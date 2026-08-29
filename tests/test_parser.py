"""Test del parser contro le catture HTTP reali.

Tutte le fixture in tests/fixtures/risposte/reale-*.json sono catturate
davvero da api.normattiva.it il 7 agosto 2026 (vedi
tests/fixtures/risposte/LEGGIMI.md nel progetto di ricerca originale, non
riportato qui — la nota di provenienza sta nel commento di ogni test).
Nessun file "ricostruito a mano" è stato portato in questo progetto: solo
le catture vere, perché un test verde su un JSON scritto a mano proverebbe
il parser contro se stesso, non contro Normattiva.
"""

import json
from pathlib import Path

import pytest

from normattiva_mcp.dto import nodo_utile
from normattiva_mcp.parser import (
    Abrogato,
    CorpoArticolo,
    HeadingDiscordante,
    Preambolo,
    _sembra_preambolo,
    analizza,
)
from normattiva_mcp.urn import Articolo

_FIXTURE = Path(__file__).parent / "fixtures" / "risposte"


def _carica(nome_file: str) -> dict:
    return json.loads((_FIXTURE / nome_file).read_text(encoding="utf-8"))


class TestArticoloStandard:
    """Cattura reale: art. 18 legge 300/1970, con heading `article-num-akn`
    e 4 blocchi di aggiornamento veri (il 23% del testo, docs/MISURE.md)."""

    def test_articolo_estratto_con_heading_e_aggiornamenti_separati(self) -> None:
        corpo = _carica("reale-atto-statuto-18.json")
        nodo = nodo_utile(corpo)
        assert nodo is not None
        esito = analizza(nodo.articolo_html, richiesto=Articolo(numero=18))
        assert isinstance(esito, CorpoArticolo)
        assert esito.heading == "Art. 18"
        assert "Tutela del lavoratore" not in esito.heading  # la rubrica non è nell'heading
        assert len(esito.aggiornamenti) == 4  # AGGIORNAMENTO (9), (23), (28), (30)
        # Il testo dell'articolo non contiene i blocchi di aggiornamento
        assert "Corte Costituzionale" not in esito.testo


class TestCodiciConAllegato:
    """Catture reali: art. 2043 c.c. e art. 542 c.c. — nei codici approvati
    per allegato la classe `article-num-akn` NON compare, il testo è
    dentro `attachment-just-text` e comincia con "Art. N."."""

    def test_articolo_2043_senza_classe_heading(self) -> None:
        corpo = _carica("reale-atto-cc-2043.json")
        nodo = nodo_utile(corpo)
        assert nodo is not None
        esito = analizza(nodo.articolo_html, richiesto=Articolo(numero=2043))
        assert isinstance(esito, CorpoArticolo)
        assert esito.heading == "Art. 2043"
        assert "Risarcimento per fatto illecito" in esito.testo

    def test_rubrica_non_parentetica_non_diventa_estensione(self) -> None:
        """Il bug storico: "Art. 542. Concorso di coniuge e figli" (rubrica
        SENZA parentesi) veniva letto come estensione "concorsodiconiugeefiglis",
        e l'articolo giusto veniva respinto per heading discordante."""
        corpo = _carica("reale-atto-cc-542-rubrica-non-parentetica.json")
        nodo = nodo_utile(corpo)
        assert nodo is not None
        esito = analizza(nodo.articolo_html, richiesto=Articolo(numero=542))
        assert isinstance(esito, CorpoArticolo)
        assert esito.heading == "Art. 542"

    def test_navigazione_con_allegato(self) -> None:
        corpo = _carica("reale-atto-navigazione-422.json")
        nodo = nodo_utile(corpo)
        assert nodo is not None
        esito = analizza(nodo.articolo_html, richiesto=Articolo(numero=422))
        assert isinstance(esito, CorpoArticolo)
        assert "Responsabilità del vettore" in esito.testo


class TestFormaLista:
    """Cattura reale: art. 42 TUEL, `data.atto = null` e `data.lista` con
    2 elementi. `nodo_utile` deve risolvere al primo elemento."""

    def test_forma_lista_risolta_al_primo_elemento(self) -> None:
        corpo = _carica("reale-lista-tuel-42.json")
        assert corpo["data"]["atto"] is None
        assert len(corpo["data"]["lista"]) == 2
        nodo = nodo_utile(corpo)
        assert nodo is not None
        esito = analizza(nodo.articolo_html, richiesto=Articolo(numero=42))
        assert isinstance(esito, CorpoArticolo)
        assert esito.heading == "Art. 42"
        assert "organo di indirizzo" in esito.testo


