"""Client dell'unico endpoint Open Data, sempre dietro il coordinatore SQLite."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

import httpx

from normattiva_mcp.config import Config
from normattiva_mcp.dto import nodo_utile
from normattiva_mcp.errori import (
    AttoInesistente,
    CoordinateSbagliate,
    EndpointNonTrovato,
    GuastoDiTrasporto,
    HttpInatteso,
    NormattivaErrore,
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
from normattiva_mcp.protezione import ProtezioneTraffico, RapportoRete
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

_FIRMA_GATEWAY = "No matching resource found"
"""La firma misurata del 404 del gateway: la chiave "description" con
questo testo. Le risposte applicative (170-171 byte) non la portano mai."""


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
)
"""Qualunque eccezione di dominio sollevata durante il tentativo di
ricaduta su vigenza storica NON deve propagarsi: l'esito originale
(abrogato) resta valido — la ricaduta può solo migliorare la risposta,
mai sostituire un errore onesto con un altro."""


@dataclass
class ClienteNormattiva:
    """Il solo componente autorizzato a preparare una chiamata HTTP reale."""

    timeout_secondi: float = 15.0
    dormi: Callable[[float], None] | None = field(default=None, repr=False)
    config: Config | None = field(default=None, repr=False)
    protezione: ProtezioneTraffico | None = field(default=None, repr=False)
    notifica_rete: Callable[[RapportoRete], None] | None = field(default=None, repr=False)
    _http: httpx.Client = field(init=False, repr=False)
    ultimi_rapporti: list[RapportoRete] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.config = self.config or Config.da_ambiente()
        if self.protezione is None:
            kwargs = {"dormi": self.dormi} if self.dormi is not None else {}
            self.protezione = ProtezioneTraffico(self.config, **kwargs)
        self._http = httpx.Client(timeout=self.timeout_secondi)

    def chiudi(self) -> None:
        self._http.close()

    def __enter__(self) -> ClienteNormattiva:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.chiudi()

    @property
    def ultimo_rapporto(self) -> RapportoRete:
        if self.ultimi_rapporti:
            return self.ultimi_rapporti[-1]
        assert self.protezione is not None
        return self.protezione.stato()

    def _pubblica(self, rapporto: RapportoRete) -> None:
        self.ultimi_rapporti.append(rapporto)
        if rapporto.origine == "rete" and self.notifica_rete:
            self.notifica_rete(rapporto)

    def leggi_articolo(
        self,
        urn: Urn,
        *,
        attivita: str = "consultazione",
        aggiorna: bool = False,
        prenotazione: str | None = None,
        recupera_storico: bool = True,
    ) -> Esito:
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
        self.ultimi_rapporti.clear()
        esito = self._richiesta_singola(
            urn, attivita=attivita, aggiorna=aggiorna, prenotazione=prenotazione
        )

        if not recupera_storico or not isinstance(esito, Abrogato) or urn.vigenza is not None:
            return esito
        if esito.data_abrogazione is None:
            return esito

        vigenza_precedente = esito.data_abrogazione - timedelta(days=1)
        try:
            esito_storico = self._richiesta_singola(
                urn.con_vigenza(vigenza_precedente),
                attivita=attivita,
                aggiorna=aggiorna,
                prenotazione=prenotazione,
            )
        except _ERRORI_DI_DOMINIO:
            return esito

        if not isinstance(esito_storico, Articolo):
            return esito

        return esito_storico.marcato(
            VigenzaStorica(data=vigenza_precedente, messaggio_corrente=esito.messaggio)
        )

    def _richiesta_singola(
        self,
        urn: Urn,
        *,
        attivita: str,
        aggiorna: bool,
        prenotazione: str | None,
    ) -> Esito:
        assert self.protezione is not None and self.config is not None

        def invia() -> httpx.Response:
            return self._http.post(
                f"{BASE_URL}/{_PERCORSO_ENDPOINT}",
                json={"urn": urn.stringa},
                headers={"Accept": "application/json", "User-Agent": self.config.user_agent},
            )

        try:
            protetta = self.protezione.esegui(
                urn.stringa,
                attivita=attivita,
                storico=urn.vigenza is not None,
                aggiorna=aggiorna,
                invia=invia,
                prenotazione=prenotazione,
            )
        except httpx.TransportError as errore:
            self._pubblica(self.protezione.rapporto_dopo_tentativo(attivita))
            raise GuastoDiTrasporto(type(errore).__name__) from errore
        except NormattivaErrore:
            # Quota, cooldown, offline e DB indisponibile bloccano prima
            # dell'HTTP: non devono produrre un falso avviso di consumo.
            raise
        except Exception:
            # `ProtezioneTraffico` registra e committa anche un errore
            # inatteso del trasporto iniettato prima di rilanciarlo.
            self._pubblica(self.protezione.rapporto_dopo_tentativo(attivita))
            raise

        richiesta = httpx.Request("POST", f"{BASE_URL}/{_PERCORSO_ENDPOINT}")
        risposta = httpx.Response(
            protetta.status,
            content=protetta.contenuto,
            headers=protetta.headers,
            request=richiesta,
        )
        if len(protetta.contenuto) > _MAX_BYTE_RISPOSTA:
            self.protezione.registra_malformata(urn.stringa)
            rapporto = self.protezione.rapporto_dopo_tentativo(attivita)
            self._pubblica(rapporto)
            raise RispostaIllegibile(dettaglio="risposta oltre il limite locale di 512 KB")
        try:
            esito = self._gestisci_risposta(risposta, urn)
        except (RispostaIllegibile, TestoAssente):
            self.protezione.registra_malformata(urn.stringa)
            rapporto = self.protezione.rapporto_dopo_tentativo(attivita)
            self._pubblica(rapporto)
            raise
        except Exception:
            self._pubblica(protetta.rapporto)
            raise
        self._pubblica(protetta.rapporto)
        return esito

    def _gestisci_risposta(self, risposta: httpx.Response, urn: Urn) -> Esito:
        status = risposta.status_code

        if status == 200:
            return self._analizza_corpo(risposta, urn)

        if status == 400:
            raise SintassiRifiutata(urn=urn.stringa)

        if status == 404:
            raise self._errore_404(risposta, urn)

        if 500 <= status < 600:
            raise ServizioInAvaria(status)

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
