"""Client, livelli e destinazioni locali della skill distribuita.

Questo modulo contiene soltanto la mappa dei percorsi nativi e il rilevamento
locale dei client. Non crea directory e non accede alla rete.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from normattiva_mcp import __version__

NOME_SKILL = "normattiva-mcp"


class ClientSkill(StrEnum):
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    OPENCODE = "opencode"
    PI = "pi"
    TUTTI = "all"


class LivelloSkill(StrEnum):
    UTENTE = "user"
    PROGETTO = "project"


class ErroreSkill(RuntimeError):
    """Errore locale e mostrabile all'utente nella gestione della skill."""


@dataclass(frozen=True, slots=True)
class DestinazioneSkill:
    client: ClientSkill
    descrizione: str
    directory_utente: Path
    directory_progetto: Path
    binario: str
    radici_configurazione: tuple[Path, ...]

    def directory(self, livello: LivelloSkill) -> Path:
        if livello is LivelloSkill.PROGETTO:
            return self.directory_progetto
        return self.directory_utente


@dataclass(frozen=True, slots=True)
class StatoSkill:
    client: ClientSkill
    livello: LivelloSkill
    percorso: Path
    versione: str | None
    presente: bool
    collegamento_simbolico: bool

    @property
    def stato(self) -> str:
        if self.collegamento_simbolico:
            return "symlink non seguito"
        if not self.presente:
            return "non installata"
        if self.versione is None:
            return "versione sconosciuta"
        if self.versione == __version__:
            return "aggiornata"
        return f"da aggiornare (v{self.versione})"


@dataclass(frozen=True, slots=True)
class EsitoSkill:
    client: ClientSkill
    livello: LivelloSkill
    percorso: Path
    azione: str
    versione_precedente: str | None = None


def _home() -> Path:
    return Path.home()


def _cwd() -> Path:
    return Path.cwd()


def destinazioni(
    *, home: Path | None = None, directory_progetto: Path | None = None
) -> tuple[DestinazioneSkill, ...]:
    """Restituisce i percorsi nativi documentati dei client supportati."""
    home = home or _home()
    directory_progetto = directory_progetto or _cwd()
    return (
        DestinazioneSkill(
            ClientSkill.CLAUDE_CODE,
            "Claude Code CLI e Desktop",
            home / ".claude" / "skills",
            directory_progetto / ".claude" / "skills",
            "claude",
            (home / ".claude",),
        ),
        DestinazioneSkill(
            ClientSkill.CODEX,
            "OpenAI Codex",
            home / ".agents" / "skills",
            directory_progetto / ".agents" / "skills",
            "codex",
            (home / ".codex", home / ".agents"),
        ),
        DestinazioneSkill(
            ClientSkill.OPENCODE,
            "OpenCode",
            home / ".config" / "opencode" / "skills",
            directory_progetto / ".opencode" / "skills",
            "opencode",
            (home / ".config" / "opencode",),
        ),
        DestinazioneSkill(
            ClientSkill.PI,
            "Pi coding agent",
            home / ".pi" / "agent" / "skills",
            directory_progetto / ".pi" / "skills",
            "pi",
            (home / ".pi",),
        ),
    )


def seleziona_destinazioni(
    client: ClientSkill,
    *,
    home: Path | None = None,
    directory_progetto: Path | None = None,
) -> tuple[DestinazioneSkill, ...]:
    tutte = destinazioni(home=home, directory_progetto=directory_progetto)
    if client is ClientSkill.TUTTI:
        return tutte
    return tuple(destinazione for destinazione in tutte if destinazione.client is client)


def client_rilevato(destinazione: DestinazioneSkill) -> bool:
    """Un binario sul PATH o una directory di configurazione bastano."""
    return shutil.which(destinazione.binario) is not None or any(
        radice.is_dir() for radice in destinazione.radici_configurazione
    )


__all__ = [
    "ClientSkill",
    "DestinazioneSkill",
    "ErroreSkill",
    "EsitoSkill",
    "LivelloSkill",
    "NOME_SKILL",
    "StatoSkill",
    "client_rilevato",
    "destinazioni",
    "seleziona_destinazioni",
]
