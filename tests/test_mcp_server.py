"""Test del server MCP — nessuna rete reale: `ClienteNormattiva` riceve un
`httpx.MockTransport`, come in `test_cli.py`. Le chiamate ai tool sono
chiamate dirette a `mcp_server.normattiva_*`, che è già il risultato del
decoratore `@_traduci_errori` (vedi il docstring del modulo): ogni
eccezione di dominio arriva quindi come `ToolError` con lo stesso
messaggio, mai come l'eccezione originale — è il comportamento vero
osservato da Claude Desktop il 29/08/2026, non un dettaglio dei test.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from normattiva_mcp import mcp_server
from normattiva_mcp.client import ClienteNormattiva

_NOMI_ATTESI = frozenset(
    {
        "normattiva_leggi_articolo",
        "normattiva_link",
        "normattiva_trova_fonte",
        "normattiva_leggi_urn",
        "normattiva_stato_rete",
    }
)

_RISPOSTA_CC_2043 = {
    "code": None,
    "message": None,
    "data": {
        "atto": {
            "titolo": "REGIO DECRETO 16 marzo 1942, n. 262",
            "sottoTitolo": "Codice civile",
            "articoloHtml": (
                '<span class="attachment-just-text">Art. 2043. '
                "(Risarcimento per fatto illecito). Qualunque fatto doloso o "
                "colposo che cagiona ad altri un danno ingiusto obbliga colui "
                "che ha commesso il fatto a risarcire il danno.</span>"
            ),
            "articoloDataInizioVigenza": "19420419",
            "articoloDataFineVigenza": "99999999",
        },
        "lista": None,
    },
    "success": True,
}


@pytest.fixture(autouse=True)
def _stato_protettivo_isolato(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Il database condiviso in produzione non deve far passare cache fra test."""
    monkeypatch.setenv("NORMATTIVA_STATO_DB", str(tmp_path / "protezione.sqlite3"))


def _app_finta(gestore: Callable[[httpx.Request], httpx.Response]) -> mcp_server.ApplicazioneMcp:
    client = ClienteNormattiva(dormi=lambda _secondi: None)
    client._http = httpx.Client(transport=httpx.MockTransport(gestore))
    return mcp_server.ApplicazioneMcp(client=client)


def _ctx_finto(app: mcp_server.ApplicazioneMcp) -> Any:
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app))


def test_il_server_espone_esattamente_cinque_strumenti() -> None:
    strumenti = mcp_server.server._tool_manager.list_tools()
    assert len(strumenti) == 5


def test_i_nomi_degli_strumenti_sono_quelli_previsti() -> None:
    nomi = {strumento.name for strumento in mcp_server.server._tool_manager.list_tools()}
    assert nomi == _NOMI_ATTESI


def test_il_trasporto_e_solo_stdio() -> None:
    import inspect

    sorgente = inspect.getsource(mcp_server.main)
    assert 'transport="stdio"' in sorgente or "transport='stdio'" in sorgente
    assert "sse" not in sorgente
    assert "streamable-http" not in sorgente


def test_il_server_dichiara_istruzioni_non_vuote() -> None:
    assert mcp_server.server.instructions
    assert len(mcp_server.server.instructions) > 100


@pytest.mark.asyncio
async def test_leggi_articolo_codice_civile_2043() -> None:
    def gestore(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_RISPOSTA_CC_2043)

    app = _app_finta(gestore)
    risultato = await mcp_server.normattiva_leggi_articolo(
        _ctx_finto(app), fonte="codice civile", articolo="2043"
    )
    assert risultato.esito == "articolo"
    assert "Risarcimento per fatto illecito" in risultato.testo
    assert risultato.urn == "urn:nir:stato:regio.decreto:1942-03-16;262:2~art2043"
    assert "CC BY 4.0" in risultato.attribuzione
    assert risultato.avvisi == ["consultazione 1/30 — totale 1/60"]
    assert risultato.protezione_rete.origine == "rete"
    assert risultato.protezione_rete.consumo_attivita == "1/30"
    assert risultato.protezione_rete.livello == "ok"


@pytest.mark.asyncio
async def test_leggi_articolo_fonte_sconosciuta_arriva_come_tool_error() -> None:
    app = _app_finta(lambda _r: httpx.Response(500))
    with pytest.raises(ToolError) as exc_info:
        await mcp_server.normattiva_leggi_articolo(
            _ctx_finto(app), fonte="una fonte inventata", articolo="1"
        )
    assert "Nessuna fonte normativa nota" in str(exc_info.value)


