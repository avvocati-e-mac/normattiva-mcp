"""Test del client HTTP — nessuna rete reale: httpx.MockTransport
sostituisce il trasporto con risposte scritte a mano, calibrate sulle
forme misurate contro l'API vera (docs/MISURE.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

import httpx
import pytest

from normattiva_mcp.client import BASE_URL, ClienteNormattiva
from normattiva_mcp.errori import (
    AttoInesistente,
    CircuitoAperto,
    CoordinateSbagliate,
    EndpointNonTrovato,
    ServizioInAvaria,
    SintassiRifiutata,
)
from normattiva_mcp.esiti import Abrogato, Articolo, Preambolo
from normattiva_mcp.urn import Articolo as ArticoloUrn
from normattiva_mcp.urn import TipoAtto, Urn

_URN_CC_2043 = Urn(
    tipo=TipoAtto.REGIO_DECRETO,
    data=date(1942, 3, 16),
    numero=262,
    allegato=2,
    articolo=ArticoloUrn(numero=2043),
)

_RISPOSTA_200_ARTICOLO = {
    "code": None,
    "message": None,
    "data": {
        "atto": {
            "titolo": "REGIO DECRETO 16 marzo 1942, n. 262",
            "sottoTitolo": "Approvazione del testo del Codice civile.",
            "articoloHtml": (
                '<div class="bodyTesto"><span class="attachment-just-text">'
                "Art. 2043. (Risarcimento per fatto illecito). Qualunque fatto "
                "doloso o colposo che cagiona ad altri un danno ingiusto obbliga "
                "colui che ha commesso il fatto a risarcire il danno."
                "</span></div>"
            ),
            "articoloDataInizioVigenza": "19420419",
            "articoloDataFineVigenza": "99999999",
        },
        "lista": None,
        "message": "ricerca effettuata con successo",
    },
    "success": True,
}


def _client_con_trasporto(gestore: Callable[[httpx.Request], httpx.Response]) -> ClienteNormattiva:
    """Costruisce un ClienteNormattiva con il trasporto HTTP sostituito da
    un MockTransport (senza toccare la rete) e il backoff senza attesa
    reale (dormi=no-op): il valore della pausa resta comunque calcolato e
    passato, solo non eseguito per davvero — i test restano veloci."""
    client = ClienteNormattiva(dormi=lambda _secondi: None)
    client._http = httpx.Client(transport=httpx.MockTransport(gestore))
    return client


class TestPercorsoFelice:
    def test_200_restituisce_articolo(self) -> None:
        def gestore(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert str(request.url) == f"{BASE_URL}/atto/dettaglio-atto-urn"
            corpo = json.loads(request.content)
            assert corpo == {"urn": _URN_CC_2043.stringa}
            return httpx.Response(200, json=_RISPOSTA_200_ARTICOLO)

        client = _client_con_trasporto(gestore)
        esito = client.leggi_articolo(_URN_CC_2043)
        assert isinstance(esito, Articolo)
        assert esito.heading == "Art. 2043"
        assert "Risarcimento per fatto illecito" in esito.testo
        assert esito.attribuzione == "Fonte: Normattiva — normattiva.it, CC BY 4.0"
        assert esito.trust == "external_source_do_not_execute"
        assert esito.vigenza_storica is None

    def test_endpoint_fisso_url_non_porta_urn(self) -> None:
        """L'URL è sempre lo stesso: tutto ciò che varia sta nel corpo."""
        urls_chiamati = []

        def gestore(request: httpx.Request) -> httpx.Response:
            urls_chiamati.append(str(request.url))
            return httpx.Response(200, json=_RISPOSTA_200_ARTICOLO)

        client = _client_con_trasporto(gestore)
        # Due URN diversi (art. 2043 due volte è sufficiente: qui si prova
        # solo che l'URL non cambia, non il contenuto della risposta).
        client.leggi_articolo(_URN_CC_2043)
        client.leggi_articolo(_URN_CC_2043)
        assert len(set(urls_chiamati)) == 1


