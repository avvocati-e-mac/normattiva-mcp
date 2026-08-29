"""Il tetto sul sapere consegnato al modello a ogni connessione MCP
(CLAUDE.md, "Il tetto sul sapere consegnato al modello").

Non è un test di stile: è la sola cosa che impedisce a istruzioni e
descrizioni di diventare prosa. Ogni carattere qui viaggia a ogni
`tools/list` — anche verso un modello debole come DeepSeek 4 flash, il
bersaglio dichiarato del progetto (CLAUDE.md, "Missione").

Se questo test arrossisce, la risposta NON è alzare il tetto: è tagliare
una frase che il modello non userebbe per scegliere diversamente, o
spostarla in `docs/`, che il modello legge solo quando gli serve.
"""

from __future__ import annotations

from normattiva_mcp import mcp_server

TETTO_CARATTERI = 5_500
"""Misurato il 29 agosto 2026, branch `mcp`: istruzioni (1.032) + quattro
descrizioni di strumento (2.673) + descrizioni dei parametri (0) = 3.705
caratteri. Il tetto lascia margine per il quinto strumento
(`normattiva_cerca`, branch `ricerca` successivo) senza doverlo alzare
al primo strumento aggiunto."""


def _istruzioni() -> str:
    istruzioni = mcp_server.server.instructions
    assert istruzioni, "il server deve dichiarare istruzioni alla connessione"
    return istruzioni


def _descrizioni() -> dict[str, str]:
    return {
        strumento.name: strumento.description or ""
        for strumento in mcp_server.server._tool_manager.list_tools()
    }


def _descrizioni_dei_parametri() -> int:
    """Caratteri delle descrizioni dei PARAMETRI: viaggiano nello stesso
    `tools/list` delle descrizioni di strumento, e una frase spostata
    dall'una all'altra uscirebbe dalla misura se non fossero contate
    insieme (stesso difetto scoperto nel gemello italgiure-web-mcp)."""
    totale = 0
    for strumento in mcp_server.server._tool_manager.list_tools():
        proprieta = (strumento.parameters or {}).get("properties", {})
        for campo in proprieta.values():
            totale += len(campo.get("description", ""))
    return totale


def test_il_sapere_consegnato_al_modello_sta_nel_tetto_dichiarato() -> None:
    istruzioni = len(_istruzioni())
    descrizioni = sum(len(testo) for testo in _descrizioni().values())
    parametri = _descrizioni_dei_parametri()
    totale = istruzioni + descrizioni + parametri

    assert totale <= TETTO_CARATTERI, (
        f"istruzioni e descrizioni costano {totale} caratteri, oltre il tetto di "
        f"{TETTO_CARATTERI}: taglia, o sposta in docs/ — non alzare il tetto per "
        "far entrare una frase (CLAUDE.md)"
    )


def test_ogni_strumento_ha_una_descrizione_non_vuota() -> None:
    for nome, descrizione in _descrizioni().items():
        assert descrizione, f"{nome} non ha una descrizione: un modello sceglie leggendola"


def test_le_istruzioni_parlano_delle_trappole_misurate() -> None:
    """Difesa contro una regressione silenziosa: un testo perduto non fa
    fallire nulla da sé — produce solo un modello che ricomincia a
    scoprire a tentoni ciò che qui è già scritto."""
    istruzioni = _istruzioni()
    assert "permalink" in istruzioni
    assert "abrogato" in istruzioni
    assert "preambolo" in istruzioni
    assert "vigenza_storica" in istruzioni
