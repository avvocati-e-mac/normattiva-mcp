"""Strumenti MCP stdio, tutti dietro il coordinatore SQLite condiviso.

Le eccezioni di dominio diventano `ToolError`; le eccezioni inattese sono
sanificate e non espongono testo ricevuto da Normattiva.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

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
from .mcp_output import (
    EsitoOutput,
    FonteOutput,
    LinkOutput,
    ProtezioneReteOutput,
    StatoReteOutput,
)
from .mcp_output import (
    avvisi_rapporti as _avvisi_rapporti_per_client,
)
from .mcp_output import (
    esito_a_output as _esito_a_output,
)
from .mcp_output import (
    protezione_rete as _protezione_rete_per_client,
)
from .protezione import RapportoRete
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

_RAPPORTI_ERRORE: ContextVar[tuple[RapportoRete, ...]] = ContextVar("rapporti_errore", default=())
"""Rapporti del tentativo dell'attuale tool, mai quelli di una chiamata
precedente concorrente. Serve anche quando MCP può restituire solo ToolError."""


def _suffisso_protezione_errore() -> str:
    """Espone quota e blocchi generati localmente, senza testo remoto."""
    rapporti = _RAPPORTI_ERRORE.get()
    if not rapporti:
        return ""
    ultimo = rapporti[-1]
    avvisi = [rapporto.avviso for rapporto in rapporti]
    stato = f"livello {ultimo.livello}"
    if ultimo.cooldown_fino:
        stato += f", cooldown fino a {ultimo.cooldown_fino}"
    avvisi.append(f"Protezione rete: {stato}.")
    return "\n" + "\n".join(avvisi)


def _traduci_errori(fn):
    """Converte ogni eccezione sollevata da uno strumento in `ToolError`
    (vedi "ERRORI SANIFICATI" nel docstring del modulo). Applicato a
    ognuno degli strumenti, non solo dentro `_rete`: `_risolvi_riferimento`
    e `analizza_urn` sollevano i loro errori PRIMA di entrare in `_rete`,
    quindi la traduzione deve avvolgere l'intero corpo dello strumento."""

    @functools.wraps(fn)
    async def involucro(*args, **kwargs):
        token = _RAPPORTI_ERRORE.set(())
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except _ERRORI_DI_DOMINIO_NOTI as exc:
            raise ToolError(str(exc) + _suffisso_protezione_errore()) from exc
        except Exception as exc:
            raise ToolError(
                f"{type(exc).__name__}: si è fermato un errore imprevisto, non "
                "riconosciuto come uno dei casi noti di questo programma. Il "
                "messaggio originale non viene mostrato perché potrebbe contenere "
                "un frammento della risposta di Normattiva. Se si ripete, va "
                "segnalato al titolare del programma." + _suffisso_protezione_errore()
            ) from exc
        finally:
            _RAPPORTI_ERRORE.reset(token)

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
    client = ClienteNormattiva(config=config, timeout_secondi=config.timeout_secondi)
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
        try:
            return azione()
        finally:
            _RAPPORTI_ERRORE.set(
                tuple(
                    rapporto
                    for rapporto in app.client.ultimi_rapporti
                    if rapporto.origine == "rete"
                )
            )


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


def _protezione_rete(app: ApplicazioneMcp, *, stato_locale: bool = False) -> ProtezioneReteOutput:
    """Compatibilità locale: la conversione vive in `mcp_output`."""
    return _protezione_rete_per_client(app.client, stato_locale=stato_locale)


def _avvisi_rapporti(app: ApplicazioneMcp) -> list[str]:
    """Compatibilità locale: la conversione vive in `mcp_output`."""
    return _avvisi_rapporti_per_client(app.client)


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
    avvisi = (*risoluzione.avvertenze, *_avvisi_rapporti(app))
    return _esito_a_output(esito, _protezione_rete(app), avvisi_extra=avvisi)


# ============================================================================
# 2. normattiva_link — rete (verifica di default).
# ============================================================================


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

        avvisi.extend(_avvisi_rapporti(app))

    nome = risoluzione.fonte.nome_canonico if risoluzione.fonte else fonte
    markdown = link_markdown(
        risoluzione.urn, testo_visibile=testo_visibile_di_default(nome, articolo)
    )
    return LinkOutput(
        markdown=markdown,
        verificato=verificato,
        avviso=" ".join(avvisi) if avvisi else None,
        avvisi=avvisi,
        protezione_rete=_protezione_rete(app, stato_locale=not verifica),
    )


# ============================================================================
# 3. normattiva_trova_fonte — locale, nessuna richiesta di rete.
# ============================================================================


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
            disponibile=True,
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
    return _esito_a_output(esito, _protezione_rete(app), avvisi_extra=tuple(_avvisi_rapporti(app)))


# ============================================================================
# 5. normattiva_stato_rete — locale, quota e telemetria aggregata.
# ============================================================================


_TITOLO, _DESCR = _d("normattiva_stato_rete")


@server.tool(
    name="normattiva_stato_rete",
    title=_TITOLO,
    description=_DESCR,
    annotations=LOCALE,
    structured_output=True,
)
@_traduci_errori
async def normattiva_stato_rete(ctx: Context) -> StatoReteOutput:
    """Legge soltanto il database locale; non contatta Normattiva."""
    app = _applicazione(ctx)
    assert app.client.protezione is not None
    rapporto = app.client.protezione.stato()
    return StatoReteOutput(
        rapporto=ProtezioneReteOutput(**rapporto.modello()),
        aggregati_giornalieri=app.client.protezione.aggregati_giornalieri(),
    )


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