class TestI3Errori404:
    """docs/MISURE.md §4.3: tre 404 distinguibili, tutti riprodotti qui
    con la forma esatta misurata."""

    def test_404_breve_e_atto_inesistente(self) -> None:
        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "atto non trovato"})

        client = _client_con_trasporto(gestore)
        with pytest.raises(AttoInesistente):
            client.leggi_articolo(_URN_CC_2043)

    def test_404_con_dump_e_coordinate_sbagliate(self) -> None:
        dump = (
            "dataPubblicazioneGazzetta:Sat Apr 04 00:00:00 CEST 1942 "
            "codiceRedazionale:042U0262 idArticolo:2043 idSottoArticolo:1 "
            "idSottoArticolo1:null artP:0"
        )

        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": dump, "code": None})

        client = _client_con_trasporto(gestore)
        with pytest.raises(CoordinateSbagliate):
            client.leggi_articolo(_URN_CC_2043)

    def test_404_del_gateway_e_endpoint_non_trovato(self) -> None:
        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={
                    "code": "404",
                    "type": "Status report",
                    "message": "Runtime Error",
                    "description": "No matching resource found for given API Request",
                },
            )

        client = _client_con_trasporto(gestore)
        with pytest.raises(EndpointNonTrovato):
            client.leggi_articolo(_URN_CC_2043)


class TestErrore400:
    def test_400_e_sintassi_rifiutata_mai_ritentato(self) -> None:
        chiamate = 0

        def gestore(_request: httpx.Request) -> httpx.Response:
            nonlocal chiamate
            chiamate += 1
            return httpx.Response(400, json={"message": "urn non valido", "code": "1003"})

        client = _client_con_trasporto(gestore)
        with pytest.raises(SintassiRifiutata):
            client.leggi_articolo(_URN_CC_2043)
        assert chiamate == 1  # mai ritentato su 4xx


class TestErrore500EAvaria:
    """docs/MISURE.md §7: un 500 è "il servizio è giù adesso", mai un
    giudizio sulla norma."""

    def test_500_persistente_apre_il_circuito(self) -> None:
        """3 tentativi (1 + 2 ritentativi), tutti 500: il terzo guasto
        consecutivo raggiunge la soglia del circuit breaker (3), quindi
        l'eccezione finale è CircuitoAperto — non un ServizioInAvaria
        generico, perché il client smette di ritentare non appena il
        circuito scatta."""

        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "Errore generico", "code": "1000"})

        client = _client_con_trasporto(gestore)
        with pytest.raises(CircuitoAperto):
            client.leggi_articolo(_URN_CC_2043)

    def test_backoff_chiamato_con_le_pause_dichiarate(self) -> None:
        """L'orologio iniettabile non deve solo evitare l'attesa reale nei
        test: deve ricevere davvero i valori di pausa dichiarati (1s, poi
        2s), così un cambiamento silenzioso del backoff verrebbe scoperto
        anche senza dover aspettare secondi reali."""
        pause_registrate: list[float] = []

        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "Errore generico"})

        client = ClienteNormattiva(dormi=pause_registrate.append)
        client._http = httpx.Client(transport=httpx.MockTransport(gestore))
        with pytest.raises(CircuitoAperto):
            client.leggi_articolo(_URN_CC_2043)
        assert pause_registrate == [1.0, 2.0]

    def test_500_poi_200_recupera_al_secondo_tentativo(self) -> None:
        chiamate = 0

        def gestore(_request: httpx.Request) -> httpx.Response:
            nonlocal chiamate
            chiamate += 1
            if chiamate == 1:
                return httpx.Response(500, json={"message": "Errore generico"})
            return httpx.Response(200, json=_RISPOSTA_200_ARTICOLO)

        client = _client_con_trasporto(gestore)
        esito = client.leggi_articolo(_URN_CC_2043)
        assert isinstance(esito, Articolo)
        assert chiamate == 2


