"""Configurazione condivisa, con limiti abbassabili ma mai alzabili."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import __version__

_DEFAULT_TIMEOUT_SECONDI = 15.0
_LIMITE_CONSULTAZIONI = 30
_LIMITE_DIAGNOSI = 2
_LIMITE_ASSOLUTO = 60


def _intero_ridotto(nome: str, massimo: int) -> int:
    try:
        valore = int(os.environ.get(nome, str(massimo)))
    except ValueError:
        return massimo
    return min(massimo, max(1, valore))


def _percorso_stato() -> Path:
    configurato = os.environ.get("NORMATTIVA_STATO_DB")
    if configurato:
        return Path(configurato).expanduser()
    if os.name == "posix" and os.uname().sysname == "Darwin":
        return Path.home() / "Library/Application Support/normattiva-mcp/protezione.sqlite3"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base / "normattiva-mcp/protezione.sqlite3"


@dataclass(frozen=True, slots=True)
class Config:
    timeout_secondi: float = _DEFAULT_TIMEOUT_SECONDI
    database: Path = Path("protezione.sqlite3")
    offline: bool = False
    limite_consultazioni: int = _LIMITE_CONSULTAZIONI
    limite_diagnosi: int = _LIMITE_DIAGNOSI
    limite_assoluto: int = _LIMITE_ASSOLUTO
    contatto_user_agent: str | None = None

    @classmethod
    def da_ambiente(cls) -> Config:
        grezzo = os.environ.get("NORMATTIVA_TIMEOUT_SECONDI")
        try:
            timeout = float(grezzo) if grezzo is not None else _DEFAULT_TIMEOUT_SECONDI
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT_SECONDI
        return cls(
            timeout_secondi=timeout,
            database=_percorso_stato(),
            offline=os.environ.get("NORMATTIVA_OFFLINE") == "1",
            limite_consultazioni=_intero_ridotto(
                "NORMATTIVA_LIMITE_CONSULTAZIONI", _LIMITE_CONSULTAZIONI
            ),
            limite_diagnosi=_intero_ridotto("NORMATTIVA_LIMITE_DIAGNOSI", _LIMITE_DIAGNOSI),
            limite_assoluto=_intero_ridotto("NORMATTIVA_LIMITE_ASSOLUTO", _LIMITE_ASSOLUTO),
            contatto_user_agent=os.environ.get("NORMATTIVA_CONTATTO_USER_AGENT") or None,
        )

    @property
    def user_agent(self) -> str:
        base = f"normattiva-mcp/{__version__} (client API Open Data; uso prudente)"
        return f"{base}; contatto={self.contatto_user_agent}" if self.contatto_user_agent else base
