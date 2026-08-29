"""Il client HTTP: un solo endpoint, i tre 404, il 500 "servizio giù", e
la ricaduta automatica su vigenza passata quando un articolo è abrogato.

Parla con UN SOLO endpoint — `atto/dettaglio-atto-urn`, in POST — e non ha,
per scelta, nessun metodo che scarichi il permalink HTML: sarebbe
2.591.983 byte contro 1.287 per un contenuto peggiore (docs/MISURE.md §2,
fattore 2.013x).

Le costanti operative vengono tutte da docs/MISURE.md:
  - §8: ~800 richieste, zero 429, zero 5xx sistematici, mediana 0,26 s.
    Nessun rate limit osservato sull'endpoint dati. Backoff e circuit
    breaker restano prudenza dichiarata, non risposta a un limite misurato.
  - §4.3: i 404 distinti (due applicativi + quello del gateway).
  - §7: l'avaria del 29/08/2026 — un 500 è "il servizio è giù adesso",
    mai un giudizio sulla norma, mai un motivo per ritentare da soli.

Client HTTP sincrono (httpx.Client), come il progetto gemello mcp-bdm:
nessun altro punto di questo pacchetto ha bisogno di un client asincrono.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

import httpx

from normattiva_mcp.dto import nodo_utile
from normattiva_mcp.errori import (
    AttoInesistente,
    CircuitoAperto,
    CoordinateSbagliate,
    EndpointNonTrovato,
    GuastoDiTrasporto,
    HttpInatteso,
    RispostaIllegibile,
    ServizioInAvaria,
    SintassiRifiutata,
    TestoAssente,
)
from normattiva_mcp.esiti import Abrogato, Articolo, Esito, Preambolo, VigenzaStorica
from normattiva_mcp.parser import Abrogato as AbrogatoParser
from normattiva_mcp.parser import HeadingDiscordante, HtmlVuoto
from normattiva_mcp.parser import Preambolo as PreamboloParser
from normattiva_mcp.parser import analizza as analizza_html
from normattiva_mcp.urn import Urn

BASE_URL = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"
"""La base del BFF, in UN punto solo. È un BFF interno non versionato: se
cambia, cambia qui e da nessun'altra parte (docs/LIMITI.md)."""

_PERCORSO_ENDPOINT = "atto/dettaglio-atto-urn"
"""L'unico endpoint usato. Il segmento "atto/" NON è decorativo: senza,
il gateway risponde 404 "No matching resource found for given API
Request"."""

_MAX_BYTE_RISPOSTA = 512 * 1024
"""512 KB. L'articolo più grosso osservato via API è nell'ordine delle
decine di KB (l'art. 18 l. 300/1970 sta in 21.496 byte); 512 KB lascia un
margine ampio e comunque taglia l'atto intero se qualcosa andasse storto."""

_MAX_RITENTATIVI = 2
"""Ritentativi SOLO su guasto di trasporto o 5xx. Mai su 4xx: un 400 o un
404 sono risposte corrette dell'API a una domanda sbagliata."""

_PAUSE_BACKOFF = (1.0, 2.0)
"""Nessun 429 mai osservato: le pause sono prudenza dichiarata, non
risposta a un rate limit misurato."""

_SOGLIA_GUASTI_CIRCUITO = 3
_PAUSA_CIRCUITO_SECONDI = 60.0
"""3 guasti consecutivi -> 60 s di sospensione, per non insistere contro
un servizio che sta chiaramente rifiutando."""

_FIRMA_GATEWAY = "No matching resource found"
"""La firma misurata del 404 del gateway: la chiave "description" con
questo testo. Le risposte applicative (170-171 byte) non la portano mai."""