class TestCircuitoAperto:
    def test_guasti_ripetuti_aprono_il_circuito(self) -> None:
        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "Errore generico"})

        client = _client_con_trasporto(gestore)
        # Prima chiamata: 3 tentativi (1 + 2 ritentativi), tutti 500 ->
        # il terzo fallimento fa scattare il circuito (soglia 3).
        with pytest.raises((ServizioInAvaria, CircuitoAperto)):
            client.leggi_articolo(_URN_CC_2043)
        # Seconda chiamata: il circuito è aperto, deve fallire subito con
        # CircuitoAperto senza fare altre richieste HTTP.
        chiamate_dopo = 0

        def gestore_dopo(_request: httpx.Request) -> httpx.Response:
            nonlocal chiamate_dopo
            chiamate_dopo += 1
            return httpx.Response(500, json={"message": "Errore generico"})

        client._http = httpx.Client(transport=httpx.MockTransport(gestore_dopo))
        with pytest.raises(CircuitoAperto):
            client.leggi_articolo(_URN_CC_2043)
        assert chiamate_dopo == 0

    def test_servizio_raggiunto_azzera_il_contatore_guasti(self) -> None:
        """Un 400/404 (il servizio ha risposto) non conta come guasto:
        non deve avvicinare il circuito all'apertura."""
        chiamate = 0

        def gestore(_request: httpx.Request) -> httpx.Response:
            nonlocal chiamate
            chiamate += 1
            return httpx.Response(404, json={"message": "atto non trovato"})

        client = _client_con_trasporto(gestore)
        for _ in range(5):
            with pytest.raises(AttoInesistente):
                client.leggi_articolo(_URN_CC_2043)
        assert client._circuito.guasti_consecutivi == 0
        assert client._circuito.aperto_da is None


