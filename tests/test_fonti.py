"""Test della tabella delle fonti — nessuna rete.

Il test più importante di questo file è `test_urn_congelati_contro_fixture`:
confronta l'URN costruito da ogni riga della tabella contro un file atteso
versionato (`tests/fixtures/urn-attesi.txt`). Include come regressione i
due errori storici già scoperti nella skill esistente: se la data della
Legge Fallimentare o l'allegato del Codice della Navigazione cambiassero
per errore, questo test lo scoprirebbe subito — senza dover ricordare a
memoria quei due casi.
"""

from pathlib import Path

import pytest

from normattiva_mcp.fonti import carica_tabella

_FIXTURE_URN_ATTESI = Path(__file__).parent / "fixtures" / "urn-attesi.txt"


def _leggi_urn_attesi() -> dict[str, str]:
    attesi: dict[str, str] = {}
    for riga in _FIXTURE_URN_ATTESI.read_text(encoding="utf-8").splitlines():
        if not riga.strip():
            continue
        nome, urn = riga.split("|", maxsplit=1)
        attesi[nome] = urn
    return attesi


class TestCaricamento:
    def test_47_fonti_verificate(self) -> None:
        tabella = carica_tabella()
        assert len(tabella.verificate) == 47

    def test_4_fonti_non_disponibili(self) -> None:
        tabella = carica_tabella()
        assert len(tabella.non_disponibili) == 4

    def test_ogni_fonte_ha_provenienza_non_vuota(self) -> None:
        """La regola: un dato senza prova non entra in questa tabella."""
        tabella = carica_tabella()
        for fonte in tabella.verificate:
            assert fonte.provenienza.strip(), f"{fonte.nome_canonico} senza provenienza"

    def test_ogni_articolo_di_controllo_e_numerico(self) -> None:
        """Deve restare semplice da verificare: nessuna estensione."""
        tabella = carica_tabella()
        for fonte in tabella.verificate:
            assert fonte.articolo_di_controllo.isdigit(), (
                f"{fonte.nome_canonico}: articolo_di_controllo non numerico "
                f"({fonte.articolo_di_controllo!r})"
            )

    def test_nessun_articolo_di_controllo_e_l_articolo_1_quando_e_preambolo(self) -> None:
        """Una fonte con art1_e_preambolo=True non può avere l'art. 1 come
        controllo: proverebbe solo che l'atto esiste, non che l'articolo
        di controllo restituisce testo vero (regressione 29/08/2026: due
        righe del dataset originale avevano proprio questo difetto)."""
        tabella = carica_tabella()
        for fonte in tabella.verificate:
            if fonte.art1_e_preambolo:
                assert fonte.articolo_di_controllo != "1", (
                    f"{fonte.nome_canonico}: articolo di controllo è l'art. 1, "
                    "ma restituisce il preambolo — il controllo non prova nulla"
                )


class TestUrnCongelati:
    """Test di regressione: l'URN costruito oggi deve coincidere con quello
    verificato in passato, riga per riga."""

    def test_urn_congelati_contro_fixture(self) -> None:
        attesi = _leggi_urn_attesi()
        tabella = carica_tabella()
        nomi_tabella = {f.nome_canonico for f in tabella.verificate}
        assert nomi_tabella == set(attesi), "la tabella e la fixture non hanno le stesse fonti"

        for fonte in tabella.verificate:
            urn_costruito = fonte.urn_di_controllo().stringa
            urn_atteso = attesi[fonte.nome_canonico]
            assert urn_costruito == urn_atteso, (
                f"{fonte.nome_canonico}: atteso {urn_atteso!r}, costruito {urn_costruito!r}"
            )

    def test_regressione_legge_fallimentare_data_corretta(self) -> None:
        """La skill esistente aveva 1942-01-16; la data vera è 1942-03-16
        (404 con la data sbagliata, ma il permalink funzionava lo stesso —
        docs/MISURE.md, nota nella provenienza di questa fonte)."""
        tabella = carica_tabella()
        fonte = tabella.trova("legge fallimentare")
        assert fonte is not None
        assert fonte.data.isoformat() == "1942-03-16"
        assert fonte.allegato == 1

    def test_regressione_codice_navigazione_ha_allegato(self) -> None:
        """La skill esistente non aveva l'allegato :1 per questo codice."""
        tabella = carica_tabella()
        fonte = tabella.trova("codice della navigazione")
        assert fonte is not None
        assert fonte.allegato == 1


class TestRicerca:
    def test_trova_per_nome_canonico(self) -> None:
        tabella = carica_tabella()
        fonte = tabella.trova("Codice Civile")
        assert fonte is not None
        assert fonte.nome_canonico == "Codice Civile"

    def test_trova_per_alias_case_insensitive(self) -> None:
        tabella = carica_tabella()
        fonte = tabella.trova("L.FALL.")
        assert fonte is not None
        assert fonte.nome_canonico == "Legge Fallimentare"

    def test_trova_fonte_non_disponibile(self) -> None:
        tabella = carica_tabella()
        risultato = tabella.trova("gdpr")
        from normattiva_mcp.fonti import FonteNonDisponibile

        assert isinstance(risultato, FonteNonDisponibile)
        assert "GDPR" in risultato.nome_canonico

    def test_testo_sconosciuto_restituisce_none(self) -> None:
        tabella = carica_tabella()
        assert tabella.trova("una norma che non esiste da nessuna parte") is None

    def test_testo_vuoto_restituisce_none(self) -> None:
        tabella = carica_tabella()
        assert tabella.trova("   ") is None


class TestAmbiguitaNonRisolte:
    """docs/IDEE-SCARTATE.md: r.d. 262/1942 è sia il Codice Civile (:2) sia
    le Preleggi (:1). Verifichiamo solo che siano due righe distinte con
    alias distinti — un alias condiviso fra le due sarebbe l'ambiguità
    silenziosa che il progetto non deve introdurre."""

    def test_codice_civile_e_preleggi_hanno_alias_distinti(self) -> None:
        tabella = carica_tabella()
        civile = tabella.trova("codice civile")
        preleggi = tabella.trova("preleggi")
        assert civile is not None
        assert preleggi is not None
        assert civile.nome_canonico != preleggi.nome_canonico
        alias_civile = {a.lower() for a in civile.alias}
        alias_preleggi = {a.lower() for a in preleggi.alias}
        comuni = alias_civile & alias_preleggi
        assert not comuni, f"alias condivisi fra Codice Civile e Preleggi: {comuni}"


@pytest.mark.parametrize(
    "nome_atteso",
    [
        "Legge Fallimentare",
        "Codice della Navigazione",
        "Codice Civile",
        "Codice di Procedura Civile",
        "Codice Penale",
        "Statuto dei Lavoratori",
    ],
)
def test_fonti_chiave_del_lavoro_forense_presenti(nome_atteso: str) -> None:
    tabella = carica_tabella()
    nomi = {f.nome_canonico for f in tabella.verificate}
    assert nome_atteso in nomi
