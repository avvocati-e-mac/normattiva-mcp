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
from normattiva_mcp.cli_skill import skill_app
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
from normattiva_mcp.protezione import ProtezioneTraffico
from normattiva_mcp.urn import UrnNonValido
from normattiva_mcp.urn import analizza as analizza_urn

app = typer.Typer(
    name="norm",
    help="Leggi, verifica e cita norme italiane da Normattiva.it.",
    no_args_is_help=True,
)
app.add_typer(skill_app, name="skill")
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
    interamente (monkeypatch) per restituire un client con trasporto finto
    e database di protezione temporaneo — più semplice e più robusto che
    patchare `httpx.Client` a livello di modulo dentro client.py.
    """
    config = Config.da_ambiente()

    def avvisa(rapporto) -> None:
        # Il client invoca il callback solo dopo un tentativo HTTP reale;
        # cache e blocchi locali non devono fingere di aver consumato quota.
        _console_errori.print(_remoto(rapporto.avviso))

    return ClienteNormattiva(
        timeout_secondi=config.timeout_secondi,
        config=config,
        notifica_rete=avvisa,
    )


def _client_o_esci() -> ClienteNormattiva:
    """Costruisce il client, trasformando il fail-closed in errore CLI.

    `ProtezioneTraffico` si inizializza nel costruttore del client: se il
    suo database non è disponibile, nessun comando di rete deve esporre un
    traceback o provare a continuare senza coordinamento.
    """
    try:
        return _nuovo_client()
    except NormattivaErrore as errore:
        _stampa_errore(errore)
        raise typer.Exit(code=1) from None


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
    aggiorna: bool = typer.Option(
        False,
        "--aggiorna",
        help="Ignora la cache locale e chiede un aggiornamento, nel rispetto delle protezioni.",
    ),
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

    with _client_o_esci() as client:
        try:
            esito = client.leggi_articolo(risoluzione.urn, aggiorna=aggiorna)
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
    aggiorna: bool = typer.Option(
        False,
        "--aggiorna",
        help="Durante la verifica, ignora la cache locale nel rispetto delle protezioni.",
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
        with _client_o_esci() as client:
            try:
                esito = client.leggi_articolo(risoluzione.urn, aggiorna=aggiorna)
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
    aggiorna: bool = typer.Option(
        False,
        "--aggiorna",
        help="Ignora la cache locale e chiede un aggiornamento, nel rispetto delle protezioni.",
    ),
) -> None:
    """Legge un URN già in mano (es. un rinvio trovato in un testo)."""
    try:
        u = analizza_urn(urn_completo)
    except UrnNonValido as errore:
        _stampa_errore(errore)
        raise typer.Exit(code=1) from None

    with _client_o_esci() as client:
        try:
            esito = client.leggi_articolo(u, aggiorna=aggiorna)
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
    """Esegue una sola diagnosi dell'endpoint del testo.

    Il coordinatore può fermarla prima della rete per cooldown, quota o
    modalità offline: in questi casi non tenta scorciatoie né altri endpoint.
    """
    _console.print(f"normattiva-mcp {__version__}")
    _console.print(f"Base API: {BASE_URL}")

    with _client_o_esci() as client:
        u = analizza_urn("urn:nir:stato:costituzione:1947-12-27;1~art1")
        try:
            esito = client.leggi_articolo(
                u,
                attivita="diagnosi",
                aggiorna=True,
                recupera_storico=False,
            )
        except NormattivaErrore as errore:
            messaggio = _remoto(str(errore))
            _console.print(
                f"[red]La diagnosi dell'endpoint del testo non è riuscita: {messaggio}[/red]"
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
def stato() -> None:
    """Mostra localmente quota, cooldown, incidente e telemetria aggregata.

    Non costruisce un client HTTP e non effettua alcuna richiesta a Normattiva.
    """
    try:
        protezione = ProtezioneTraffico(Config.da_ambiente())
        rapporto = protezione.stato()
        diagnosi = protezione.stato(attivita="diagnosi")
        aggregati = protezione.aggregati_giornalieri()
    except NormattivaErrore as errore:
        _stampa_errore(errore)
        raise typer.Exit(code=1) from None

    _console.print("[bold]Stato locale della protezione di rete[/bold]")
    _console.print(f"Consultazioni: {rapporto.consumo_attivita}")
    _console.print(f"Diagnosi: {diagnosi.consumo_attivita}")
    _console.print(f"Totale: {rapporto.consumo_globale}")
    _console.print(f"Richieste residue: {rapporto.richieste_residue}")
    _console.print(f"Livello: {rapporto.livello}")
    _console.print(f"Cooldown: {rapporto.cooldown_fino or 'nessuno'}")
    _console.print(f"Ultimo incidente: {rapporto.ultimo_incidente or 'nessuno'}")
    _console.print(
        "Oggi (UTC): "
        f"{aggregati['richieste_reali']} richieste reali, "
        f"{aggregati['cache_hit']} cache hit, "
        f"{aggregati['errori']} errori, "
        f"picco {aggregati['massimo_in_un_ora']}/ora"
    )


@app.command()
def verifica(
    tutte: bool = typer.Option(False, "--tutte", help="Verifica tutte le fonti della tabella."),
    esegui: bool = typer.Option(
        False,
        "--esegui",
        help="Esegue la verifica completa dopo aver prenotato l'intero budget stimato.",
    ),
) -> None:
    """Verifica tutte le fonti esclusivamente su esplicita conferma CLI.

    Il costo dichiarato è una richiesta per fonte e non include sonde: non
    esiste qui una sonda nascosta che possa eccedere il budget prenotato.
    """
    if not tutte:
        _console.print("Usa --tutte per verificare l'intera tabella (fa decine di richieste).")
        raise typer.Exit(code=1)

    tabella = carica_tabella()
    costo = len(tabella.verificate)
    if not esegui:
        _console.print(
            f"Costo stimato: fino a {costo} richieste reali (una per fonte, nessuna sonda). "
            "Per iniziare usa `norm verifica --tutte --esegui`."
        )
        return

    with _client_o_esci() as client:
        try:
            assert client.protezione is not None
            prenotazione = client.protezione.prenota_verifica(costo)
        except NormattivaErrore as errore:
            _stampa_errore(errore)
            raise typer.Exit(code=1) from None

        table = Table(title="Verifica delle fonti")
        table.add_column("Fonte")
        table.add_column("Esito")
        righe_rosse = 0
        righe_non_verificate = 0
        completa = True
        try:
            for f in tabella.verificate:
                try:
                    esito = client.leggi_articolo(
                        f.urn_di_controllo(),
                        attivita="verifica",
                        aggiorna=True,
                        prenotazione=prenotazione,
                        recupera_storico=False,
                    )
                except NormattivaErrore as errore:
                    # Un errore è sempre "non verificata", mai una prova che
                    # la fonte sia errata. Se il coordinatore blocca il giro,
                    # fermarsi è l'unico comportamento prudente.
                    table.add_row(
                        f.nome_canonico,
                        f"[yellow]non verificata ({_remoto(str(errore))})[/yellow]",
                    )
                    righe_non_verificate += 1
                    if client.ultimo_rapporto.livello == "bloccato":
                        completa = False
                        break
                    continue
                if isinstance(esito, Articolo):
                    table.add_row(f.nome_canonico, "[green]verde[/green]")
                else:
                    table.add_row(
                        f.nome_canonico,
                        f"[red]da controllare: {type(esito).__name__}[/red]",
                    )
                    righe_rosse += 1
        finally:
            client.protezione.chiudi_prenotazione(prenotazione, completa=completa)

    _console.print(table)
    if righe_rosse or righe_non_verificate or not completa:
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