@pytest.mark.asyncio
async def test_link_costruisce_e_verifica_per_difetto() -> None:
    def gestore(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_RISPOSTA_CC_2043)

    app = _app_finta(gestore)
    risultato = await mcp_server.normattiva_link(
        _ctx_finto(app), fonte="codice civile", articolo="2043"
    )
    assert risultato.verificato is True
    assert "art. 2043 Codice Civile" in risultato.markdown
    assert "normattiva.it" in risultato.markdown


@pytest.mark.asyncio
async def test_link_non_verificato_su_richiesta_non_tocca_la_rete() -> None:
    def gestore(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("non deve partire nessuna richiesta con verifica=False")

    app = _app_finta(gestore)
    risultato = await mcp_server.normattiva_link(
        _ctx_finto(app), fonte="codice civile", articolo="2043", verifica=False
    )
    assert risultato.verificato is None
    assert risultato.avviso is None


@pytest.mark.asyncio
async def test_trova_fonte_riconosciuta() -> None:
    app = _app_finta(lambda _r: httpx.Response(500))
    risultato = await mcp_server.normattiva_trova_fonte(_ctx_finto(app), testo="codice civile")
    assert risultato.trovata is True
    assert risultato.disponibile is True
    assert risultato.allegato == 2


@pytest.mark.asyncio
async def test_trova_fonte_sconosciuta() -> None:
    app = _app_finta(lambda _r: httpx.Response(500))
    risultato = await mcp_server.normattiva_trova_fonte(
        _ctx_finto(app), testo="una fonte che non esiste da nessuna parte"
    )
    assert risultato.trovata is False
    assert risultato.disponibile is None


@pytest.mark.asyncio
async def test_stato_rete_e_locale_e_non_tocca_http() -> None:
    def gestore(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("lo stato non deve contattare Normattiva")

    app = _app_finta(gestore)
    risultato = await mcp_server.normattiva_stato_rete(_ctx_finto(app))
    assert risultato.rapporto.origine == "locale"
    assert risultato.rapporto.livello == "ok"
    assert risultato.aggregati_giornalieri["richieste_reali"] == 0


@pytest.mark.asyncio
async def test_leggi_urn_valido() -> None:
    def gestore(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_RISPOSTA_CC_2043)

    app = _app_finta(gestore)
    risultato = await mcp_server.normattiva_leggi_urn(
        _ctx_finto(app), urn="urn:nir:stato:regio.decreto:1942-03-16;262:2~art2043"
    )
    assert risultato.esito == "articolo"


@pytest.mark.asyncio
async def test_leggi_urn_malformato_arriva_come_tool_error() -> None:
    app = _app_finta(lambda _r: httpx.Response(500))
    with pytest.raises(ToolError) as exc_info:
        await mcp_server.normattiva_leggi_urn(_ctx_finto(app), urn="non un urn")
    assert "urn" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_un_errore_imprevisto_esce_come_tool_error_sanificato() -> None:
    """Il caso reale osservato il 29/08/2026: senza `_traduci_errori`, un
    un errore di dominio veniva nascosto dall'SDK se non era tradotto in
    `ToolError`. Qui si verifica il caso imprevisto, che resta sanificato."""

    def gestore(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("frammento imprevisto di una risposta")

    app = _app_finta(gestore)
    with pytest.raises(ToolError) as exc_info:
        await mcp_server.normattiva_leggi_articolo(
            _ctx_finto(app), fonte="codice civile", articolo="2043"
        )
    assert "frammento imprevisto" not in str(exc_info.value)
    assert "RuntimeError" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fonte_dichiaratamente_non_disponibile_arriva_come_tool_error() -> None:
    app = _app_finta(lambda _r: httpx.Response(500))
    from normattiva_mcp.fonti import carica_tabella

    non_disponibili = carica_tabella().non_disponibili
    if not non_disponibili:
        pytest.skip("nessuna fonte non disponibile in tabella")
    alias = non_disponibili[0].alias[0]
    with pytest.raises(ToolError) as exc_info:
        await mcp_server.normattiva_leggi_articolo(_ctx_finto(app), fonte=alias, articolo="1")
    assert "non è disponibile su Normattiva" in str(exc_info.value)


@pytest.mark.asyncio
async def test_5xx_arriva_come_tool_error_con_cooldown_e_senza_retry() -> None:
    """Il primo 5xx basta: porta cooldown nel messaggio, senza retry."""

    def gestore(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    app = _app_finta(gestore)
    with pytest.raises(ToolError) as exc_info:
        await mcp_server.normattiva_leggi_articolo(
            _ctx_finto(app), fonte="codice civile", articolo="2043"
        )
    assert "anomalia temporanea" in str(exc_info.value)
    assert "cooldown fino" in str(exc_info.value)
