"""Il server MCP `normattiva-mcp`: quattro strumenti, stdio soltanto.

LE DUE PORTE NON SI CHIAMANO FRA LORO (CLAUDE.md, "Struttura e stile del
codice"): questo modulo non reimplementa la risoluzione degli alias o la
lettura del testo, chiama `lookup.py`, `client.py`, `fonti.py`,
`citazione.py` — esattamente come fa `cli.py`. La sola cosa che aggiunge è
la traduzione verso il protocollo MCP.

TRASPORTO STDIO SOLTANTO: `main()` chiama `server.run()` col predefinito
`transport="stdio"`, mai `sse` o `streamable-http`.

QUATTRO STRUMENTI, NON CINQUE: `normattiva_cerca` (ricerca full-text)
dipende da `ricerca.py`, non ancora scritto — arriva al branch `ricerca`
successivo (vedi docs/HANDOFF-2026-08-29.md).

UN SOLO CLIENT PER PROCESSO, non uno per chiamata come in `cli.py`: il
circuit breaker di `ClienteNormattiva` (client.py) mantiene stato fra le
richieste, e quello stato serve a poco se ogni chiamata parte da un
client nuovo. `_lucchetto` serializza le richieste allo stesso client fra
chiamate concorrenti — questo server non ha bisogno di parallelismo verso
un'unica API pubblica.

ERRORI SANIFICATI, E PERCHÉ DEVONO ESSERE `ToolError`. Un errore di
dominio (`NormattivaErrore`, `RiferimentoSconosciuto`,
`FonteNonDisponibileErrore`, `UrnNonValido`) porta già un messaggio scritto
per essere letto da un modello o da un avvocato (CLAUDE.md, regola 1) —
ma l'SDK (`mcp.server.mcpserver.tools.base.Tool.run`) tratta come un
crash silenzioso QUALUNQUE eccezione che non sia una sua `ToolError`:
il modello legge solo "Error executing tool <nome>", perdendo il
messaggio. Ogni strumento passa quindi da `_traduci_errori`, che converte
un errore di dominio in `ToolError(str(exc))` (messaggio conservato) e
qualunque altra eccezione in un `ToolError` col solo `type(exc).__name__`
più un testo nostro, mai `str(exc)` — potrebbe citare un frammento della
risposta di Normattiva. **Scoperto provando il server a mano da Claude
Desktop il 29/08/2026** (durante l'avaria in corso: il modello vedeva un
errore muto invece del messaggio "Normattiva è stata sospesa..."), mai
dai test che chiamavano le funzioni direttamente saltando l'SDK — da qui
`tests/test_mcp_server.py` verifica anche il tipo `ToolError`, non solo
il messaggio.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import __version__
from .citazione import link_markdown, testo_visibile_di_default
from .client import ClienteNormattiva
from .config import Config
from .descrizioni import DESCRIZIONI, ISTRUZIONI_SERVER
from .errori import NormattivaErrore
from .esiti import Abrogato, Articolo, Esito, Preambolo
from .fonti import Fonte, FonteNonDisponibile, carica_tabella
from .lookup import FonteNonDisponibileErrore, RiferimentoSconosciuto
from .lookup import risolvi_riferimento as _risolvi_riferimento
from .urn import UrnNonValido
from .urn import analizza as analizza_urn

_ERRORI_DI_DOMINIO_NOTI = (
    NormattivaErrore,
    RiferimentoSconosciuto,
    FonteNonDisponibileErrore,
    UrnNonValido,
)
"""Le eccezioni che portano già un messaggio scritto per un modello o un
avvocato (CLAUDE.md regola 1): viaggiano verso il chiamante MCP tali e
quali, mai sanificate."""


def _traduci_errori(fn):
    """Converte ogni eccezione sollevata da uno strumento in `ToolError`
    (vedi "ERRORI SANIFICATI" nel docstring del modulo). Applicato a
    ognuno dei quattro strumenti, non solo dentro `_rete`: `_risolvi_riferimento`
    e `analizza_urn` sollevano i loro errori PRIMA di entrare in `_rete`,
    quindi la traduzione deve avvolgere l'intero corpo dello strumento."""

    @functools.wraps(fn)
    async def involucro(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except _ERRORI_DI_DOMINIO_NOTI as exc:
            raise ToolError(str(exc)) from exc
        except Exception as exc:
            raise ToolError(
                f"{type(exc).__name__}: si è fermato un errore imprevisto, non "
                "riconosciuto come uno dei casi noti di questo programma. Il "
                "messaggio originale non viene mostrato perché potrebbe contenere "
                "un frammento della risposta di Normattiva. Se si ripete, va "
                "segnalato al titolare del programma."
            ) from exc

    return involucro


def _d(nome: str) -> tuple[str, str]:
    voce = DESCRIZIONI[nome]
    return voce.titolo, voce.descrizione


@dataclass(slots=True)
class ApplicazioneMcp:
    client: ClienteNormattiva
    lucchetto: asyncio.Lock = field(default_factory=asyncio.Lock)


@asynccontextmanager
async def _lifespan(_: MCPServer[ApplicazioneMcp]) -> AsyncIterator[ApplicazioneMcp]:
    config = Config.da_ambiente()
    client = ClienteNormattiva(timeout_secondi=config.timeout_secondi)
    try:
        yield ApplicazioneMcp(client=client)
    finally:
        client.chiudi()


def _applicazione(ctx: Context) -> ApplicazioneMcp:
    app = ctx.request_context.lifespan_context
    if not isinstance(app, ApplicazioneMcp):  # pragma: no cover - errore di integrazione
        raise RuntimeError("Contesto MCP non inizializzato")
    return app


async def _rete[T](app: ApplicazioneMcp, azione: Callable[[], T]) -> T:
    """Una richiesta alla volta verso l'unico client di processo. La
    traduzione degli errori vive in `_traduci_errori`, non qui: avvolge
    l'intero strumento, non solo la parte che tocca la rete."""
    async with app.lucchetto:
        return azione()


RETE = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)
LOCALE = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


