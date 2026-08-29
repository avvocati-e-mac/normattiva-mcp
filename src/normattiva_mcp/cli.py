"""La porta da terminale: comandi Typer sottili, che chiamano gli stessi
moduli di dominio del server MCP (mcp_server.py). Non decidono nulla che
non sia già deciso in urn.py, lookup.py, client.py, parser.py: traducono
input/output.

`norm verifica` e `norm fonti aggiungi` sono SOLO qui, mai come strumento
MCP: fanno decine di richieste all'API e non devono poter essere lanciate
da un modello (CLAUDE.md, regola implicita "il modello non deve poter
scatenare da solo un giro completo sulla tabella").
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

from normattiva_mcp import __version__
from normattiva_mcp.citazione import link_markdown, riga_attribuzione, testo_visibile_di_default
from normattiva_mcp.client import BASE_URL, ClienteNormattiva
from normattiva_mcp.config import Config
from normattiva_mcp.errori import NormattivaErrore
from normattiva_mcp.esiti import Abrogato, Articolo, Preambolo
from normattiva_mcp.fonti import Fonte, carica_tabella
from normattiva_mcp.lookup import (
    FonteNonDisponibileErrore,
    RiferimentoSconosciuto,
)
from normattiva_mcp.lookup import risolvi_riferimento as _risolvi_riferimento_condiviso
from normattiva_mcp.urn import UrnNonValido
from normattiva_mcp.urn import analizza as analizza_urn

app = typer.Typer(
    name="norm",
    help="Leggi, verifica e cita norme italiane da Normattiva.it.",
    no_args_is_help=True,
)
_console = Console()
_console_errori = Console(stderr=True)


def _remoto(testo: str) -> str:
    """Il testo remoto (che viene da Normattiva) va sempre stampato senza
    interpretarlo come markup Rich — coerente con la busta trust in
    esiti.py: è un dato, non un'istruzione, nemmeno per il terminale."""
    from rich.markup import escape

    return escape(testo)


def _nuovo_client() -> ClienteNormattiva:
    """Un unico punto di costruzione del client, per tutti i comandi.

    In un test, `normattiva_mcp.cli._nuovo_client` si sostituisce
    interamente (monkeypatch) per restituire un client con trasporto
    finto e backoff senza attesa — più semplice e più robusto che
    patchare `httpx.Client` a livello di modulo dentro client.py.
    """
    config = Config.da_ambiente()
    return ClienteNormattiva(timeout_secondi=config.timeout_secondi)


def _stampa_errore(errore: Exception) -> None:
    """Stampa un errore su stderr, con l'escape del suo testo.

    Un messaggio d'errore può contenere testo che viene da Normattiva
    (es. il dump di CoordinateSbagliate, o un URN citato in un errore):
    senza l'escape, un carattere "[" nel messaggio verrebbe interpretato
    da Rich come l'inizio di un tag di stile e scomparirebbe insieme al
    resto — bug reale trovato provando `norm link` a mano, che stampava
    solo "(...)" invece del link completo tra parentesi quadre.
    """
    _console_errori.print(f"[red]{_remoto(str(errore))}[/red]")


