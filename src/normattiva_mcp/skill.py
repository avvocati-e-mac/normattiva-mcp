"""Gestione locale della skill Agent Skills distribuita con il progetto.

Questo modulo non costruisce il client HTTP: installazione, aggiornamento e
rimozione operano soltanto sul filesystem locale. La sostituzione di una skill
usa una directory di staging e conserva temporaneamente la versione precedente
per poterla ripristinare se il passaggio finale fallisce.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path

from normattiva_mcp import __version__
from normattiva_mcp.skill_destinazioni import (
    NOME_SKILL,
    ClientSkill,
    DestinazioneSkill,
    ErroreSkill,
    EsitoSkill,
    LivelloSkill,
    StatoSkill,
    client_rilevato,
    destinazioni,
    seleziona_destinazioni,
)


def trova_sorgente(
    *, directory_pacchetto: Path | None = None, radice_repository: Path | None = None
) -> Path:
    """Trova prima la copia packaged, poi quella del checkout modificabile."""
    directory_pacchetto = directory_pacchetto or Path(__file__).resolve().parent
    radice_repository = radice_repository or Path(__file__).resolve().parents[2]
    candidate = (
        directory_pacchetto / "data" / "skill" / NOME_SKILL,
        radice_repository / "skills" / NOME_SKILL,
    )
    for percorso in candidate:
        if (percorso / "SKILL.md").is_file():
            return percorso
    raise ErroreSkill(
        "La skill integrata non è disponibile nel pacchetto né nel repository. "
        "Reinstalla normattiva-mcp e riprova."
    )


def versione_skill(percorso: Path) -> str | None:
    """Legge esclusivamente ``metadata.version`` dal frontmatter YAML.

    Non serve un parser YAML completo: il formato distribuito contiene una
    mappa ``metadata`` semplice. Una ``version`` top-level non viene accettata.
    """
    # Non leggere mai attraverso un link collocato al posto della directory
    # della skill: potrebbe puntare fuori dall'albero che l'utente ha scelto.
    if percorso.is_symlink():
        return None
    skill_file = percorso / "SKILL.md" if percorso.is_dir() else percorso
    try:
        righe = skill_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    if not righe or righe[0].strip() != "---":
        return None

    in_metadata = False
    indent_metadata = -1
    for riga in righe[1:]:
        if riga.strip() == "---":
            break
        if not riga.strip() or riga.lstrip().startswith("#"):
            continue
        indent = len(riga) - len(riga.lstrip())
        if in_metadata and indent <= indent_metadata:
            in_metadata = False
        if not in_metadata and re.fullmatch(r"\s*metadata\s*:\s*", riga):
            in_metadata = True
            indent_metadata = indent
            continue
        if in_metadata:
            match = re.fullmatch(r"\s*version\s*:\s*(.*?)\s*", riga)
            if match:
                valore = match.group(1).strip().strip("\"'")
                return valore or None
    return None


def _verifica_sorgente(sorgente: Path) -> None:
    if sorgente.is_symlink() or not sorgente.is_dir():
        raise ErroreSkill(f"Sorgente della skill non valida: {sorgente}")
    if any(percorso.is_symlink() for percorso in sorgente.rglob("*")):
        raise ErroreSkill("La sorgente della skill contiene collegamenti simbolici non ammessi.")
    if not (sorgente / "SKILL.md").is_file():
        raise ErroreSkill(f"Sorgente della skill non valida: {sorgente}")
    versione = versione_skill(sorgente)
    if versione != __version__:
        trovata = versione or "assente"
        raise ErroreSkill(
            "La versione metadata.version della skill integrata "
            f"({trovata}) non coincide con normattiva-mcp {__version__}."
        )


def _esiste(path: Path) -> bool:
    return os.path.lexists(path)


def _rimuovi(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _sostituisci_atomico(sorgente: Path, directory_destinazione: Path) -> None:
    """Copia una directory con staging, backup e rollback best effort."""
    directory_destinazione.mkdir(parents=True, exist_ok=True)
    target = directory_destinazione / NOME_SKILL
    staging_root: Path | None = None
    backup: Path | None = None
    precedente_spostata = False
    try:
        staging_root = Path(
            tempfile.mkdtemp(prefix=f".{NOME_SKILL}-staging-", dir=directory_destinazione)
        )
        staged = staging_root / NOME_SKILL
        shutil.copytree(sorgente, staged, symlinks=True)

        if _esiste(target):
            backup = directory_destinazione / f".{NOME_SKILL}-backup-{uuid.uuid4().hex}"
            target.replace(backup)
            precedente_spostata = True
        staged.replace(target)
    except (OSError, UnicodeError, ValueError) as errore:
        if precedente_spostata and backup is not None and _esiste(backup):
            try:
                if _esiste(target):
                    _rimuovi(target)
                backup.replace(target)
            except OSError as errore_ripristino:
                raise ErroreSkill(
                    f"Installazione fallita ({errore}); anche il ripristino della "
                    f"versione precedente è fallito: {errore_ripristino}. "
                    f"Controlla il backup {backup}."
                ) from errore_ripristino
        raise ErroreSkill(f"Installazione della skill fallita: {errore}") from errore
    finally:
        if staging_root is not None and _esiste(staging_root):
            with suppress(OSError):
                _rimuovi(staging_root)

    if backup is not None and _esiste(backup):
        # L'installazione è completa: un backup che non si riesca a
        # cancellare resta recuperabile e non rende falso il commit riuscito.
        with suppress(OSError):
            _rimuovi(backup)


def installa(
    client: ClientSkill,
    livello: LivelloSkill = LivelloSkill.UTENTE,
    *,
    sorgente: Path | None = None,
    home: Path | None = None,
    directory_progetto: Path | None = None,
) -> tuple[EsitoSkill, ...]:
    sorgente = sorgente or trova_sorgente()
    _verifica_sorgente(sorgente)
    esiti: list[EsitoSkill] = []
    for destinazione in seleziona_destinazioni(
        client, home=home, directory_progetto=directory_progetto
    ):
        directory = destinazione.directory(livello)
        if client is ClientSkill.TUTTI and not client_rilevato(destinazione):
            esiti.append(
                EsitoSkill(
                    destinazione.client,
                    livello,
                    directory / NOME_SKILL,
                    "non rilevato",
                )
            )
            continue
        precedente = versione_skill(directory / NOME_SKILL)
        _sostituisci_atomico(sorgente, directory)
        esiti.append(
            EsitoSkill(
                destinazione.client,
                livello,
                directory / NOME_SKILL,
                "installata" if precedente is None else "reinstallata",
                precedente,
            )
        )
    return tuple(esiti)


def disinstalla(
    client: ClientSkill,
    livello: LivelloSkill = LivelloSkill.UTENTE,
    *,
    home: Path | None = None,
    directory_progetto: Path | None = None,
) -> tuple[EsitoSkill, ...]:
    esiti: list[EsitoSkill] = []
    for destinazione in seleziona_destinazioni(
        client, home=home, directory_progetto=directory_progetto
    ):
        target = destinazione.directory(livello) / NOME_SKILL
        precedente = versione_skill(target)
        if not _esiste(target):
            esiti.append(EsitoSkill(destinazione.client, livello, target, "non installata"))
            continue
        backup = target.parent / f".{NOME_SKILL}-rimozione-{uuid.uuid4().hex}"
        try:
            target.replace(backup)
            _rimuovi(backup)
        except OSError as errore:
            if _esiste(backup) and not _esiste(target):
                try:
                    backup.replace(target)
                except OSError as errore_ripristino:
                    raise ErroreSkill(
                        f"Rimozione fallita ({errore}); ripristino fallito: "
                        f"{errore_ripristino}. Controlla {backup}."
                    ) from errore_ripristino
            raise ErroreSkill(f"Rimozione della skill fallita: {errore}") from errore
        esiti.append(EsitoSkill(destinazione.client, livello, target, "rimossa", precedente))
    return tuple(esiti)


def aggiorna(
    client: ClientSkill = ClientSkill.TUTTI,
    livello: LivelloSkill = LivelloSkill.UTENTE,
    *,
    sorgente: Path | None = None,
    home: Path | None = None,
    directory_progetto: Path | None = None,
) -> tuple[EsitoSkill, ...]:
    """Aggiorna solo installazioni già presenti e con versione diversa."""
    sorgente = sorgente or trova_sorgente()
    _verifica_sorgente(sorgente)
    esiti: list[EsitoSkill] = []
    for destinazione in seleziona_destinazioni(
        client, home=home, directory_progetto=directory_progetto
    ):
        target = destinazione.directory(livello) / NOME_SKILL
        precedente = versione_skill(target)
        if not _esiste(target):
            esiti.append(EsitoSkill(destinazione.client, livello, target, "non installata"))
        elif precedente == __version__:
            esiti.append(
                EsitoSkill(destinazione.client, livello, target, "già aggiornata", precedente)
            )
        else:
            _sostituisci_atomico(sorgente, target.parent)
            esiti.append(EsitoSkill(destinazione.client, livello, target, "aggiornata", precedente))
    return tuple(esiti)


def elenco_stati(
    livello: LivelloSkill | None = None,
    *,
    home: Path | None = None,
    directory_progetto: Path | None = None,
) -> tuple[StatoSkill, ...]:
    livelli = (livello,) if livello is not None else tuple(LivelloSkill)
    risultati: list[StatoSkill] = []
    for destinazione in destinazioni(home=home, directory_progetto=directory_progetto):
        for voce_livello in livelli:
            percorso = destinazione.directory(voce_livello) / NOME_SKILL
            risultati.append(
                StatoSkill(
                    destinazione.client,
                    voce_livello,
                    percorso,
                    versione_skill(percorso),
                    _esiste(percorso),
                    percorso.is_symlink(),
                )
            )
    return tuple(risultati)


def mostra(*, sorgente: Path | None = None) -> str:
    sorgente = sorgente or trova_sorgente()
    _verifica_sorgente(sorgente)
    try:
        return (sorgente / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as errore:
        raise ErroreSkill(f"Impossibile leggere la skill integrata: {errore}") from errore


__all__ = [
    "ClientSkill",
    "DestinazioneSkill",
    "ErroreSkill",
    "EsitoSkill",
    "LivelloSkill",
    "NOME_SKILL",
    "StatoSkill",
    "aggiorna",
    "client_rilevato",
    "destinazioni",
    "disinstalla",
    "elenco_stati",
    "installa",
    "mostra",
    "seleziona_destinazioni",
    "trova_sorgente",
    "versione_skill",
]