server = MCPServer[ApplicazioneMcp](
    name="normattiva-mcp",
    title="Normattiva MCP",
    description=(
        "Lettura, citazione e verifica di norme italiane da Normattiva.it, parlando "
        "direttamente con l'API pubblica del sito."
    ),
    instructions=ISTRUZIONI_SERVER,
    version=__version__,
    lifespan=_lifespan,
)

mcp = server


# ============================================================================
# Esito comune a normattiva_leggi_articolo e normattiva_leggi_urn.
# ============================================================================


class EsitoOutput(BaseModel):
    """Un solo schema per i tre esiti possibili (`esito` discrimina), così i
    due strumenti che leggono un articolo condividono un'unica forma di
    uscita — nessuna copia divergente fra loro."""

    esito: str
    urn: str
    permalink: str
    heading: str | None = None
    testo: str | None = None
    aggiornamenti: list[str] = Field(default_factory=list)
    vigenza_storica: dict[str, str] | None = None
    messaggio: str | None = None
    data_abrogazione: str | None = None
    caratteri: int | None = None
    incipit: str | None = None
    attribuzione: str
    avvisi: list[str] = Field(default_factory=list)
    """Ogni avvertenza va qui come frase leggibile, mai solo in un campo
    fratello ignorabile (CLAUDE.md regola 2)."""


def _esito_a_output(esito: Esito, avvisi_extra: tuple[str, ...] = ()) -> EsitoOutput:
    avvisi = list(avvisi_extra)
    if isinstance(esito, Articolo):
        vigenza_storica = None
        if esito.vigenza_storica:
            vigenza_storica = {
                "data": esito.vigenza_storica.data.isoformat(),
                "avviso": esito.vigenza_storica.avviso,
            }
            avvisi.append(esito.vigenza_storica.avviso)
        return EsitoOutput(
            esito="articolo",
            urn=esito.urn.stringa,
            permalink=esito.permalink,
            heading=esito.heading,
            testo=esito.testo,
            aggiornamenti=list(esito.aggiornamenti),
            vigenza_storica=vigenza_storica,
            attribuzione=esito.attribuzione,
            avvisi=avvisi,
        )
    if isinstance(esito, Abrogato):
        avvisi.append(f"Articolo abrogato: {esito.messaggio}")
        return EsitoOutput(
            esito="abrogato",
            urn=esito.urn.stringa,
            permalink=esito.permalink,
            messaggio=esito.messaggio,
            data_abrogazione=esito.data_abrogazione.isoformat() if esito.data_abrogazione else None,
            attribuzione=esito.attribuzione,
            avvisi=avvisi,
        )
    avvisi.append(
        "Attenzione: Normattiva ha restituito il preambolo di promulgazione, "
        "non l'articolo richiesto."
    )
    return EsitoOutput(
        esito="preambolo",
        urn=esito.urn.stringa,
        permalink=esito.permalink,
        caratteri=esito.caratteri,
        incipit=esito.incipit,
        attribuzione=esito.attribuzione,
        avvisi=avvisi,
    )


# ============================================================================
# 1. normattiva_leggi_articolo — rete.
# ============================================================================

_TITOLO, _DESCR = _d("normattiva_leggi_articolo")