@app.callback(invoke_without_command=True)
def _radice(
    ctx: typer.Context,
    versione: bool = typer.Option(False, "--version", help="Mostra la versione e esce."),
) -> None:
    if versione:
        typer.echo(__version__)
        raise typer.Exit
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def _stampa_esito(esito: Articolo | Abrogato | Preambolo, *, come_json: bool) -> None:
    if come_json:
        import json as _json

        if isinstance(esito, Articolo):
            corpo = {
                "esito": "articolo",
                "urn": esito.urn.stringa,
                "permalink": esito.permalink,
                "heading": esito.heading,
                "testo": esito.testo,
                "aggiornamenti": list(esito.aggiornamenti),
                "vigenza_storica": (
                    {
                        "data": esito.vigenza_storica.data.isoformat(),
                        "avviso": esito.vigenza_storica.avviso,
                    }
                    if esito.vigenza_storica
                    else None
                ),
                "attribuzione": esito.attribuzione,
            }
        elif isinstance(esito, Abrogato):
            corpo = {
                "esito": "abrogato",
                "urn": esito.urn.stringa,
                "permalink": esito.permalink,
                "messaggio": esito.messaggio,
                "data_abrogazione": (
                    esito.data_abrogazione.isoformat() if esito.data_abrogazione else None
                ),
                "attribuzione": esito.attribuzione,
            }
        else:
            corpo = {
                "esito": "preambolo",
                "urn": esito.urn.stringa,
                "permalink": esito.permalink,
                "caratteri": esito.caratteri,
                "incipit": esito.incipit,
                "attribuzione": esito.attribuzione,
            }
        typer.echo(_json.dumps(corpo, ensure_ascii=False, indent=2))
        return

    if isinstance(esito, Articolo):
        if esito.vigenza_storica:
            _console.print(f"[yellow]{_remoto(esito.vigenza_storica.avviso)}[/yellow]\n")
        _console.print(f"[bold]{_remoto(esito.heading)}[/bold]\n")
        _console.print(_remoto(esito.testo))
        if esito.aggiornamenti:
            _console.print(
                f"\n[dim]({len(esito.aggiornamenti)} nota/e di aggiornamento omesse)[/dim]"
            )
        _console.print(f"\n[blue]{esito.permalink}[/blue]")
        _console.print(f"[dim]{riga_attribuzione()}[/dim]")
    elif isinstance(esito, Abrogato):
        _console.print(f"[red]Articolo abrogato:[/red] {_remoto(esito.messaggio)}")
        if esito.data_abrogazione:
            _console.print(
                f"[dim]Prova con --vigenza {esito.data_abrogazione.isoformat()} "
                "per il testo storico.[/dim]"
            )
        _console.print(f"\n[blue]{esito.permalink}[/blue]")
    else:
        _console.print(
            f"[red]Attenzione:[/red] Normattiva ha restituito il preambolo di "
            f"promulgazione ({esito.caratteri} caratteri), non l'articolo richiesto."
        )
        _console.print(f"[dim]Incipit: {_remoto(esito.incipit)}[/dim]")
        _console.print(f"\n[blue]{esito.permalink}[/blue]")


def _risolvi_riferimento(fonte: str, numero_articolo: str, vigenza: str | None):
    """Risolve fonte+articolo passando dalla tabella (`lookup.risolvi_riferimento`,
    condivisa con `mcp_server.py` — CLAUDE.md regola 6); solleva gli errori del
    dominio, che i comandi convertono in messaggi.
    """
    return _risolvi_riferimento_condiviso(fonte, numero_articolo, vigenza)


@app.command()
def leggi(
    fonte: str = typer.Argument(
        ..., help='Nome o alias della fonte, es. "codice civile", "l.fall."'
    ),
    articolo: str = typer.Argument(..., help='Numero dell\'articolo, es. "2043", "21novies"'),
    vigenza: str | None = typer.Option(
        None, "--vigenza", help="Data YYYY-MM-DD per il testo storico."
    ),
    come_json: bool = typer.Option(False, "--json", help="Uscita in JSON invece che leggibile."),
) -> None:
    """Legge il testo di un articolo, verificato."""
    try:
        risoluzione = _risolvi_riferimento(fonte, articolo, vigenza)
    except FonteNonDisponibileErrore as errore:
        _stampa_errore(errore)
        raise typer.Exit(code=1) from None
    except RiferimentoSconosciuto as errore:
        _stampa_errore(errore)
        raise typer.Exit(code=1) from None
    except UrnNonValido as errore:
        _stampa_errore(errore)
        raise typer.Exit(code=1) from None

    for avviso in risoluzione.avvertenze:
        _console.print(f"[yellow]Avviso: {avviso}[/yellow]")

    with _nuovo_client() as client:
        try:
            esito = client.leggi_articolo(risoluzione.urn)
        except NormattivaErrore as errore:
            _stampa_errore(errore)
            raise typer.Exit(code=1) from None

    _stampa_esito(esito, come_json=come_json)