@dataclass
class _StatoCircuito:
    """Stato mutabile del circuit breaker, isolato in un solo posto."""

    guasti_consecutivi: int = 0
    aperto_da: float | None = None

    def deve_essere_chiuso(self) -> None:
        """Solleva CircuitoAperto se il circuito è aperto e la pausa non è
        ancora scaduta. Alla scadenza si richiude da solo, in mezza
        apertura: il tentativo successivo passa, e se fallisce riapre
        subito (il contatore resta alla soglia)."""
        if self.aperto_da is None:
            return
        trascorso = time.monotonic() - self.aperto_da
        if trascorso >= _PAUSA_CIRCUITO_SECONDI:
            self.aperto_da = None
            self.guasti_consecutivi = _SOGLIA_GUASTI_CIRCUITO - 1
            return
        raise CircuitoAperto(riapre_tra_secondi=_PAUSA_CIRCUITO_SECONDI - trascorso)

    def registra_guasto(self) -> None:
        self.guasti_consecutivi += 1
        if self.guasti_consecutivi >= _SOGLIA_GUASTI_CIRCUITO and self.aperto_da is None:
            self.aperto_da = time.monotonic()

    def registra_servizio_raggiunto(self) -> None:
        """Il servizio ha risposto, anche con un 400 o un 404: non è
        guasto — solo un 5xx o un errore di trasporto lo è."""
        self.guasti_consecutivi = 0
        self.aperto_da = None


_ERRORI_DI_DOMINIO = (
    AttoInesistente,
    CoordinateSbagliate,
    EndpointNonTrovato,
    SintassiRifiutata,
    HttpInatteso,
    RispostaIllegibile,
    TestoAssente,
    ServizioInAvaria,
    GuastoDiTrasporto,
    CircuitoAperto,
)
"""Qualunque eccezione di dominio sollevata durante il tentativo di
ricaduta su vigenza storica NON deve propagarsi: l'esito originale
(abrogato) resta valido — la ricaduta può solo migliorare la risposta,
mai sostituire un errore onesto con un altro."""


