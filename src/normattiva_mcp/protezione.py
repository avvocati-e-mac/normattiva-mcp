"""Coordinatore SQLite condiviso per quota, cache, cooldown e telemetria minima."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from .config import Config
from .errori import ProtezioneNonDisponibile, RichiestaBloccata
from .protezione_db import FINESTRA, ArchivioProtezione, RapportoRete  # noqa: F401

INTERVALLO_MINIMO = 5.0
TTL_VIGENTE = 7 * 24 * 60 * 60
TTL_STORICO = 30 * 24 * 60 * 60
TTL_ERRORE = 60 * 60


@dataclass(frozen=True, slots=True)
class RispostaProtetta:
    status: int
    contenuto: bytes
    headers: dict[str, str]
    rapporto: RapportoRete


class ProtezioneTraffico:
    def __init__(
        self,
        config: Config,
        *,
        ora: Callable[[], float] = time.time,
        dormi: Callable[[float], None] = time.sleep,
        intervallo_minimo: float = INTERVALLO_MINIMO,
    ) -> None:
        self.config = config
        self.ora = ora
        self.dormi = dormi
        self.intervallo_minimo = intervallo_minimo
        self._archivio = ArchivioProtezione(config, ora)

    def _connetti(self) -> sqlite3.Connection:
        return self._archivio.connetti()

    @staticmethod
    def chiave_cache(urn: str) -> str:
        return hashlib.sha256(urn.encode()).hexdigest()

    def stato(self, attivita: str = "consultazione") -> RapportoRete:
        try:
            with self._connetti() as db:
                return self._archivio.rapporto(
                    db, origine="locale", acquisita=None, attivita=attivita
                )
        except sqlite3.Error as exc:
            raise ProtezioneNonDisponibile(type(exc).__name__) from exc

    def rapporto_dopo_tentativo(self, attivita: str) -> RapportoRete:
        with self._connetti() as db:
            return self._archivio.rapporto(
                db, origine="rete", acquisita=self.ora(), attivita=attivita
            )

    def aggregati_giornalieri(self) -> dict[str, int | str | None]:
        return self._archivio.aggregati_giornalieri()

    def _verifica_budget(
        self, db: sqlite3.Connection, attivita: str, prenotazione: str | None
    ) -> None:
        adesso = self.ora()
        self._archivio.interrompi_prenotazioni_scadute(db, adesso)
        consultazioni, diagnosi, totale = self._archivio.conteggi(db, adesso)
        if prenotazione:
            r = db.execute(
                "SELECT residue, stato FROM prenotazioni WHERE id=?", (prenotazione,)
            ).fetchone()
            if not r or r["stato"] != "attiva" or r["residue"] <= 0:
                raise RichiestaBloccata("prenotazione della verifica assente o esaurita")
            db.execute("UPDATE prenotazioni SET residue=residue-1 WHERE id=?", (prenotazione,))
            return
        riservate = self._archivio.riservate(db)
        if totale + riservate >= self.config.limite_assoluto:
            raise RichiestaBloccata("limite assoluto delle ultime 24 ore raggiunto o già prenotato")
        if attivita == "diagnosi" and diagnosi >= self.config.limite_diagnosi:
            raise RichiestaBloccata("limite locale delle diagnosi nelle ultime 24 ore raggiunto")
        if attivita == "consultazione" and consultazioni >= self.config.limite_consultazioni:
            raise RichiestaBloccata(
                "limite locale delle consultazioni nelle ultime 24 ore raggiunto"
            )

    def _quota_globale(self, db: sqlite3.Connection) -> str:
        totale = self._archivio.conteggi(db, self.ora())[2]
        return f"{totale}/{self.config.limite_assoluto}"

    def esegui(
        self,
        urn: str,
        *,
        attivita: str,
        storico: bool,
        aggiorna: bool,
        invia: Callable[[], httpx.Response],
        prenotazione: str | None = None,
    ) -> RispostaProtetta:
        chiave = self.chiave_cache(urn)
        try:
            with self._connetti() as db:
                db.execute("BEGIN IMMEDIATE")
                adesso = self.ora()
                cache = db.execute("SELECT * FROM cache WHERE chiave=?", (chiave,)).fetchone()
                if cache and not aggiorna and (cache["scade"] > adesso or self.config.offline):
                    db.execute(
                        "INSERT INTO eventi_cache(ts,attivita) VALUES(?,?)", (adesso, attivita)
                    )
                    rapporto = self._archivio.rapporto(
                        db, origine="cache", acquisita=cache["acquisita"], attivita=attivita
                    )
                    db.commit()
                    return RispostaProtetta(
                        cache["status"], cache["corpo"], json.loads(cache["headers"]), rapporto
                    )
                if self.config.offline:
                    rapporto = self._archivio.rapporto(
                        db, origine="cache", acquisita=None, attivita=attivita, bloccato=True
                    )
                    raise RichiestaBloccata(
                        "modalità offline attiva e risposta assente dalla cache"
                    )
                cooldown, incidente = self._archivio.cooldown(db, adesso)
                if cooldown:
                    raise RichiestaBloccata(
                        f"cooldown attivo fino a {self._archivio.iso(cooldown)} ({incidente})"
                    )
                self._verifica_budget(db, attivita, prenotazione)
                r_ultima = db.execute(
                    "SELECT valore FROM stato WHERE chiave='ultima_richiesta_fine'"
                ).fetchone()
                ultima = float(r_ultima[0]) if r_ultima else None
                if ultima is not None:
                    pausa = self.intervallo_minimo - (self.ora() - float(ultima))
                    if pausa > 0:
                        self.dormi(pausa)
                iniziata = self.ora()
                quota_prima = self._quota_globale(db)
                cursore = db.execute(
                    "INSERT INTO tentativi(ts,attivita,quota_prima,cache_esito) "
                    "VALUES(?,?,?,'miss')",
                    (iniziata, attivita, quota_prima),
                )
                try:
                    risposta = invia()
                except httpx.TransportError as exc:
                    durata = int((self.ora() - iniziata) * 1000)
                    db.execute(
                        "UPDATE tentativi SET durata_ms=?, errore=1, quota_dopo=?, "
                        "categoria_incidente=? WHERE id=?",
                        (
                            durata,
                            self._quota_globale(db),
                            f"trasporto {type(exc).__name__}",
                            cursore.lastrowid,
                        ),
                    )
                    self._archivio.trasporto_fallito(db, f"trasporto {type(exc).__name__}")
                    db.execute(
                        "INSERT OR REPLACE INTO stato VALUES('ultima_richiesta_fine', ?)",
                        (str(self.ora()),),
                    )
                    db.commit()
                    raise
                except Exception as exc:
                    durata = int((self.ora() - iniziata) * 1000)
                    db.execute(
                        "UPDATE tentativi SET durata_ms=?, errore=1, quota_dopo=?, "
                        "categoria_incidente=? WHERE id=?",
                        (
                            durata,
                            self._quota_globale(db),
                            f"errore client {type(exc).__name__}",
                            cursore.lastrowid,
                        ),
                    )
                    self._archivio.imposta_incidente(
                        db, f"errore client {type(exc).__name__}", self.ora() + 15 * 60
                    )
                    db.execute(
                        "INSERT OR REPLACE INTO stato VALUES('ultima_richiesta_fine', ?)",
                        (str(self.ora()),),
                    )
                    db.commit()
                    raise
                durata = int((self.ora() - iniziata) * 1000)
                headers = {
                    k: v
                    for k, v in risposta.headers.items()
                    if k.lower() in {"retry-after", "x-request-id", "request-id", "content-type"}
                }
                errore = int(risposta.status_code >= 400)
                db.execute(
                    "UPDATE tentativi SET durata_ms=?, status=?, dimensione=?, "
                    "retry_after=?, request_id=?, errore=?, quota_dopo=?, "
                    "categoria_incidente=? WHERE id=?",
                    (
                        durata,
                        risposta.status_code,
                        len(risposta.content),
                        risposta.headers.get("Retry-After"),
                        risposta.headers.get("x-request-id") or risposta.headers.get("request-id"),
                        errore,
                        self._quota_globale(db),
                        f"HTTP {risposta.status_code}" if errore else None,
                        cursore.lastrowid,
                    ),
                )
                self._archivio.classifica(db, risposta)
                db.execute(
                    "INSERT OR REPLACE INTO stato VALUES('ultima_richiesta_fine', ?)",
                    (str(self.ora()),),
                )
                ttl = (
                    TTL_ERRORE
                    if risposta.status_code in {400, 404}
                    else TTL_STORICO
                    if storico
                    else TTL_VIGENTE
                )
                if risposta.status_code in {200, 400, 404}:
                    db.execute(
                        "INSERT OR REPLACE INTO cache VALUES(?,?,?,?,?,?)",
                        (
                            chiave,
                            iniziata,
                            iniziata + ttl,
                            risposta.status_code,
                            json.dumps(headers),
                            risposta.content,
                        ),
                    )
                rapporto = self._archivio.rapporto(
                    db, origine="rete", acquisita=iniziata, attivita=attivita
                )
                db.commit()
                return RispostaProtetta(risposta.status_code, risposta.content, headers, rapporto)
        except RichiestaBloccata:
            raise
        except httpx.TransportError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ProtezioneNonDisponibile(type(exc).__name__) from exc

    def registra_malformata(self, urn: str) -> None:
        try:
            with self._connetti() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM cache WHERE chiave=?", (self.chiave_cache(urn),))
                db.execute(
                    "UPDATE tentativi SET errore=1, categoria_incidente='risposta malformata' "
                    "WHERE id=(SELECT MAX(id) FROM tentativi)"
                )
                self._archivio.imposta_incidente(db, "risposta malformata", self.ora() + 15 * 60)
                db.commit()
        except sqlite3.Error as exc:
            raise ProtezioneNonDisponibile(type(exc).__name__) from exc

    def prenota_verifica(self, costo: int) -> str:
        try:
            with self._connetti() as db:
                db.execute("BEGIN IMMEDIATE")
                adesso = self.ora()
                self._archivio.interrompi_prenotazioni_scadute(db, adesso)
                cooldown, _ = self._archivio.cooldown(db, adesso)
                if cooldown:
                    raise RichiestaBloccata(
                        "cooldown attivo: la verifica completa non può iniziare"
                    )
                ultima = db.execute(
                    "SELECT MAX(creata) FROM prenotazioni WHERE stato='completa'"
                ).fetchone()[0]
                if ultima and adesso - float(ultima) < 7 * 24 * 3600:
                    raise RichiestaBloccata(
                        "una verifica completa è già stata eseguita negli ultimi 7 giorni"
                    )
                totale = self._archivio.conteggi(db, adesso)[2]
                riservate = self._archivio.riservate(db)
                if totale + riservate + costo > self.config.limite_assoluto:
                    raise RichiestaBloccata(
                        "budget assoluto insufficiente per completare l'intera verifica"
                    )
                ident = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO prenotazioni VALUES(?,?,?,?, 'attiva')",
                    (ident, adesso, costo, costo),
                )
                db.commit()
                return ident
        except RichiestaBloccata:
            raise
        except sqlite3.Error as exc:
            raise ProtezioneNonDisponibile(type(exc).__name__) from exc

    def chiudi_prenotazione(self, ident: str, *, completa: bool) -> None:
        try:
            with self._connetti() as db:
                db.execute(
                    "UPDATE prenotazioni SET stato=? WHERE id=?",
                    ("completa" if completa else "interrotta", ident),
                )
        except sqlite3.Error as exc:
            raise ProtezioneNonDisponibile(type(exc).__name__) from exc