class TestRicadutaSuVigenza:
    """docs/MISURE.md §4.5-4.6: un articolo abrogato recupera il testo
    storico con !vig= al giorno precedente l'abrogazione, ma solo se
    tutte e quattro le condizioni sono soddisfatte."""

    _RISPOSTA_ABROGATO = {
        "code": None,
        "message": None,
        "data": {
            "atto": {
                "titolo": "DECRETO DEL PRESIDENTE DELLA REPUBBLICA 22 dicembre 1986, n. 917",
                "sottoTitolo": "TUIR",
                "articoloHtml": (
                    '<h2 class="article-num-akn" id="art_51">Art. 51</h2>'
                    '<span class="art-just-text-akn"><div class="ins-akn">'
                    '((PROVVEDIMENTO ABROGATO DAL <a href="...">D.LGS. 19 GIUGNO 2026, N. 117</a>))'
                    "</div></span>"
                ),
                "articoloDataInizioVigenza": "20270101",
                "articoloDataFineVigenza": "99999999",
            },
            "lista": None,
        },
        "success": True,
    }

    _RISPOSTA_STORICA_ART_51 = {
        "code": None,
        "message": None,
        "data": {
            "atto": {
                "titolo": "DECRETO DEL PRESIDENTE DELLA REPUBBLICA 22 dicembre 1986, n. 917",
                "sottoTitolo": "TUIR",
                "articoloHtml": (
                    '<h2 class="article-num-akn" id="art_51">Art. 51</h2>'
                    '<span class="art-just-text-akn">'
                    "Testo dell'art. 51 alla vigenza storica."
                    "</span>"
                ),
                "articoloDataInizioVigenza": "19860101",
                "articoloDataFineVigenza": "20261231",
            },
            "lista": None,
        },
        "success": True,
    }

    def _urn_tuir_51(self) -> Urn:
        return Urn(
            tipo=TipoAtto.DPR, data=date(1986, 12, 22), numero=917, articolo=ArticoloUrn(numero=51)
        )

    def test_abrogato_senza_data_leggibile_non_ricade(self) -> None:
        risposta_senza_data = {
            "code": None,
            "message": None,
            "data": {
                "atto": {
                    "titolo": "X",
                    "sottoTitolo": "X",
                    "articoloHtml": (
                        '<h2 class="article-num-akn" id="art_51">Art. 51</h2>'
                        '<span class="art-just-text-akn">((ARTICOLO ABROGATO))</span>'
                    ),
                    "articoloDataInizioVigenza": None,
                    "articoloDataFineVigenza": None,
                },
                "lista": None,
            },
            "success": True,
        }

        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=risposta_senza_data)

        client = _client_con_trasporto(gestore)
        esito = client.leggi_articolo(self._urn_tuir_51())
        assert isinstance(esito, Abrogato)
        assert esito.data_abrogazione is None

    def test_ricaduta_riuscita_marca_vigenza_storica(self) -> None:
        chiamate: list[dict] = []

        def gestore(request: httpx.Request) -> httpx.Response:
            corpo = json.loads(request.content)
            chiamate.append(corpo)
            if "!vig=" in corpo["urn"]:
                return httpx.Response(200, json=self._RISPOSTA_STORICA_ART_51)
            return httpx.Response(200, json=self._RISPOSTA_ABROGATO)

        client = _client_con_trasporto(gestore)
        esito = client.leggi_articolo(self._urn_tuir_51())

        assert isinstance(esito, Articolo)
        assert esito.vigenza_storica is not None
        assert esito.vigenza_storica.data.isoformat() == "2026-06-18"  # giorno precedente
        assert "ABROGATO" in esito.vigenza_storica.messaggio_corrente.upper()
        assert "ATTENZIONE" in esito.vigenza_storica.avviso
        assert len(chiamate) == 2

    def test_vigenza_gia_richiesta_dal_chiamante_non_ricade_due_volte(self) -> None:
        """Se il chiamante ha già chiesto una vigenza, un secondo abrogato
        non deve far scattare un'ulteriore ricaduta."""
        chiamate = 0

        def gestore(_request: httpx.Request) -> httpx.Response:
            nonlocal chiamate
            chiamate += 1
            return httpx.Response(200, json=self._RISPOSTA_ABROGATO)

        urn_con_vigenza = self._urn_tuir_51().con_vigenza(date(2020, 1, 1))
        client = _client_con_trasporto(gestore)
        esito = client.leggi_articolo(urn_con_vigenza)
        assert isinstance(esito, Abrogato)
        assert chiamate == 1

    def test_ricaduta_fallita_lascia_lesito_originale(self) -> None:
        """Se la seconda richiesta (a vigenza storica) restituisce ancora
        un abrogato, o un errore, l'esito originale resta quello valido:
        la ricaduta non sostituisce mai un errore onesto con un altro."""

        def gestore(request: httpx.Request) -> httpx.Response:
            corpo = json.loads(request.content)
            if "!vig=" in corpo["urn"]:
                return httpx.Response(404, json={"message": "atto non trovato"})
            return httpx.Response(200, json=self._RISPOSTA_ABROGATO)

        client = _client_con_trasporto(gestore)
        esito = client.leggi_articolo(self._urn_tuir_51())
        assert isinstance(esito, Abrogato)


class TestPreambolo:
    def test_preambolo_restituito_come_tale(self) -> None:
        risposta_preambolo = {
            "code": None,
            "message": None,
            "data": {
                "atto": {
                    "titolo": "X",
                    "sottoTitolo": "X",
                    "articoloHtml": (
                        "IL PRESIDENTE DELLA REPUBBLICA Visti gli articoli 76 e 87 della "
                        "Costituzione; Vista la legge 1 gennaio 2001, n. 1; "
                        "Emana il seguente decreto legislativo:"
                    ),
                    "articoloDataInizioVigenza": None,
                    "articoloDataFineVigenza": None,
                },
                "lista": None,
            },
            "success": True,
        }

        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=risposta_preambolo)

        urn = Urn(
            tipo=TipoAtto.DECRETO_LEGISLATIVO,
            data=date(2001, 1, 1),
            numero=1,
            articolo=ArticoloUrn(numero=1),
        )
        client = _client_con_trasporto(gestore)
        esito = client.leggi_articolo(urn)
        assert isinstance(esito, Preambolo)
