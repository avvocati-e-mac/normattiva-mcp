"""Gestione skill: soltanto filesystem temporaneo, senza rete o home reale."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from normattiva_mcp import __version__
from normattiva_mcp import skill as skill_module
from normattiva_mcp import skill_destinazioni as destinazioni_module
from normattiva_mcp.cli import app
from normattiva_mcp.skill import (
    ClientSkill,
    ErroreSkill,
    LivelloSkill,
    aggiorna,
    destinazioni,
    disinstalla,
    elenco_stati,
    installa,
    mostra,
    trova_sorgente,
    versione_skill,
)

runner = CliRunner()


@pytest.fixture
def sorgente(tmp_path: Path) -> Path:
    directory = tmp_path / "sorgente" / "normattiva-mcp"
    (directory / "references").mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\n"
        "name: normattiva-mcp\n"
        "description: Usa il server MCP Normattiva.\n"
        "metadata:\n"
        f'  version: "{__version__}"\n'
        "---\n"
        "# Normattiva MCP\n",
        encoding="utf-8",
    )
    (directory / "references" / "strumenti.md").write_text("strumenti", encoding="utf-8")
    return directory


def test_destinazioni_native_user_e_project(tmp_path: Path) -> None:
    home = tmp_path / "home"
    progetto = tmp_path / "progetto"
    mappa = {voce.client: voce for voce in destinazioni(home=home, directory_progetto=progetto)}

    assert mappa[ClientSkill.CLAUDE_CODE].directory_utente == home / ".claude/skills"
    assert mappa[ClientSkill.CODEX].directory_utente == home / ".agents/skills"
    assert mappa[ClientSkill.OPENCODE].directory_utente == home / ".config/opencode/skills"
    assert mappa[ClientSkill.PI].directory_utente == home / ".pi/agent/skills"
    assert mappa[ClientSkill.PI].directory_progetto == progetto / ".pi/skills"


def test_trova_sorgente_preferisce_pacchetto_e_ripiega_sul_repo(tmp_path: Path) -> None:
    pacchetto = tmp_path / "package"
    repo = tmp_path / "repo"
    packaged = pacchetto / "data/skill/normattiva-mcp"
    fallback = repo / "skills/normattiva-mcp"
    packaged.mkdir(parents=True)
    fallback.mkdir(parents=True)
    (packaged / "SKILL.md").write_text("packaged", encoding="utf-8")
    (fallback / "SKILL.md").write_text("repo", encoding="utf-8")

    assert trova_sorgente(directory_pacchetto=pacchetto, radice_repository=repo) == packaged
    (packaged / "SKILL.md").unlink()
    assert trova_sorgente(directory_pacchetto=pacchetto, radice_repository=repo) == fallback


def test_versione_legge_solo_metadata_version(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        "---\nversion: '9.9.9'\nmetadata:\n  version: \"1.2.3\"\n---\ntesto\n",
        encoding="utf-8",
    )
    assert versione_skill(skill_file) == "1.2.3"


def test_installa_all_copia_directory_complete(sorgente: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    progetto = tmp_path / "progetto"
    for radice in (home / ".claude", home / ".codex", home / ".config/opencode", home / ".pi"):
        radice.mkdir(parents=True)
    esiti = installa(
        ClientSkill.TUTTI,
        sorgente=sorgente,
        home=home,
        directory_progetto=progetto,
    )

    assert len(esiti) == 4
    assert all(esito.azione == "installata" for esito in esiti)
    assert all((esito.percorso / "references/strumenti.md").is_file() for esito in esiti)
    stati = elenco_stati(LivelloSkill.UTENTE, home=home, directory_progetto=progetto)
    assert {stato.stato for stato in stati} == {"aggiornata"}


def test_installa_all_salta_e_riporta_client_non_rilevati(
    sorgente: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(destinazioni_module.shutil, "which", lambda _nome: None)

    esiti = installa(ClientSkill.TUTTI, sorgente=sorgente, home=home)
    per_client = {esito.client: esito.azione for esito in esiti}

    assert per_client[ClientSkill.CLAUDE_CODE] == "installata"
    assert per_client[ClientSkill.CODEX] == "non rilevato"
    assert per_client[ClientSkill.OPENCODE] == "non rilevato"
    assert per_client[ClientSkill.PI] == "non rilevato"
    assert not (home / ".agents/skills/normattiva-mcp").exists()


def test_reinstallazione_sostituisce_tutto_e_non_lascia_backup(
    sorgente: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    installa(ClientSkill.CLAUDE_CODE, sorgente=sorgente, home=home)
    target = home / ".claude/skills/normattiva-mcp"
    (target / "vecchio.txt").write_text("da rimuovere", encoding="utf-8")

    esito = installa(ClientSkill.CLAUDE_CODE, sorgente=sorgente, home=home)[0]

    assert esito.azione == "reinstallata"
    assert not (target / "vecchio.txt").exists()
    assert not list(target.parent.glob(".normattiva-mcp-*-*"))


def test_installazione_ripristina_la_versione_precedente_se_il_commit_fallisce(
    sorgente: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    target = home / ".claude/skills/normattiva-mcp"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("versione precedente", encoding="utf-8")
    replace_originale = Path.replace

    def replace_con_guasto(percorso: Path, destinazione: Path) -> Path:
        if percorso.name == "normattiva-mcp" and "staging" in percorso.parent.name:
            raise OSError("guasto simulato")
        return replace_originale(percorso, destinazione)

    monkeypatch.setattr(Path, "replace", replace_con_guasto)
    with pytest.raises(ErroreSkill, match="guasto simulato"):
        installa(ClientSkill.CLAUDE_CODE, sorgente=sorgente, home=home)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "versione precedente"
    assert not list(target.parent.glob(".normattiva-mcp-*-*"))


def test_aggiorna_solo_installazioni_esistenti(sorgente: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = home / ".agents/skills/normattiva-mcp"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(
        "---\nmetadata:\n  version: '0.0.1'\n---\nvecchia\n", encoding="utf-8"
    )

    esiti = aggiorna(ClientSkill.TUTTI, sorgente=sorgente, home=home)
    per_client = {esito.client: esito.azione for esito in esiti}

    assert per_client[ClientSkill.CODEX] == "aggiornata"
    assert per_client[ClientSkill.CLAUDE_CODE] == "non installata"
    assert not (home / ".claude/skills/normattiva-mcp").exists()
    assert versione_skill(target) == __version__


def test_disinstalla_solo_livello_richiesto(sorgente: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    progetto = tmp_path / "progetto"
    installa(ClientSkill.PI, LivelloSkill.UTENTE, sorgente=sorgente, home=home)
    installa(
        ClientSkill.PI,
        LivelloSkill.PROGETTO,
        sorgente=sorgente,
        home=home,
        directory_progetto=progetto,
    )

    esito = disinstalla(ClientSkill.PI, home=home, directory_progetto=progetto)[0]

    assert esito.azione == "rimossa"
    assert not (home / ".pi/agent/skills/normattiva-mcp").exists()
    assert (progetto / ".pi/skills/normattiva-mcp").exists()


def test_mostra_restituisce_il_file_integrale(sorgente: Path) -> None:
    assert mostra(sorgente=sorgente) == (sorgente / "SKILL.md").read_text(encoding="utf-8")


def test_cli_skill_project_non_usa_home_rete_o_client(
    sorgente: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progetto = tmp_path / "progetto"
    progetto.mkdir()
    monkeypatch.setattr(skill_module, "trova_sorgente", lambda: sorgente)
    monkeypatch.setattr(destinazioni_module, "_cwd", lambda: progetto)
    monkeypatch.setattr(
        "normattiva_mcp.cli._nuovo_client",
        lambda: pytest.fail("la gestione skill non deve costruire ClienteNormattiva"),
    )

    risultato = runner.invoke(app, ["skill", "install", "opencode", "--level", "project"])

    assert risultato.exit_code == 0, risultato.output
    assert (progetto / ".opencode/skills/normattiva-mcp/SKILL.md").is_file()
    assert "opencode" in risultato.stdout


def test_cli_show_usa_la_sorgente_locale(sorgente: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_module, "trova_sorgente", lambda: sorgente)
    risultato = runner.invoke(app, ["skill", "show"])
    assert risultato.exit_code == 0
    assert "# Normattiva MCP" in risultato.stdout


def test_cli_install_all_riporta_i_client_non_rilevati(
    sorgente: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(skill_module, "trova_sorgente", lambda: sorgente)
    monkeypatch.setattr(destinazioni_module, "_home", lambda: home)
    monkeypatch.setattr(destinazioni_module.shutil, "which", lambda _nome: None)

    risultato = runner.invoke(app, ["skill", "install", "all"])

    assert risultato.exit_code == 0, risultato.output
    assert "claude-code" in risultato.stdout
    assert risultato.stdout.count("client non rilevato") == 3


def test_cli_rifiuta_client_e_livello_sconosciuti() -> None:
    assert runner.invoke(app, ["skill", "install", "cursor"]).exit_code == 2
    assert (
        runner.invoke(app, ["skill", "install", "claude-code", "--level", "globale"]).exit_code == 2
    )


def test_sorgente_con_versione_diversa_viene_rifiutata(sorgente: Path, tmp_path: Path) -> None:
    testo = (sorgente / "SKILL.md").read_text(encoding="utf-8")
    (sorgente / "SKILL.md").write_text(testo.replace(__version__, "99.0.0"), encoding="utf-8")
    with pytest.raises(ErroreSkill, match="non coincide"):
        installa(ClientSkill.CLAUDE_CODE, sorgente=sorgente, home=tmp_path / "home")


def test_uninstall_rimuove_anche_un_target_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = home / ".claude/skills/normattiva-mcp"
    target.parent.mkdir(parents=True)
    target.write_text("installazione corrotta", encoding="utf-8")

    esito = disinstalla(ClientSkill.CLAUDE_CODE, home=home)[0]

    assert esito.azione == "rimossa"
    assert not target.exists()


def test_symlink_install_e_uninstall_non_toccano_il_target_esterno(
    sorgente: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    esterna = tmp_path / "esterna"
    esterna.mkdir()
    sentinella = esterna / "sentinella.txt"
    sentinella.write_text("intatta", encoding="utf-8")
    target = home / ".claude/skills/normattiva-mcp"
    target.parent.mkdir(parents=True)
    target.symlink_to(esterna, target_is_directory=True)

    installa(ClientSkill.CLAUDE_CODE, sorgente=sorgente, home=home)
    assert not target.is_symlink()
    assert sentinella.read_text(encoding="utf-8") == "intatta"

    shutil.rmtree(target)
    target.symlink_to(esterna, target_is_directory=True)
    disinstalla(ClientSkill.CLAUDE_CODE, home=home)
    assert not target.exists()
    assert sentinella.read_text(encoding="utf-8") == "intatta"


def test_le_due_copie_distribuite_sono_identiche_byte_per_byte() -> None:
    radice = Path(__file__).resolve().parents[1]
    repo = radice / "skills/normattiva-mcp"
    packaged = radice / "src/normattiva_mcp/data/skill/normattiva-mcp"

    file_repo = {
        path.relative_to(repo): path.read_bytes() for path in repo.rglob("*") if path.is_file()
    }
    file_packaged = {
        path.relative_to(packaged): path.read_bytes()
        for path in packaged.rglob("*")
        if path.is_file()
    }
    assert file_repo == file_packaged


def test_versione_skill_distribuita_coincide_con_pacchetto() -> None:
    radice = Path(__file__).resolve().parents[1]
    assert versione_skill(radice / "skills/normattiva-mcp") == __version__


def test_installazione_elimina_risorse_obsolete(sorgente: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = home / ".config/opencode/skills/normattiva-mcp"
    shutil.copytree(sorgente, target)
    (target / "references/obsoleta.md").write_text("vecchia", encoding="utf-8")

    installa(ClientSkill.OPENCODE, sorgente=sorgente, home=home)

    assert not (target / "references/obsoleta.md").exists()