@server.tool(
    name="normattiva_leggi_articolo",
    title=_TITOLO,
    description=_DESCR,
    annotations=RETE,
    structured_output=True,
)
@_traduci_errori
async def normattiva_leggi_articolo(
    ctx: Context,
    fonte: str,
    articolo: str,
    vigenza: str | None = None,
) -> EsitoOutput:
    app = _applicazione(ctx)
    risoluzione = _risolvi_riferimento(fonte, articolo, vigenza)

    def azione() -> Esito:
        return app.client.leggi_articolo(risoluzione.urn)

    esito = await _rete(app, azione)
    return _esito_a_output(esito, avvisi_extra=risoluzione.avvertenze)


# ============================================================================
# 2. normattiva_link — rete (verifica di default).
# ============================================================================


class LinkOutput(BaseModel):
    markdown: str
    verificato: bool | None
    avviso: str | None = None


_TITOLO, _DESCR = _d("normattiva_link")


@server.tool(
    name="normattiva_link",
    title=_TITOLO,
    description=_DESCR,
    annotations=RETE,
    structured_output=True,
)
@_traduci_errori
async def normattiva_link(
    ctx: Context,
    fonte: str,
    articolo: str,
    vigenza: str | None = None,
    verifica: bool = True,
) -> LinkOutput:
    app = _applicazione(ctx)
    risoluzione = _risolvi_riferimento(fonte, articolo, vigenza)

    avvisi = list(risoluzione.avvertenze)
    verificato: bool | None = None
    if verifica:

        def azione() -> Esito:
            return app.client.leggi_articolo(risoluzione.urn)

        esito = await _rete(app, azione)
        verificato = isinstance(esito, Articolo)
        if isinstance(esito, Abrogato):
            avvisi.append(f"Attenzione: l'articolo risulta abrogato — {esito.messaggio}")
        elif isinstance(esito, Preambolo):
            avvisi.append(
                "Attenzione: Normattiva ha restituito il preambolo, non l'articolo — "
                "l'URN potrebbe non essere corretto."
            )

    nome = risoluzione.fonte.nome_canonico if risoluzione.fonte else fonte
    markdown = link_markdown(
        risoluzione.urn, testo_visibile=testo_visibile_di_default(nome, articolo)
    )
    return LinkOutput(
        markdown=markdown,
        verificato=verificato,
        avviso=" ".join(avvisi) if avvisi else None,
    )


# ============================================================================
# 3. normattiva_trova_fonte — locale, nessuna richiesta di rete.
# ============================================================================


class FonteOutput(BaseModel):
    trovata: bool
    disponibile: bool = True
    nome_canonico: str | None = None
    tipo: str | None = None
    numero: int | None = None
    data: str | None = None
    allegato: int | None = None
    stato: str | None = None
    nota_stato: str | None = None
    alias: list[str] = Field(default_factory=list)
    nota: str | None = None


_TITOLO, _DESCR = _d("normattiva_trova_fonte")


@server.tool(
    name="normattiva_trova_fonte",
    title=_TITOLO,
    description=_DESCR,
    annotations=LOCALE,
    structured_output=True,
)
@_traduci_errori
async def normattiva_trova_fonte(ctx: Context, testo: str) -> FonteOutput:
    _applicazione(ctx)  # valida il contesto, anche se questo strumento non tocca la rete
    tabella = carica_tabella()
    risultato = tabella.trova(testo)

    if risultato is None:
        return FonteOutput(trovata=False)
    if isinstance(risultato, Fonte):
        return FonteOutput(
            trovata=True,
            nome_canonico=risultato.nome_canonico,
            tipo=risultato.tipo.value,
            numero=risultato.numero,
            data=risultato.data.isoformat(),
            allegato=risultato.allegato,
            stato=risultato.stato,
            nota_stato=risultato.nota_stato,
            alias=list(risultato.alias),
        )
    assert isinstance(risultato, FonteNonDisponibile)
    return FonteOutput(
        trovata=True,
        disponibile=False,
        nome_canonico=risultato.nome_canonico,
        alias=list(risultato.alias),
        nota=risultato.nota,
    )


# ============================================================================
# 4. normattiva_leggi_urn — rete.
# ============================================================================

_TITOLO, _DESCR = _d("normattiva_leggi_urn")


@server.tool(
    name="normattiva_leggi_urn",
    title=_TITOLO,
    description=_DESCR,
    annotations=RETE,
    structured_output=True,
)
@_traduci_errori
async def normattiva_leggi_urn(ctx: Context, urn: str) -> EsitoOutput:
    app = _applicazione(ctx)
    u = analizza_urn(urn)

    def azione() -> Esito:
        return app.client.leggi_articolo(u)

    esito = await _rete(app, azione)
    return _esito_a_output(esito)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
