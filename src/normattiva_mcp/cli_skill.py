"""Sotto-comandi Typer per installare la skill sui client AI supportati."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from normattiva_mcp import __version__
from normattiva_mcp.skill import (
    ClientSkill,
    ErroreSkill,
    LivelloSkill,
    aggiorna,
    disinstalla,
    elenco_stati,
    installa,
    mostra,
)

skill_app = typer.Typer(
    name="skill",
    help="Installa e aggiorna la skill Agent Skills per Claude, Codex, OpenCode e Pi.",
    no_args_is_help=True,
)
_console = Console()
_errori = Console(stderr=True)


def _fallisci(errore: ErroreSkill) -> None:
    _errori.print(f"[red]{errore}[/red]")
    raise typer.Exit(code=1)


@skill_app.command("list")
def elenco(
    livello: Annotated[
        LivelloSkill | None,
        typer.Option("--level", help="Limita lo stato a user oppure project."),
    ] = None,
) -> None:
    """Mostra percorsi, versioni e stato delle installazioni locali."""
    table = Table(title=f"Skill normattiva-mcp — versione disponibile {__version__}")
    table.add_column("Client")
    table.add_column("Livello")
    table.add_column("Stato")
    table.add_column("Percorso")
    for stato in elenco_stati(livello):
        table.add_row(stato.client.value, stato.livello.value, stato.stato, str(stato.percorso))
    _console.print(table)


@skill_app.command("install")
def installa_comando(
    client: Annotated[ClientSkill, typer.Argument(help="Client oppure all.")],
    livello: Annotated[
        LivelloSkill,
        typer.Option("--level", help="Installa per l'utente o nel progetto corrente."),
    ] = LivelloSkill.UTENTE,
) -> None:
    """Installa la skill per uno o tutti i client supportati."""
    try:
        esiti = installa(client, livello)
    except ErroreSkill as errore:
        _fallisci(errore)
    for esito in esiti:
        if esito.azione == "non rilevato":
            _console.print(
                f"[yellow]{esito.client.value}[/yellow]: client non rilevato; installazione saltata"
            )
            continue
        _console.print(
            f"[green]{esito.client.value}[/green] ({esito.livello.value}): "
            f"skill {esito.azione} v{__version__} in {esito.percorso}"
        )


@skill_app.command("uninstall")
def disinstalla_comando(
    client: Annotated[ClientSkill, typer.Argument(help="Client oppure all.")],
    livello: Annotated[
        LivelloSkill,
        typer.Option("--level", help="Rimuove dal livello user o project."),
    ] = LivelloSkill.UTENTE,
) -> None:
    """Rimuove la skill soltanto dal livello indicato."""
    try:
        esiti = disinstalla(client, livello)
    except ErroreSkill as errore:
        _fallisci(errore)
    for esito in esiti:
        colore = "green" if esito.azione == "rimossa" else "yellow"
        _console.print(
            f"[{colore}]{esito.client.value}[/{colore}] ({esito.livello.value}): "
            f"{esito.azione} — {esito.percorso}"
        )


@skill_app.command("update")
def aggiorna_comando(
    client: Annotated[ClientSkill, typer.Argument(help="Client oppure all.")] = ClientSkill.TUTTI,
    livello: Annotated[
        LivelloSkill,
        typer.Option("--level", help="Aggiorna il livello user o project."),
    ] = LivelloSkill.UTENTE,
) -> None:
    """Aggiorna le installazioni presenti, senza crearne di nuove."""
    try:
        esiti = aggiorna(client, livello)
    except ErroreSkill as errore:
        _fallisci(errore)
    for esito in esiti:
        colore = "green" if esito.azione == "aggiornata" else "dim"
        _console.print(
            f"[{colore}]{esito.client.value}[/{colore}] ({esito.livello.value}): "
            f"{esito.azione} — {esito.percorso}"
        )


@skill_app.command("show")
def mostra_comando() -> None:
    """Stampa il contenuto della skill integrata nel pacchetto."""
    try:
        testo = mostra()
    except ErroreSkill as errore:
        _fallisci(errore)
    typer.echo(testo, nl=not testo.endswith("\n"))


__all__ = ["skill_app"]