@dataclass
class ClienteNormattiva:
    """Il client. Un'istanza mantiene lo stato del circuit breaker fra le
    chiamate — va riusata per la vita di un processo, non ricreata a ogni
    richiesta."""

    timeout_secondi: float = 15.0
    dormi: Callable[[float], None] = field(default=time.sleep, repr=False)
    """La funzione di pausa per il backoff, iniettabile. Nei test si passa
    una funzione che non dorme davvero (es. `lambda s: None`), così un
    circuito che apre dopo tre guasti non fa aspettare la suite per
    secondi reali — la pausa resta comunque misurata (viene chiamata con
    il valore giusto), solo non eseguita per davvero."""
    _http: httpx.Client = field(init=False, repr=False)
    _circuito: _StatoCircuito = field(default_factory=_StatoCircuito, repr=False)

    def __post_init__(self) -> None:
        self._http = httpx.Client(timeout=self.timeout_secondi)

    def chiudi(self) -> None:
        self._http.close()

    def __enter__(self) -> ClienteNormattiva:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.chiudi()

    def leggi_articolo(self, urn: Urn) -> Esito:
        """L'operazione principale: dato un URN, il testo verificato
        dell'articolo (o abrogato, o preambolo — mai un errore silenzioso).

        Ricaduta su vigenza passata, una sola, mai due. Se la richiesta
        alla vigenza corrente risponde "abrogato", e il chiamante non
        aveva già chiesto una vigenza, e il messaggio porta una data
        leggibile, si ritenta con !vig= al giorno PRECEDENTE
        l'abrogazione — l'ultimo giorno derivabile in cui la norma era in
        vigore. Se la seconda richiesta non restituisce un vero articolo
        (un secondo abrogato, un preambolo, un errore), l'esito originale
        resta quello valido: la ricaduta può solo migliorare la risposta,
        mai sostituire un errore onesto con un altro.
        """
        esito = self._richiesta_singola(urn)

        if not isinstance(esito, Abrogato) or urn.vigenza is not None:
            return esito
        if esito.data_abrogazione is None:
            return esito

        vigenza_precedente = esito.data_abrogazione - timedelta(days=1)
        try:
            esito_storico = self._richiesta_singola(urn.con_vigenza(vigenza_precedente))
        except _ERRORI_DI_DOMINIO:
            return esito

        if not isinstance(esito_storico, Articolo):
            return esito

        return esito_storico.marcato(
            VigenzaStorica(data=vigenza_precedente, messaggio_corrente=esito.messaggio)
        )

    def _richiesta_singola(self, urn: Urn) -> Esito:
        """Una singola andata e ritorno con l'API, ritentativi e circuito
        compresi. Separata da leggi_articolo perché la ricaduta a vigenza
        passata deve poterne fare due senza duplicare backoff o circuito.
        """
        self._circuito.deve_essere_chiuso()

        ultimo_errore: Exception = GuastoDiTrasporto("nessun tentativo eseguito")

        for tentativo in range(_MAX_RITENTATIVI + 1):
            try:
                risposta = self._http.post(
                    f"{BASE_URL}/{_PERCORSO_ENDPOINT}",
                    json={"urn": urn.stringa},
                    headers={"Accept": "application/json"},
                )
            except httpx.TransportError as errore:
                self._circuito.registra_guasto()
                ultimo_errore = GuastoDiTrasporto(str(errore))
            else:
                esito = self._gestisci_risposta(risposta, urn)
                if esito is not None:
                    return esito
                # 5xx: registrato dentro _gestisci_risposta, si continua
                # il ciclo per ritentare (se restano tentativi).
                ultimo_errore = ServizioInAvaria(risposta.status_code)

            if self._circuito.aperto_da is not None:
                raise CircuitoAperto(riapre_tra_secondi=_PAUSA_CIRCUITO_SECONDI)
            if tentativo >= _MAX_RITENTATIVI:
                break
            self.dormi(_PAUSE_BACKOFF[min(tentativo, len(_PAUSE_BACKOFF) - 1)])

        raise ultimo_errore

    def _gestisci_risposta(self, risposta: httpx.Response, urn: Urn) -> Esito | None:
        """Restituisce l'esito su una risposta definitiva (200/400/404 e
        stati imprevisti), o None per un 5xx (da ritentare)."""
        status = risposta.status_code

        if status == 200:
            self._circuito.registra_servizio_raggiunto()
            return self._analizza_corpo(risposta, urn)

        if status == 400:
            self._circuito.registra_servizio_raggiunto()
            raise SintassiRifiutata(urn=urn.stringa)

        if status == 404:
            self._circuito.registra_servizio_raggiunto()
            raise self._errore_404(risposta, urn)

        if 500 <= status < 600:
            self._circuito.registra_guasto()
            return None

        self._circuito.registra_servizio_raggiunto()
        raise HttpInatteso(status=status)

    def _analizza_corpo(self, risposta: httpx.Response, urn: Urn) -> Esito:
        try:
            corpo = risposta.json()
        except json.JSONDecodeError as errore:
            raise RispostaIllegibile(dettaglio=str(errore)) from errore

        nodo = nodo_utile(corpo)
        if nodo is None or not nodo.articolo_html:
            raise TestoAssente(urn=urn.stringa)

        try:
            esito_parser = analizza_html(nodo.articolo_html, richiesto=urn.articolo)
        except HeadingDiscordante as errore:
            raise CoordinateSbagliate(urn=urn.stringa, dump=str(errore)) from errore
        except HtmlVuoto as errore:
            raise TestoAssente(urn=urn.stringa) from errore

        if isinstance(esito_parser, AbrogatoParser):
            return Abrogato(
                urn=urn,
                messaggio=esito_parser.messaggio,
                data_abrogazione=esito_parser.data_abrogazione,
            )
        if isinstance(esito_parser, PreamboloParser):
            return Preambolo(
                urn=urn,
                caratteri=esito_parser.caratteri,
                incipit=esito_parser.incipit,
            )
        return Articolo(
            urn=urn,
            heading=esito_parser.heading,
            testo=esito_parser.testo,
            aggiornamenti=esito_parser.aggiornamenti,
            data_inizio_vigenza=nodo.articolo_data_inizio_vigenza,
        )

    def _errore_404(self, risposta: httpx.Response, urn: Urn) -> Exception:
        """Tre 404, non due. L'ordine conta: il 404 del gateway si
        riconosce PRIMA, perché è l'unico che non parla dell'atto — parla
        di noi."""
        try:
            corpo = risposta.json()
        except json.JSONDecodeError:
            corpo = None

        if isinstance(corpo, dict):
            descrizione = corpo.get("description")
            if isinstance(descrizione, str) and _FIRMA_GATEWAY in descrizione:
                return EndpointNonTrovato(dettaglio=descrizione)

            messaggio = corpo.get("message")
            # Il dump di coordinate sbagliate porta chiave:valore dentro
            # la stringa message (non chiavi JSON separate).
            if (
                isinstance(messaggio, str)
                and messaggio.strip()
                and ":" in messaggio
                and "codiceRedazionale" in messaggio
            ):
                return CoordinateSbagliate(urn=urn.stringa, dump=messaggio)

        return AttoInesistente(urn=urn.stringa)
