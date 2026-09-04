"""Persistenza SQLite e calcoli locali del coordinatore di traffico."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from .config import Config
from .errori import ProtezioneNonDisponibile

FINESTRA = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class RapportoRete:
    origine: str
    acquisita_il: str | None
    attivita: str
    consumo_attivita: str
    consumo_globale: str
    richieste_residue: int
    cooldown_fino: str | None
    ultimo_incidente: str | None
    livello: str
    avviso: str

    def modello(self) -> dict[str, object]:
        return asdict(self)


class ArchivioProtezione:
    """Incapsula schema, connessioni e stato tecnico condiviso via SQLite."""

    def __init__(self, config: Config, ora: Callable[[], float]) -> None:
        self.config = config
        self.ora = ora
        self.inizializza()

    def connetti(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.config.database, timeout=60, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=60000")
            return conn
        except (OSError, sqlite3.Error) as exc:
            raise ProtezioneNonDisponibile(type(exc).__name__) from exc

    def inizializza(self) -> None:
        try:
            Path(self.config.database).parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ProtezioneNonDisponibile(type(exc).__name__) from exc
        ultimo_errore: Exception | None = None
        # CLI e MCP possono contendere il brevissimo passaggio a WAL: si
        # ritenta solo l'avvio locale, mai una chiamata HTTP.
        for _ in range(20):
            try:
                with self.connetti() as db:
                    db.executescript(
                        """
                        PRAGMA journal_mode=WAL;
                        CREATE TABLE IF NOT EXISTS tentativi(
                          id INTEGER PRIMARY KEY, ts REAL NOT NULL, attivita TEXT NOT NULL,
                          durata_ms INTEGER, status INTEGER, dimensione INTEGER,
                          retry_after TEXT, request_id TEXT, errore INTEGER NOT NULL DEFAULT 0,
                          quota_prima TEXT, quota_dopo TEXT, categoria_incidente TEXT,
                          cache_esito TEXT NOT NULL DEFAULT 'miss');
                        CREATE INDEX IF NOT EXISTS ix_tentativi_ts ON tentativi(ts);
                        CREATE TABLE IF NOT EXISTS cache(
                          chiave TEXT PRIMARY KEY, acquisita REAL NOT NULL, scade REAL NOT NULL,
                          status INTEGER NOT NULL, headers TEXT NOT NULL, corpo BLOB NOT NULL);
                        CREATE TABLE IF NOT EXISTS eventi_cache(
                          id INTEGER PRIMARY KEY, ts REAL NOT NULL, attivita TEXT NOT NULL);
                        CREATE TABLE IF NOT EXISTS stato(
                          chiave TEXT PRIMARY KEY, valore TEXT NOT NULL);
                        CREATE TABLE IF NOT EXISTS prenotazioni(
                          id TEXT PRIMARY KEY, creata REAL NOT NULL, iniziale INTEGER NOT NULL,
                          residue INTEGER NOT NULL, stato TEXT NOT NULL);
                        """
                    )
                    self._migra_tentativi(db)
                return
            except sqlite3.OperationalError as exc:
                ultimo_errore = exc
                if "locked" not in str(exc).lower():
                    break
                time.sleep(0.05)
            except (OSError, sqlite3.Error, ProtezioneNonDisponibile) as exc:
                ultimo_errore = exc
                break
        assert ultimo_errore is not None
        raise ProtezioneNonDisponibile(type(ultimo_errore).__name__) from ultimo_errore

    @staticmethod
    def _migra_tentativi(db: sqlite3.Connection) -> None:
        """Aggiunge i campi tecnici alle basi create da versioni precedenti."""
        colonne = {r["name"] for r in db.execute("PRAGMA table_info(tentativi)")}
        mancanti = {
            "quota_prima": "TEXT",
            "quota_dopo": "TEXT",
            "categoria_incidente": "TEXT",
            "cache_esito": "TEXT NOT NULL DEFAULT 'miss'",
        }
        for nome, definizione in mancanti.items():
            if nome not in colonne:
                db.execute(f"ALTER TABLE tentativi ADD COLUMN {nome} {definizione}")

    @staticmethod
    def iso(ts: float | None) -> str | None:
        return datetime.fromtimestamp(ts, UTC).isoformat() if ts is not None else None

    def conteggi(self, db: sqlite3.Connection, adesso: float) -> tuple[int, int, int]:
        righe = db.execute(
            "SELECT attivita, COUNT(*) n FROM tentativi WHERE ts >= ? GROUP BY attivita",
            (adesso - FINESTRA,),
        ).fetchall()
        valori = {r["attivita"]: r["n"] for r in righe}
        return valori.get("consultazione", 0), valori.get("diagnosi", 0), sum(valori.values())

    def cooldown(self, db: sqlite3.Connection, adesso: float) -> tuple[float | None, str | None]:
        r = db.execute("SELECT valore FROM stato WHERE chiave='cooldown_fino'").fetchone()
        motivo = db.execute("SELECT valore FROM stato WHERE chiave='ultimo_incidente'").fetchone()
        fino = float(r[0]) if r else None
        return (fino if fino and fino > adesso else None, motivo[0] if motivo else None)

    @staticmethod
    def riservate(db: sqlite3.Connection) -> int:
        return db.execute(
            "SELECT COALESCE(SUM(residue),0) FROM prenotazioni WHERE stato='attiva'"
        ).fetchone()[0]

    def interrompi_prenotazioni_scadute(self, db: sqlite3.Connection, adesso: float) -> None:
        db.execute(
            "UPDATE prenotazioni SET stato='interrotta' WHERE stato='attiva' AND creata < ?",
            (adesso - FINESTRA,),
        )

    def rapporto(
        self,
        db: sqlite3.Connection,
        *,
        origine: str,
        acquisita: float | None,
        attivita: str,
        bloccato: bool = False,
    ) -> RapportoRete:
        adesso = self.ora()
        consultazioni, diagnosi, totale = self.conteggi(db, adesso)
        if attivita == "diagnosi":
            usate, limite = diagnosi, self.config.limite_diagnosi
        elif attivita == "verifica":
            usate = db.execute(
                "SELECT COUNT(*) FROM tentativi WHERE ts>=? AND attivita='verifica'",
                (adesso - FINESTRA,),
            ).fetchone()[0]
            limite = self.config.limite_assoluto
        else:
            usate, limite = consultazioni, self.config.limite_consultazioni
        riservate = self.riservate(db)
        residue = (
            riservate
            if attivita == "verifica" and riservate
            else min(
                max(0, limite - usate),
                max(0, self.config.limite_assoluto - totale - riservate),
            )
        )
        cooldown, incidente = self.cooldown(db, adesso)
        rapporto = max(usate / limite, totale / self.config.limite_assoluto)
        livello = (
            "bloccato"
            if bloccato or cooldown or residue == 0
            else "critico"
            if rapporto >= 0.8
            else "attenzione"
            if rapporto >= 0.5
            else "ok"
        )
        soglia = ""
        if rapporto >= 0.9:
            soglia = " — soglia 90% superata"
        elif rapporto >= 0.8:
            soglia = " — soglia 80% superata"
        elif rapporto >= 0.5:
            soglia = " — soglia 50% superata"
        nome = (
            "diagnosi"
            if attivita == "diagnosi"
            else ("verifica" if attivita == "verifica" else "consultazione")
        )
        return RapportoRete(
            origine=origine,
            acquisita_il=self.iso(acquisita) if acquisita else None,
            attivita=attivita,
            consumo_attivita=f"{usate}/{limite}",
            consumo_globale=f"{totale}/{self.config.limite_assoluto}",
            richieste_residue=residue,
            cooldown_fino=self.iso(cooldown) if cooldown else None,
            ultimo_incidente=incidente,
            livello=livello,
            avviso=(
                f"{nome} {usate}/{limite} — totale {totale}/{self.config.limite_assoluto}{soglia}"
            ),
        )

    def aggregati_giornalieri(self) -> dict[str, int | str | None]:
        try:
            adesso = self.ora()
            inizio = (
                datetime.fromtimestamp(adesso, UTC)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            with self.connetti() as db:
                tentativi = db.execute(
                    "SELECT COUNT(*) n, COALESCE(SUM(errore),0) e FROM tentativi WHERE ts>=?",
                    (inizio,),
                ).fetchone()
                hit = db.execute(
                    "SELECT COUNT(*) FROM eventi_cache WHERE ts>=?", (inizio,)
                ).fetchone()[0]
                densita = db.execute(
                    "SELECT COUNT(*) n FROM tentativi WHERE ts>=? "
                    "GROUP BY CAST(ts/3600 AS INT) ORDER BY n DESC LIMIT 1",
                    (inizio,),
                ).fetchone()
                cooldown, _ = self.cooldown(db, adesso)
            return {
                "data_utc": self.iso(inizio)[:10],
                "richieste_reali": tentativi["n"],
                "cache_hit": hit,
                "errori": tentativi["e"],
                "massimo_in_un_ora": densita["n"] if densita else 0,
                "cooldown_fino": self.iso(cooldown) if cooldown else None,
            }
        except sqlite3.Error as exc:
            raise ProtezioneNonDisponibile(type(exc).__name__) from exc

    def imposta_incidente(self, db: sqlite3.Connection, categoria: str, fino: float) -> None:
        testo = f"{self.iso(self.ora())} — {categoria}"
        db.execute("INSERT OR REPLACE INTO stato VALUES('cooldown_fino', ?)", (str(fino),))
        db.execute("INSERT OR REPLACE INTO stato VALUES('ultimo_incidente', ?)", (testo,))

    def classifica(self, db: sqlite3.Connection, risposta: httpx.Response) -> None:
        adesso, status = self.ora(), risposta.status_code
        if status == 429:
            attesa = self.retry_after_secondi(risposta.headers.get("Retry-After"), adesso)
            self.imposta_incidente(db, "HTTP 429", adesso + max(6 * 3600, attesa))
        elif status in {401, 403, 409}:
            self.imposta_incidente(db, f"HTTP {status} anomalo", adesso + 24 * 3600)
        elif 500 <= status < 600:
            self.imposta_incidente(db, f"HTTP {status}", adesso + 15 * 60)
        else:
            db.execute("INSERT OR REPLACE INTO stato VALUES('guasti_trasporto','0')")

    @staticmethod
    def retry_after_secondi(valore: str | None, adesso: float) -> float:
        if not valore:
            return 0
        try:
            return max(0, float(valore))
        except ValueError:
            try:
                return max(0, parsedate_to_datetime(valore).timestamp() - adesso)
            except (TypeError, ValueError, OverflowError):
                return 0

    def trasporto_fallito(self, db: sqlite3.Connection, categoria: str) -> None:
        r = db.execute("SELECT valore FROM stato WHERE chiave='guasti_trasporto'").fetchone()
        n = (int(r[0]) if r else 0) + 1
        db.execute("INSERT OR REPLACE INTO stato VALUES('guasti_trasporto', ?)", (str(n),))
        pausa = min(24 * 3600, 15 * 60 * (2 ** (n - 1)))
        self.imposta_incidente(db, categoria, self.ora() + pausa)
