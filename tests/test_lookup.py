"""Test della lookup alias→URN — nessuna rete."""

from datetime import date

import pytest

from normattiva_mcp.fonti import Fonte, FonteNonDisponibile, TabellaFonti
from normattiva_mcp.lookup import (
    FonteNonDisponibileErrore,
    RiferimentoSconosciuto,
    normalizza_alias,
    risolvi_alias,
)
from normattiva_mcp.urn import Articolo, TipoAtto


class TestNormalizzazione:
    def test_minuscolo(self) -> None:
        assert normalizza_alias("CODICE CIVILE") == "codice civile"

    def test_diacritici_rimossi(self) -> None:
        assert normalizza_alias("perché così") == "perche cosi"

    def test_punteggiatura_diventa_spazio(self) -> None:
        assert normalizza_alias("c.c.") == "c c"
        assert normalizza_alias("l.fall.") == "l fall"

    def test_spazi_multipli_collassati(self) -> None:
        assert normalizza_alias("codice   civile") == "codice civile"

    def test_forme_equivalenti(self) -> None:
        assert normalizza_alias("Codice Civile") == normalizza_alias("codice civile")


class TestRisoluzioneAlias:
    def test_alias_esatto_codice_civile(self) -> None:
        risultato = risolvi_alias("codice civile", articolo=Articolo(numero=2043))
        assert risultato.urn.stringa == "urn:nir:stato:regio.decreto:1942-03-16;262:2~art2043"
        assert risultato.fonte is not None
        assert risultato.fonte.nome_canonico == "Codice Civile"

    def test_alias_case_insensitive_e_con_punteggiatura(self) -> None:
        risultato = risolvi_alias("C.C.", articolo=Articolo(numero=2043))
        assert risultato.fonte is not None
        assert risultato.fonte.nome_canonico == "Codice Civile"

    def test_articolo_default_e_uno(self) -> None:
        risultato = risolvi_alias("codice civile")
        assert risultato.urn.articolo.numero == 1

    def test_fonte_non_disponibile_solleva_errore_dedicato(self) -> None:
        with pytest.raises(FonteNonDisponibileErrore, match="GDPR"):
            risolvi_alias("gdpr")

    def test_alias_sconosciuto_solleva_errore_dedicato(self) -> None:
        with pytest.raises(RiferimentoSconosciuto):
            risolvi_alias("una legge che non esiste da nessuna parte")


class TestAvvertenze:
    def test_art1_e_preambolo_produce_avvertenza(self) -> None:
        risultato = risolvi_alias("d.lgs. 231/2001", articolo=Articolo(numero=1))
        assert any("preambolo" in a for a in risultato.avvertenze)

    def test_articolo_diverso_da_uno_non_produce_avvertenza_preambolo(self) -> None:
        risultato = risolvi_alias("d.lgs. 231/2001", articolo=Articolo(numero=5))
        assert not any("preambolo" in a for a in risultato.avvertenze)

    def test_nessuna_avvertenza_per_fonte_vigente_e_articolo_normale(self) -> None:
        risultato = risolvi_alias("codice civile", articolo=Articolo(numero=2043))
        assert risultato.avvertenze == ()


class TestGrafieEstese:
    """docs/MISURE.md e il censimento delle grafie: le forme estese
    ufficiali sono quelle con cui la ricerca umana nomina davvero una
    norma. Il rimatch NON deve mai perdere l'allegato di un codice
    storico — per questo passa sempre dalla tabella verificata, mai da
    una costruzione diretta.
    """

    def test_grafia_estesa_con_data_rimatcha_la_tabella_con_allegato(self) -> None:
        risultato = risolvi_alias("regio decreto 16 marzo 1942 n 267", articolo=Articolo(numero=1))
        assert risultato.fonte is not None
        assert risultato.fonte.nome_canonico == "Legge Fallimentare"
        assert risultato.urn.allegato == 1

    def test_grafia_senza_data_rimatcha_la_tabella(self) -> None:
        risultato = risolvi_alias("decreto legislativo n 231 del 2001", articolo=Articolo(numero=1))
        assert risultato.fonte is not None
        assert (
            risultato.fonte.nome_canonico
            == "D.Lgs. 231/2001 (responsabilità amministrativa degli enti)"
        )

    def test_grafia_estesa_malformata_continua_a_rifiutare(self) -> None:
        with pytest.raises(RiferimentoSconosciuto):
            risolvi_alias("regio decreto marzo 1942 n 267")  # manca il giorno

    def test_grafia_senza_data_malformata_continua_a_rifiutare(self) -> None:
        with pytest.raises(RiferimentoSconosciuto):
            risolvi_alias("decreto legislativo 231 del 2001")  # manca la "n"

    def test_ambiguita_codice_civile_preleggi_rifiutata(self) -> None:
        """r.d. 262/1942 è sia il Codice Civile (:2) sia le Preleggi (:1):
        stesso tipo, numero e anno. Un'ambiguità sintattica si rifiuta,
        non si risolve a caso — mai la fonte sbagliata."""
        with pytest.raises(RiferimentoSconosciuto):
            risolvi_alias("regio decreto 16 marzo 1942 n 262")


class TestAmbiguitaEsplicita:
    """Verifica diretta, senza passare dalla tabella reale, che due fonti
    con lo stesso (tipo, numero, anno) blocchino il rimatch — indipendente
    da quali fonti esistano oggi in data/fonti.json."""

    def _tabella_con_ambiguita(self) -> TabellaFonti:
        comune = {
            "tipo": TipoAtto.REGIO_DECRETO,
            "data": date(1942, 3, 16),
            "numero": 262,
            "articolo_di_controllo": "1",
            "art1_e_preambolo": False,
            "stato": "vigente",
            "nota_stato": None,
            "provenienza": "test",
        }
        return TabellaFonti(
            verificate=(
                Fonte(nome_canonico="Fonte A", alias=("fonte a",), allegato=1, **comune),
                Fonte(nome_canonico="Fonte B", alias=("fonte b",), allegato=2, **comune),
            ),
            non_disponibili=(),
        )

    def test_due_fonti_stesso_tipo_numero_anno_rifiutano_il_rimatch(self) -> None:
        tabella = self._tabella_con_ambiguita()
        with pytest.raises(RiferimentoSconosciuto):
            risolvi_alias("regio decreto 16 marzo 1942 n 262", tabella=tabella)

    def test_alias_esatto_funziona_comunque_nonostante_l_ambiguita(self) -> None:
        """L'ambiguità riguarda SOLO il rimatch da grafia estesa: un alias
        esplicito in tabella non è mai ambiguo."""
        tabella = self._tabella_con_ambiguita()
        risultato = risolvi_alias("fonte a", tabella=tabella)
        assert risultato.urn.allegato == 1


class TestFonteNonDisponibileDedicata:
    def test_tabella_minima_fonte_non_disponibile(self) -> None:
        tabella = TabellaFonti(
            verificate=(),
            non_disponibili=(
                FonteNonDisponibile(
                    nome_canonico="X", alias=("x", "x esteso"), nota="non è su Normattiva"
                ),
            ),
        )
        with pytest.raises(FonteNonDisponibileErrore, match="non è su Normattiva"):
            risolvi_alias("x esteso", tabella=tabella)
