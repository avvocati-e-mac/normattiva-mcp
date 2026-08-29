"""Test della CLI — nessuna rete: httpx.Client viene sostituito con un
MockTransport in ogni test che tocca il client (via monkeypatch su
httpx.Client, il punto in cui ClienteNormattiva lo istanzia).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from typer.testing import CliRunner

from normattiva_mcp.cli import app
from normattiva_mcp.client import ClienteNormattiva

runner = CliRunner()

_RISPOSTA_CC_2043 = {
    "code": None,
    "message": None,
    "data": {
        "atto": {
            "titolo": "REGIO DECRETO 16 marzo 1942, n. 262",
            "sottoTitolo": "Codice civile",
            "articoloHtml": (
                '<span class="attachment-just-text">Art. 2043. '
                "(Risarcimento per fatto illecito). Qualunque fatto doloso o "
                "colposo che cagiona ad altri un danno ingiusto obbliga colui "
                "che ha commesso il fatto a risarcire il danno.</span>"
            ),
            "articoloDataInizioVigenza": "19420419",
            "articoloDataFineVigenza": "99999999",
        },
        "lista": None,
    },
    "success": True,
}


def _monkeypatch_http(monkeypatch: pytest.MonkeyPatch, gestore: Callable) -> None:
    """Sostituisce interamente `cli._nuovo_client` con una fabbrica che
    restituisce un ClienteNormattiva con trasporto finto (MockTransport,
    nessuna rete reale) e backoff senza attesa (dormi=no-op): un test che
    fa scattare il circuit breaker non aspetta più secondi reali."""

    def _fabbrica() -> ClienteNormattiva:
        client = ClienteNormattiva(dormi=lambda _secondi: None)
        client._http = httpx.Client(transport=httpx.MockTransport(gestore))
        return client

    monkeypatch.setattr("normattiva_mcp.cli._nuovo_client", _fabbrica)


class TestComandoLeggi:
    def test_leggi_codice_civile_2043(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_RISPOSTA_CC_2043)

        _monkeypatch_http(monkeypatch, gestore)
        risultato = runner.invoke(app, ["leggi", "codice civile", "2043"])
        assert risultato.exit_code == 0
        assert "Risarcimento per fatto illecito" in risultato.stdout
        assert "CC BY 4.0" in risultato.stdout

    def test_leggi_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_RISPOSTA_CC_2043)

        _monkeypatch_http(monkeypatch, gestore)
        risultato = runner.invoke(app, ["leggi", "codice civile", "2043", "--json"])
        assert risultato.exit_code == 0
        import json

        corpo = json.loads(risultato.stdout)
        assert corpo["esito"] == "articolo"
        assert corpo["urn"] == "urn:nir:stato:regio.decreto:1942-03-16;262:2~art2043"

    def test_leggi_fonte_sconosciuta_esce_con_errore(self) -> None:
        risultato = runner.invoke(app, ["leggi", "una fonte inventata", "1"])
        assert risultato.exit_code == 1

    def test_leggi_fonte_non_disponibile_esce_con_errore(self) -> None:
        risultato = runner.invoke(app, ["leggi", "gdpr", "6"])
        assert risultato.exit_code == 1
        assert "GDPR" in risultato.output


class TestComandoLink:
    def test_link_produce_markdown_completo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regressione: senza markup=False, Rich interpretava le parentesi
        quadre del Markdown come tag di stile e le scartava — il link
        usciva come "(url)" invece di "[testo](url)"."""

        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_RISPOSTA_CC_2043)

        _monkeypatch_http(monkeypatch, gestore)
        risultato = runner.invoke(app, ["link", "codice civile", "2043"])
        assert risultato.exit_code == 0
        assert risultato.stdout.strip().startswith("[art. 2043")
        assert "](https://www.normattiva.it/uri-res/N2Ls?" in risultato.stdout

    def test_link_non_verificato_su_errore(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "atto non trovato"})

        _monkeypatch_http(monkeypatch, gestore)
        risultato = runner.invoke(app, ["link", "codice civile", "2043"])
        assert risultato.exit_code == 1

    def test_link_non_verificare_salta_la_rete(self) -> None:
        # Nessun monkeypatch: se il comando provasse a fare rete, questo
        # test fallirebbe con un errore di trasporto reale.
        risultato = runner.invoke(app, ["link", "codice civile", "2043", "--non-verificare"])
        assert risultato.exit_code == 0
        assert "[art. 2043" in risultato.stdout


class TestComandoFonti:
    def test_fonti_senza_argomento_elenca_tutte(self) -> None:
        risultato = runner.invoke(app, ["fonti"])
        assert risultato.exit_code == 0
        assert "Codice Civile" in risultato.stdout

    def test_fonti_con_argomento_cerca_una_fonte(self) -> None:
        risultato = runner.invoke(app, ["fonti", "l.fall."])
        assert risultato.exit_code == 0
        assert "Legge Fallimentare" in risultato.stdout

    def test_fonti_gdpr_dice_non_disponibile(self) -> None:
        risultato = runner.invoke(app, ["fonti", "gdpr"])
        assert risultato.exit_code == 0
        assert "non è disponibile su Normattiva" in risultato.stdout

    def test_fonti_sconosciuta_esce_con_errore(self) -> None:
        risultato = runner.invoke(app, ["fonti", "una fonte che non esiste"])
        assert risultato.exit_code == 1


class TestComandoDoctor:
    def test_doctor_endpoint_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        risposta_costituzione = {
            "code": None,
            "message": None,
            "data": {
                "atto": {
                    "titolo": "COSTITUZIONE",
                    "sottoTitolo": "Costituzione",
                    "articoloHtml": (
                        '<h2 class="article-num-akn" id="art_1">Art. 1</h2>'
                        '<span class="art-just-text-akn">Testo art. 1 Cost.</span>'
                    ),
                    "articoloDataInizioVigenza": "19480101",
                    "articoloDataFineVigenza": "99999999",
                },
                "lista": None,
            },
            "success": True,
        }

        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=risposta_costituzione)

        _monkeypatch_http(monkeypatch, gestore)
        risultato = runner.invoke(app, ["doctor"])
        assert risultato.exit_code == 0
        assert "risponde correttamente" in risultato.stdout

    def test_doctor_endpoint_in_avaria(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "Errore generico"})

        _monkeypatch_http(monkeypatch, gestore)
        risultato = runner.invoke(app, ["doctor"])
        assert risultato.exit_code == 1


class TestComandoVerifica:
    def test_verifica_senza_tutte_chiede_il_flag(self) -> None:
        risultato = runner.invoke(app, ["verifica"])
        assert risultato.exit_code == 1
        assert "--tutte" in risultato.output

    def test_verifica_si_ferma_se_la_sonda_fallisce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """La regola centrale: un'avaria del servizio non deve mai
        tradursi in righe della tabella marcate come sbagliate."""

        def gestore(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "Errore generico"})

        _monkeypatch_http(monkeypatch, gestore)
        risultato = runner.invoke(app, ["verifica", "--tutte"])
        assert risultato.exit_code == 1
        assert "nessuna riga è stata giudicata" in risultato.output
