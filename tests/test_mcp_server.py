"""Test del server MCP — nessuna rete reale: `ClienteNormattiva` riceve un
`httpx.MockTransport`, come in `test_cli.py`. `@server.tool` restituisce la
funzione originale invariata (non un wrapper), quindi le chiamate ai tool
sono chiamate dirette con un `ctx` finto che porta `ApplicazioneMcp` nel
contesto (stesso pattern del gemello `mcp-bdm`).
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from normattiva_mcp import mcp_server
from normattiva_mcp.client import ClienteNormattiva
from normattiva_mcp.lookup import FonteNonDisponibileErrore, RiferimentoSconosciuto
from normattiva_mcp.urn import UrnNonValido

_NOMI_ATTESI = frozenset(
    {
        "normattiva_leggi_articolo",
        "normattiva_link",
        "normattiva_trova_fonte",
        "normattiva_leggi_urn",
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


def _app_finta(gestore: Callable[[httpx.Request], httpx.Response]) -> mcp_server.ApplicazioneMcp:
    client = ClienteNormattiva(dormi=lambda _secondi: None)
    client._http = httpx.Client(transport=httpx.MockTransport(gestore))
    return mcp_server.ApplicazioneMcp(client=client)


def _ctx_finto(app: mcp_server.ApplicazioneMcp) -> Any:
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app))


def test_il_server_espone_esattamente_quattro_strumenti() -> None:
    strumenti = mcp_server.server._tool_manager.list_tools()
    assert len(strumenti) == 4


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
    assert risultato.avvisi == []


@pytest.mark.asyncio
async def test_leggi_articolo_fonte_sconosciuta_solleva_errore_di_dominio() -> None:
    app = _app_finta(lambda _r: httpx.Response(500))
    with pytest.raises(RiferimentoSconosciuto):
        await mcp_server.normattiva_leggi_articolo(
            _ctx_finto(app), fonte="una fonte inventata", articolo="1"
        )


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
async def test_leggi_urn_malformato_solleva_urn_non_valido() -> None:
    app = _app_finta(lambda _r: httpx.Response(500))
    with pytest.raises(UrnNonValido):
        await mcp_server.normattiva_leggi_urn(_ctx_finto(app), urn="non un urn")


@pytest.mark.asyncio
async def test_un_errore_imprevisto_esce_sanificato() -> None:
    def gestore(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("frammento imprevisto di una risposta")

    app = _app_finta(gestore)
    with pytest.raises(mcp_server.ErroreInternoMcp) as exc_info:
        await mcp_server.normattiva_leggi_articolo(
            _ctx_finto(app), fonte="codice civile", articolo="2043"
        )
    assert "frammento imprevisto" not in str(exc_info.value)
    assert "RuntimeError" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fonte_dichiaratamente_non_disponibile_solleva_errore_dedicato() -> None:
    app = _app_finta(lambda _r: httpx.Response(500))
    from normattiva_mcp.fonti import carica_tabella

    non_disponibili = carica_tabella().non_disponibili
    if not non_disponibili:
        pytest.skip("nessuna fonte non disponibile in tabella")
    alias = non_disponibili[0].alias[0]
    with pytest.raises(FonteNonDisponibileErrore):
        await mcp_server.normattiva_leggi_articolo(_ctx_finto(app), fonte=alias, articolo="1")