class TestAbrogato:
    """Cattura reale: art. 51 TUIR, "PROVVEDIMENTO ABROGATO DAL D.LGS. 19
    GIUGNO 2026, N. 117"."""

    def test_abrogato_riconosciuto_come_tale_non_come_vuoto(self) -> None:
        corpo = _carica("reale-abrogato-tuir-51.json")
        nodo = nodo_utile(corpo)
        assert nodo is not None
        esito = analizza(nodo.articolo_html, richiesto=Articolo(numero=51))
        assert isinstance(esito, Abrogato)
        assert "ABROGATO" in esito.messaggio.upper()

    def test_data_abrogazione_estratta_dal_messaggio(self) -> None:
        corpo = _carica("reale-abrogato-tuir-51.json")
        nodo = nodo_utile(corpo)
        assert nodo is not None
        esito = analizza(nodo.articolo_html, richiesto=Articolo(numero=51))
        assert isinstance(esito, Abrogato)
        assert esito.data_abrogazione is not None
        assert esito.data_abrogazione.isoformat() == "2026-06-19"


class TestPreambolo:
    """Catture reali: `~art1` su d.lgs. 231/2001 e d.lgs. 36/2023.

    Il primo mostra il taglio RIUSCITO: il preambolo precede l'heading
    "Art. 1" vero (che compare al carattere 3.591 dell'HTML), e
    `_dal_heading` lo trova e restituisce il vero articolo — non un
    preambolo. Il secondo è il caso più insidioso, dove il taglio non basta
    perché il preambolo sta SOTTO un heading "Art. 1" a sua volta corretto:
    solo il guardiano del preambolo lo scopre, il controllo di coincidenza
    da solo non basta."""

    def test_preambolo_231_il_taglio_trova_l_articolo_vero_dopo_il_preambolo(self) -> None:
        corpo = _carica("reale-preambolo-231-art1.json")
        nodo = nodo_utile(corpo)
        assert nodo is not None
        esito = analizza(nodo.articolo_html, richiesto=Articolo(numero=1))
        assert isinstance(esito, CorpoArticolo)
        assert esito.heading == "Art. 1"
        # Il preambolo (che precede l'heading nell'HTML) è stato tagliato:
        # l'incipit caratteristico dei "visti" non deve comparire più.
        # (Il testo dell'articolo vero può comunque nominare legittimamente
        # il Presidente della Repubblica in una nota esplicativa — non è
        # quello il segnale del preambolo, lo è la formula "VISTI GLI
        # ARTICOLI... VISTA LA LEGGE" che apre l'atto.)
        assert not esito.testo.upper().startswith("IL PRESIDENTE DELLA REPUBBLICA")
        assert esito.testo.startswith("Art. 1")

    def test_preambolo_36_2023_sotto_heading_art1_corretto(self) -> None:
        """Il caso che il solo confronto sui numeri non vede: l'heading
        dice "Art. 1", ma il contenuto è il preambolo."""
        corpo = _carica("reale-preambolo-36-2023-art1.json")
        nodo = nodo_utile(corpo)
        assert nodo is not None
        esito = analizza(nodo.articolo_html, richiesto=Articolo(numero=1))
        assert isinstance(esito, Preambolo)


class TestGuardianoDelPreambolo:
    """Test unitari sulla soglia delle due formule — non solo contro
    fixture, per fissare il comportamento della soglia stessa."""

    def test_una_sola_formula_non_basta(self) -> None:
        """L'art. 87 Cost. comincia con "Il Presidente della Repubblica è
        il capo dello Stato": una sola formula, non deve essere respinto."""
        testo = (
            "Art. 87 Il Presidente della Repubblica è il capo dello Stato "
            "e rappresenta l'unità nazionale."
        )
        assert _sembra_preambolo(testo, dopo="Art. 87") is False

    def test_due_formule_bastano(self) -> None:
        testo = (
            "Art. 1 IL PRESIDENTE DELLA REPUBBLICA Visti gli articoli 76 e 87 della Costituzione; "
            "Vista la legge 29 settembre 2000, n. 300; Emana il seguente decreto legislativo:"
        )
        assert _sembra_preambolo(testo, dopo="Art. 1") is True

    def test_formule_oltre_la_finestra_non_contano(self) -> None:
        # Una formula di promulgazione citata molto più avanti nel testo
        # non deve far scattare il guardiano: la finestra è solo l'inizio.
        testo = "Art. 1 " + ("x " * 300) + "IL PRESIDENTE DELLA REPUBBLICA VISTI GLI ARTICOLI"
        assert _sembra_preambolo(testo, dopo="Art. 1") is False


class TestHeadingDiscordante:
    def test_heading_diverso_dal_richiesto_solleva_errore(self) -> None:
        corpo = _carica("reale-atto-cc-2043.json")
        nodo = nodo_utile(corpo)
        assert nodo is not None
        with pytest.raises(HeadingDiscordante) as errore:
            analizza(nodo.articolo_html, richiesto=Articolo(numero=2044))
        assert "2044" in str(errore.value)
        assert "2043" in str(errore.value)
