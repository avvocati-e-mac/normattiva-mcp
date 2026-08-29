"""Configurazione condivisa da CLI e server MCP, letta dall'ambiente.

Nessuna chiave richiesta: l'API di Normattiva è pubblica (docs/MISURE.md
§1). L'unica cosa configurabile è il timeout delle richieste, per chi ha
una rete lenta o vuole test più severi.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_TIMEOUT_SECONDI = 15.0


@dataclass(frozen=True, slots=True)
class Config:
    timeout_secondi: float = _DEFAULT_TIMEOUT_SECONDI

    @classmethod
    def da_ambiente(cls) -> Config:
        grezzo = os.environ.get("NORMATTIVA_TIMEOUT_SECONDI")
        if grezzo is None:
            return cls()
        try:
            return cls(timeout_secondi=float(grezzo))
        except ValueError:
            return cls()
