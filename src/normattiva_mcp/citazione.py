"""Resa Markdown della citazione, con attribuzione — un punto solo.

`[art. 2043 c.c.](https://www.normattiva.it/uri-res/...)` è la forma che
un avvocato incolla in un parere o in un atto. Questo modulo la costruisce
sempre allo stesso modo, sia che la chiami la CLI sia l'MCP, per evitare
che le due porte producano rese diverse dello stesso URN.
"""

from __future__ import annotations

from normattiva_mcp.esiti import ATTRIBUZIONE
from normattiva_mcp.urn import Urn


def link_markdown(urn: Urn, *, testo_visibile: str) -> str:
    """`[testo_visibile](permalink)`."""
    return f"[{testo_visibile}]({urn.permalink})"


def testo_visibile_di_default(nome_fonte: str, articolo: str) -> str:
    """La forma breve di default per il testo del link: "art. 2043 c.c.",
    "art. 18 Statuto dei Lavoratori". Il chiamante può sempre passare un
    testo proprio a `link_markdown` — questa è solo la comodità di base.
    """
    return f"art. {articolo} {nome_fonte}"


def riga_attribuzione() -> str:
    """La riga di attribuzione CC BY 4.0, da mostrare insieme a ogni testo
    normativo restituito — condizione della licenza dei dati, non una
    cortesia (vedi README.md, sezione Licenza)."""
    return ATTRIBUZIONE