@app.command()
def link(
    fonte: str = typer.Argument(...),
    articolo: str = typer.Argument(...),
    vigenza: str | None = typer.Option(None, "--vigenza"),
    non_verificare: bool = typer.Option(
        False,
        "--non-verificare",
        help="Non controllare l'esistenza dell'atto (più veloce, meno sicuro).",
    ),
) -> None:
    """Costruisce e — di default — verifica la citazione Markdown di un
    articolo, senza restituirne il testo completo."""
    try:
        risoluzione = _risolvi_riferimento(fonte, articolo, vigenza)
    except (FonteNonDisponibileErrore, RiferimentoSconosciuto, UrnNonValido) as errore:
        _stampa_errore(errore)
        raise typer.Exit(code=1) from None

    verificato: bool | None = None
    if not non_verificare:
        with _nuovo_client() as client:
            try:
                esito = client.leggi_articolo(risoluzione.urn)
                verificato = isinstance(esito, Articolo)
                if isinstance(esito, Abrogato):
                    messaggio = _remoto(esito.messaggio)
                    _console.print(
                        f"[yellow]Attenzione: l'articolo risulta abrogato — {messaggio}[/yellow]"
                    )
                elif isinstance(esito, Preambolo):
                    _console.print(
                        "[yellow]Attenzione: Normattiva ha restituito il preambolo, "
                        "non l'articolo — l'URN potrebbe non essere corretto.[/yellow]"
                    )
            except NormattivaErrore as errore:
                _console_errori.print(f"[red]Verifica fallita: {_remoto(str(errore))}[/red]")
                verificato = False

    nome = risoluzione.fonte.nome_canonico if risoluzione.fonte else fonte
    testo_visibile = testo_visibile_di_default(nome, articolo)
    markdown = link_markdown(risoluzione.urn, testo_visibile=testo_visibile)
    # markup=False: la citazione Markdown contiene parentesi quadre che
    # Rich altrimenti interpreterebbe come un tag di stile sconosciuto e
    # scarterebbe silenziosamente — bug reale trovato provando il comando
    # a mano ("[art. 42 Legge Fallimentare](...)" veniva stampato come
    # "(...)", senza il testo del link).
    _console.print(markdown, markup=False)
    if verificato is False:
        _console_errori.print("[red]Attenzione: il link non è stato verificato con successo.[/red]")
        raise typer.Exit(code=1)


@app.command()
def urn(
    urn_completo: str = typer.Argument(..., help="Un URN Normattiva completo."),
    come_json: bool = typer.Option(False, "--json"),
) -> None:
    """Legge un URN già in mano (es. un rinvio trovato in un testo)."""
    try:
        u = analizza_urn(urn_completo)
    except UrnNonValido as errore:
        _stampa_errore(errore)
        raise typer.Exit(code=1) from None

    with _nuovo_client() as client:
        try:
            esito = client.leggi_articolo(u)
        except NormattivaErrore as errore:
            _stampa_errore(errore)
            raise typer.Exit(code=1) from None
    _stampa_esito(esito, come_json=come_json)


@app.command()
def fonti(
    testo: str | None = typer.Argument(None, help="Cerca una fonte per nome o alias."),
) -> None:
    """Elenca le fonti verificate, o cerca una fonte per nome."""
    tabella = carica_tabella()
    if testo:
        risultato = tabella.trova(testo)
        if risultato is None:
            _console.print(f'[yellow]Nessuna fonte nota per "{testo}".[/yellow]')
            raise typer.Exit(code=1)
        if isinstance(risultato, Fonte):
            _console.print(f"[bold]{risultato.nome_canonico}[/bold]")
            _console.print(
                f"  tipo: {risultato.tipo.value}, numero: {risultato.numero}, "
                f"data: {risultato.data.isoformat()}"
                + (f", allegato: {risultato.allegato}" if risultato.allegato else "")
            )
            _console.print(
                f"  stato: {risultato.stato}"
                + (f" ({risultato.nota_stato})" if risultato.nota_stato else "")
            )
            _console.print(f"  alias: {', '.join(risultato.alias)}")
        else:
            _console.print(
                f"[yellow]{risultato.nome_canonico} non è disponibile su Normattiva.[/yellow]"
            )
            _console.print(f"  {risultato.nota}")
        return

    table = Table(title="Fonti verificate")
    table.add_column("Nome canonico")
    table.add_column("Tipo")
    table.add_column("Stato")
    for f in tabella.verificate:
        table.add_row(f.nome_canonico, f.tipo.value, f.stato)
    _console.print(table)


