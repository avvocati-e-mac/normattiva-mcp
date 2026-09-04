"""Prove offline del coordinatore condiviso.

Ogni percorso che finge HTTP passa da ``httpx.MockTransport``: la suite non
contatta mai Normattiva e non cerca di provocare limiti o blocchi reali.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from normattiva_mcp.config import Config
from normattiva_mcp.errori import ProtezioneNonDisponibile, RichiestaBloccata
from normattiva_mcp.protezione import (
    TTL_ERRORE,
    TTL_VIGENTE,
    ProtezioneTraffico,
)

_URN = "urn:nir:stato:legge:1970-05-20;300~art18"


class Orologio:
    def __init__(self, iniziale: float = 1_700_000_000) -> None:
        self.adesso = iniziale

    def __call__(self) -> float:
        return self.adesso

    def avanza(self, secondi: float) -> None:
        self.adesso += secondi


def _config(tmp_path: Path, **limiti: int) -> Config:
    return Config(database=tmp_path / "protezione.sqlite3", **limiti)


def _invia(
    status: int = 200, *, headers: dict[str, str] | None = None, corpo: bytes = b"{}"
) -> tuple[Callable[[], httpx.Response], list[httpx.Request]]:
    """Una richiesta HTTP finta, ma attraverso il trasporto ufficiale dei test."""
    richieste: list[httpx.Request] = []

    def gestore(richiesta: httpx.Request) -> httpx.Response:
        richieste.append(richiesta)
        return httpx.Response(status, headers=headers, content=corpo, request=richiesta)

    client = httpx.Client(transport=httpx.MockTransport(gestore))
    return lambda: client.get("https://example.invalid/opendata"), richieste


def test_cache_vigente_e_storica_hanno_ttl_distinti(tmp_path: Path) -> None:
    ora = Orologio()
    protezione = ProtezioneTraffico(_config(tmp_path), ora=ora, intervallo_minimo=0)
    invia, richieste = _invia()

    prima = protezione.esegui(
        _URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia
    )
    ora.avanza(TTL_VIGENTE - 1)
    da_cache = protezione.esegui(
        _URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia
    )
    assert prima.rapporto.origine == "rete"
    assert da_cache.rapporto.origine == "cache"
    assert len(richieste) == 1

    storico = _URN + "!vig=2020-01-01"
    protezione.esegui(storico, attivita="consultazione", storico=True, aggiorna=False, invia=invia)
    ora.avanza(TTL_VIGENTE + 1)
    # Il vigente è scaduto; lo storico resta servibile fino a 30 giorni.
    protezione.esegui(_URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia)
    storico_cache = protezione.esegui(
        storico, attivita="consultazione", storico=True, aggiorna=False, invia=invia
    )
    assert storico_cache.rapporto.origine == "cache"
    assert len(richieste) == 3


def test_errori_400_e_404_sono_in_cache_per_un_ora(tmp_path: Path) -> None:
    ora = Orologio()
    protezione = ProtezioneTraffico(_config(tmp_path), ora=ora, intervallo_minimo=0)
    invia, richieste = _invia(404, corpo=b'{"message":"atto non trovato"}')
    protezione.esegui(_URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia)
    ora.avanza(TTL_ERRORE - 1)
    assert (
        protezione.esegui(
            _URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia
        ).rapporto.origine
        == "cache"
    )
    ora.avanza(2)
    protezione.esegui(_URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia)
    assert len(richieste) == 2


def test_offline_usa_solo_cache_e_non_invia_miss(tmp_path: Path) -> None:
    ora = Orologio()
    online = ProtezioneTraffico(_config(tmp_path), ora=ora, intervallo_minimo=0)
    invia, richieste = _invia()
    online.esegui(_URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia)
    offline = ProtezioneTraffico(
        Config(database=tmp_path / "protezione.sqlite3", offline=True), ora=ora, intervallo_minimo=0
    )
    assert (
        offline.esegui(
            _URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia
        ).rapporto.origine
        == "cache"
    )
    with pytest.raises(RichiestaBloccata, match="offline"):
        offline.esegui(
            _URN + "bis", attivita="consultazione", storico=False, aggiorna=False, invia=invia
        )
    assert len(richieste) == 1


def test_intervallo_globale_e_dedup_sono_condivisi_fra_istanze(tmp_path: Path) -> None:
    ora = Orologio()
    pause: list[float] = []
    config = _config(tmp_path)
    uno = ProtezioneTraffico(config, ora=ora, dormi=pause.append)
    due = ProtezioneTraffico(config, ora=ora, dormi=pause.append)
    invia, richieste = _invia()
    uno.esegui(_URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia)
    # Forzare l'aggiornamento consuma quota, ma non può aggirare la distanza minima.
    due.esegui(_URN + "-altro", attivita="consultazione", storico=False, aggiorna=True, invia=invia)
    assert pause == [5.0]
    assert len(richieste) == 2


def test_dedup_concorrente_condivide_cache_e_fa_una_sola_http(tmp_path: Path) -> None:
    config = _config(tmp_path)
    bariera = threading.Barrier(2)
    conteggio = 0
    lock = threading.Lock()
    coordinatori = [ProtezioneTraffico(config, intervallo_minimo=0) for _ in range(2)]

    def gestore(richiesta: httpx.Request) -> httpx.Response:
        nonlocal conteggio
        with lock:
            conteggio += 1
        return httpx.Response(200, content=b"{}", request=richiesta)

    def lavoro(coordinatore: ProtezioneTraffico) -> None:
        client = httpx.Client(transport=httpx.MockTransport(gestore))
        bariera.wait()
        coordinatore.esegui(
            _URN,
            attivita="consultazione",
            storico=False,
            aggiorna=False,
            invia=lambda: client.get("https://example.invalid/opendata"),
        )

    thread = [threading.Thread(target=lavoro, args=(c,)) for c in coordinatori]
    for t in thread:
        t.start()
    for t in thread:
        t.join(timeout=10)
    assert all(not t.is_alive() for t in thread)
    assert conteggio == 1


def test_urn_diversi_non_hanno_mai_due_invia_in_volo(tmp_path: Path) -> None:
    """La transazione SQLite copre anche la fase HTTP, non solo cache/quota."""
    config = _config(tmp_path)
    coordinatori = [ProtezioneTraffico(config, intervallo_minimo=0) for _ in range(2)]
    entrata_prima = threading.Event()
    libera_prima = threading.Event()
    attivi = 0
    massimo_attivi = 0
    lock = threading.Lock()

    def invia_prima() -> httpx.Response:
        nonlocal attivi, massimo_attivi
        with lock:
            attivi += 1
            massimo_attivi = max(massimo_attivi, attivi)
        entrata_prima.set()
        assert libera_prima.wait(5)
        with lock:
            attivi -= 1
        return httpx.Response(200, content=b"{}")

    def invia_seconda() -> httpx.Response:
        nonlocal attivi, massimo_attivi
        with lock:
            attivi += 1
            massimo_attivi = max(massimo_attivi, attivi)
            attivi -= 1
        return httpx.Response(200, content=b"{}")

    def lavoro(
        coordinatore: ProtezioneTraffico, urn: str, invia: Callable[[], httpx.Response]
    ) -> None:
        coordinatore.esegui(
            urn, attivita="consultazione", storico=False, aggiorna=False, invia=invia
        )

    primo = threading.Thread(target=lavoro, args=(coordinatori[0], _URN, invia_prima))
    secondo = threading.Thread(
        target=lavoro, args=(coordinatori[1], _URN + "-diverso", invia_seconda)
    )
    primo.start()
    assert entrata_prima.wait(5)
    secondo.start()
    # Se il secondo attraversasse il lock DB, il massimo salirebbe già a 2.
    assert massimo_attivi == 1
    libera_prima.set()
    primo.join(timeout=10)
    secondo.join(timeout=10)
    assert not primo.is_alive() and not secondo.is_alive()
    assert massimo_attivi == 1


@pytest.mark.parametrize(
    ("status", "headers", "attesa"),
    [
        (429, {"Retry-After": "60"}, 6 * 3600),
        (401, {}, 24 * 3600),
        (403, {}, 24 * 3600),
        (409, {}, 24 * 3600),
        (500, {}, 15 * 60),
    ],
)
def test_risposte_anomale_applicano_cooldown_e_non_ritentano(
    tmp_path: Path, status: int, headers: dict[str, str], attesa: int
) -> None:
    ora = Orologio()
    protezione = ProtezioneTraffico(_config(tmp_path), ora=ora, intervallo_minimo=0)
    invia, richieste = _invia(status, headers=headers)
    risposta = protezione.esegui(
        _URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia
    )
    assert risposta.rapporto.livello == "bloccato"
    stato = protezione.stato()
    assert stato.cooldown_fino is not None
    assert stato.ultimo_incidente is not None
    with pytest.raises(RichiestaBloccata, match="cooldown"):
        protezione.esegui(
            _URN + "nuovo", attivita="consultazione", storico=False, aggiorna=False, invia=invia
        )
    assert len(richieste) == 1
    assert (
        float(
            sqlite3.connect(tmp_path / "protezione.sqlite3")
            .execute("SELECT valore FROM stato WHERE chiave='cooldown_fino'")
            .fetchone()[0]
        )
        >= ora() + attesa
    )


def test_errore_trasporto_consuma_quota_e_cresce_il_cooldown(tmp_path: Path) -> None:
    ora = Orologio()
    protezione = ProtezioneTraffico(_config(tmp_path), ora=ora, intervallo_minimo=0)

    def rotto() -> httpx.Response:
        raise httpx.ConnectError("simulato")

    with pytest.raises(httpx.TransportError):
        protezione.esegui(
            _URN, attivita="consultazione", storico=False, aggiorna=False, invia=rotto
        )
    assert protezione.stato().ultimo_incidente is not None
    assert protezione.aggregati_giornalieri()["richieste_reali"] == 1
    with pytest.raises(RichiestaBloccata):
        protezione.esegui(
            _URN + "x", attivita="consultazione", storico=False, aggiorna=False, invia=rotto
        )


def test_cooldown_trasporto_raddoppia_fino_al_massimo_di_24_ore(tmp_path: Path) -> None:
    ora = Orologio()
    protezione = ProtezioneTraffico(_config(tmp_path), ora=ora, intervallo_minimo=0)

    def rotto() -> httpx.Response:
        raise httpx.ConnectError("simulato")

    for i in range(12):
        with pytest.raises(httpx.TransportError):
            protezione.esegui(
                _URN + str(i), attivita="consultazione", storico=False, aggiorna=False, invia=rotto
            )
        db = sqlite3.connect(tmp_path / "protezione.sqlite3")
        fino = float(
            db.execute("SELECT valore FROM stato WHERE chiave='cooldown_fino'").fetchone()[0]
        )
        attesa = min(24 * 3600, 15 * 60 * (2**i))
        assert fino == ora() + attesa
        ora.avanza(attesa)


def test_quote_diagnosi_e_assoluta_bloccano_prima_della_http(tmp_path: Path) -> None:
    ora = Orologio()
    protezione = ProtezioneTraffico(
        _config(tmp_path, limite_consultazioni=30, limite_diagnosi=2, limite_assoluto=3),
        ora=ora,
        intervallo_minimo=0,
    )
    invia, richieste = _invia()
    for suffisso in ("a", "b"):
        protezione.esegui(
            _URN + suffisso, attivita="diagnosi", storico=False, aggiorna=False, invia=invia
        )
    with pytest.raises(RichiestaBloccata, match="diagnosi"):
        protezione.esegui(
            _URN + "c", attivita="diagnosi", storico=False, aggiorna=False, invia=invia
        )
    protezione.esegui(
        _URN + "d", attivita="consultazione", storico=False, aggiorna=False, invia=invia
    )
    with pytest.raises(RichiestaBloccata, match="assoluto"):
        protezione.esegui(
            _URN + "e", attivita="consultazione", storico=False, aggiorna=False, invia=invia
        )
    assert len(richieste) == 3


def test_prenotazione_impedisce_verifica_parziale_e_rispetta_sette_giorni(tmp_path: Path) -> None:
    ora = Orologio()
    protezione = ProtezioneTraffico(
        _config(tmp_path, limite_assoluto=4), ora=ora, intervallo_minimo=0
    )
    invia, _ = _invia()
    prenotazione = protezione.prenota_verifica(3)
    with pytest.raises(RichiestaBloccata, match="insufficiente"):
        protezione.prenota_verifica(2)
    for i in range(3):
        protezione.esegui(
            _URN + str(i),
            attivita="verifica",
            storico=False,
            aggiorna=False,
            invia=invia,
            prenotazione=prenotazione,
        )
    with pytest.raises(RichiestaBloccata, match="prenotazione"):
        protezione.esegui(
            _URN + "oltre",
            attivita="verifica",
            storico=False,
            aggiorna=False,
            invia=invia,
            prenotazione=prenotazione,
        )
    protezione.chiudi_prenotazione(prenotazione, completa=True)
    with pytest.raises(RichiestaBloccata, match="7 giorni"):
        protezione.prenota_verifica(1)


def test_telemetria_non_contiene_urn_ne_contenuti_e_ha_aggregati(tmp_path: Path) -> None:
    ora = Orologio()
    protezione = ProtezioneTraffico(_config(tmp_path), ora=ora, intervallo_minimo=0)
    segreto = b"contenuto-da-non-mettere-nei-log"
    invia, _ = _invia(corpo=segreto)
    protezione.esegui(_URN, attivita="consultazione", storico=False, aggiorna=False, invia=invia)
    aggregati = protezione.aggregati_giornalieri()
    assert aggregati["richieste_reali"] == 1
    db = sqlite3.connect(tmp_path / "protezione.sqlite3")
    colonne = {r[1] for r in db.execute("PRAGMA table_info(tentativi)")}
    assert "urn" not in colonne and "contenuto" not in colonne and "corpo" not in colonne
    riga = db.execute("SELECT * FROM tentativi").fetchone()
    assert _URN not in repr(riga) and segreto.decode() not in repr(riga)


def test_database_indisponibile_fallisce_chiuso_prima_di_http(tmp_path: Path) -> None:
    # Un path che è già una directory non è apribile da SQLite come database.
    database = tmp_path / "non-un-db"
    database.mkdir()
    invia, richieste = _invia()
    with pytest.raises(ProtezioneNonDisponibile):
        ProtezioneTraffico(Config(database=database))
    assert richieste == []


def test_config_ambiente_puo_solo_ridurre_quote_e_configura_offline_ua(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NORMATTIVA_STATO_DB", str(tmp_path / "condiviso.sqlite3"))
    monkeypatch.setenv("NORMATTIVA_LIMITE_CONSULTAZIONI", "999")
    monkeypatch.setenv("NORMATTIVA_LIMITE_DIAGNOSI", "1")
    monkeypatch.setenv("NORMATTIVA_LIMITE_ASSOLUTO", "600")
    monkeypatch.setenv("NORMATTIVA_OFFLINE", "1")
    monkeypatch.setenv("NORMATTIVA_CONTATTO_USER_AGENT", "responsabile@example.test")
    config = Config.da_ambiente()
    assert (config.limite_consultazioni, config.limite_diagnosi, config.limite_assoluto) == (
        30,
        1,
        60,
    )
    assert config.offline is True
    assert "responsabile@example.test" in config.user_agent