@app.command()
def doctor() -> None:
    """Controlla se il servizio risponde — sonda specificamente l'endpoint
    del testo (dettaglio-atto-urn), non un endpoint qualsiasi: l'avaria
    del 29/08/2026 ha colpito solo quello mentre il resto rispondeva
    (docs/MISURE.md §7)."""
    _console.print(f"normattiva-mcp {__version__}")
    _console.print(f"Base API: {BASE_URL}")

    with _nuovo_client() as client:
        u = analizza_urn("urn:nir:stato:costituzione:1947-12-27;1~art1")
        try:
            esito = client.leggi_articolo(u)
        except NormattivaErrore as errore:
            messaggio = _remoto(str(errore))
            _console.print(
                f"[red]L'endpoint del testo non risponde correttamente: {messaggio}[/red]"
            )
            raise typer.Exit(code=1) from None

    if isinstance(esito, Articolo):
        _console.print(
            "[green]L'endpoint del testo (dettaglio-atto-urn) risponde correttamente.[/green]"
        )
    else:
        _console.print(
            "[yellow]L'endpoint risponde ma con un esito inatteso per l'art. 1 "
            f"della Costituzione: {type(esito).__name__}.[/yellow]"
        )
        raise typer.Exit(code=1)


@app.command()
def verifica(
    tutte: bool = typer.Option(False, "--tutte", help="Verifica tutte le fonti della tabella."),
) -> None:
    """Interroga l'API per ogni fonte, distinguendo un'avaria del
    servizio da una riga davvero sbagliata (CLAUDE.md, la disciplina che
    ha già scoperto due errori storici nella tabella).

    Prima di giudicare qualunque fonte, prova una sonda di salute: se
    fallisce, si ferma subito senza emettere nessun verdetto — un'avaria
    non deve mai tradursi in righe marcate come sbagliate.
    """
    if not tutte:
        _console.print("Usa --tutte per verificare l'intera tabella (fa decine di richieste).")
        raise typer.Exit(code=1)

    tabella = carica_tabella()

    with _nuovo_client() as client:
        sonda = analizza_urn("urn:nir:stato:costituzione:1947-12-27;1~art1")
        try:
            esito_sonda = client.leggi_articolo(sonda)
        except NormattivaErrore as errore:
            _console_errori.print(
                f"[red]Il servizio è in avaria adesso ({_remoto(str(errore))}): "
                "nessuna riga è stata giudicata, riprova più tardi.[/red]"
            )
            raise typer.Exit(code=1) from None
        if not isinstance(esito_sonda, Articolo):
            _console_errori.print(
                "[red]Il servizio risponde in modo inatteso alla sonda di salute: "
                "nessuna riga è stata giudicata, riprova più tardi.[/red]"
            )
            raise typer.Exit(code=1)

        table = Table(title="Verifica delle fonti")
        table.add_column("Fonte")
        table.add_column("Esito")
        righe_rosse = 0
        righe_non_verificate = 0
        for f in tabella.verificate:
            try:
                esito = client.leggi_articolo(f.urn_di_controllo())
            except NormattivaErrore as errore:
                # Un errore durante il giro (non alla sonda iniziale) è
                # trattato come "non verificata", mai come "sbagliata":
                # potrebbe essere un'avaria isolata su quella singola
                # richiesta, non un giudizio sulla riga.
                table.add_row(
                    f.nome_canonico, f"[yellow]non verificata ({_remoto(str(errore))})[/yellow]"
                )
                righe_non_verificate += 1
                continue
            if isinstance(esito, Articolo):
                table.add_row(f.nome_canonico, "[green]verde[/green]")
            else:
                table.add_row(f.nome_canonico, f"[red]da controllare: {type(esito).__name__}[/red]")
                righe_rosse += 1

        _console.print(table)
        if righe_rosse or righe_non_verificate:
            _console_errori.print(
                f"[yellow]{righe_rosse} riga/e da controllare, "
                f"{righe_non_verificate} non verificate.[/yellow]"
            )
            raise typer.Exit(code=1)


@app.command(name="fonti-aggiungi")
def fonti_aggiungi_comando() -> None:
    """La tabella non si amplia a tavolino: cresce con l'uso.

    Non ancora implementato in questo branch — richiede la ricerca
    (ricerca.py, branch successivo) per trovare l'atto dal nome. Il
    comando esiste già come promemoria dell'interfaccia prevista dal
    piano; l'implementazione arriva con la ricerca."""
    _console.print(
        "[yellow]norm fonti-aggiungi non è ancora implementato: richiede la ricerca "
        "full-text (branch successivo). Nel frattempo, aggiungi una riga a mano in "
        "src/normattiva_mcp/data/fonti.json con provenienza e articolo_di_controllo, "
        "poi verifica con `norm verifica --tutte`.[/yellow]"
    )
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
