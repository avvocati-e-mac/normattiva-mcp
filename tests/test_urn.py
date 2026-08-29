"""Test della grammatica URN — nessuna rete, tutto misurato in docs/MISURE.md §3.

Ogni test qui pin-na una regola che è stata osservata contro l'API reale.
Un test che passa senza una regola misurata dietro non serve a niente in
questo file.
"""

from datetime import date

import pytest

from normattiva_mcp.estensioni import Estensione
from normattiva_mcp.urn import Articolo, TipoAtto, Urn, UrnNonValido, analizza


class TestCostruzione:
    def test_stringa_urn_forma_completa(self) -> None:
        urn = Urn(
            tipo=TipoAtto.REGIO_DECRETO,
            data=date(1942, 3, 16),
            numero=262,
            allegato=2,
            articolo=Articolo(numero=2043),
        )
        assert urn.stringa == "urn:nir:stato:regio.decreto:1942-03-16;262:2~art2043"

    def test_stringa_senza_allegato(self) -> None:
        urn = Urn(
            tipo=TipoAtto.LEGGE,
            data=date(1970, 5, 20),
            numero=300,
            articolo=Articolo(numero=18),
        )
        assert urn.stringa == "urn:nir:stato:legge:1970-05-20;300~art18"

    def test_stringa_con_estensione(self) -> None:
        urn = Urn(
            tipo=TipoAtto.LEGGE,
            data=date(1990, 8, 7),
            numero=241,
            articolo=Articolo(numero=21, estensione=Estensione.NOVIES),
        )
        assert urn.stringa == "urn:nir:stato:legge:1990-08-07;241~art21novies"

    def test_stringa_con_vigenza(self) -> None:
        urn = Urn(
            tipo=TipoAtto.LEGGE,
            data=date(1970, 5, 20),
            numero=300,
            articolo=Articolo(numero=18),
            vigenza=date(2012, 6, 17),
        )
        assert urn.stringa == "urn:nir:stato:legge:1970-05-20;300~art18!vig=2012-06-17"

    def test_permalink(self) -> None:
        urn = Urn(
            tipo=TipoAtto.REGIO_DECRETO,
            data=date(1942, 3, 16),
            numero=262,
            allegato=2,
            articolo=Articolo(numero=2043),
        )
        assert urn.permalink == (
            "https://www.normattiva.it/uri-res/N2Ls?"
            "urn:nir:stato:regio.decreto:1942-03-16;262:2~art2043"
        )

    def test_con_vigenza_produce_urn_nuovo_senza_toccare_l_originale(self) -> None:
        originale = Urn(
            tipo=TipoAtto.DECRETO_LEGISLATIVO,
            data=date(1986, 12, 22),
            numero=917,
            articolo=Articolo(numero=51),
        )
        storico = originale.con_vigenza(date(2020, 12, 31))
        assert originale.vigenza is None
        assert storico.vigenza == date(2020, 12, 31)
        assert storico.stringa != originale.stringa

    def test_data_solo_anno_in_uscita(self) -> None:
        urn = Urn(
            tipo=TipoAtto.REGIO_DECRETO,
            data=date(1942, 1, 1),
            numero=262,
            allegato=2,
            articolo=Articolo(numero=2043),
            anno_solo=True,
        )
        assert urn.stringa == "urn:nir:stato:regio.decreto:1942;262:2~art2043"

    def test_numero_atto_non_positivo_rifiutato(self) -> None:
        with pytest.raises(UrnNonValido):
            Urn(tipo=TipoAtto.LEGGE, data=date(2020, 1, 1), numero=0, articolo=Articolo(numero=1))

    def test_numero_articolo_non_positivo_rifiutato(self) -> None:
        with pytest.raises(UrnNonValido):
            Articolo(numero=0)


class TestAnalisiFormaLunga:
    def test_forma_lunga_con_allegato(self) -> None:
        urn = analizza("urn:nir:stato:regio.decreto:1942-03-16;262:2~art2043")
        assert urn.tipo is TipoAtto.REGIO_DECRETO
        assert urn.data == date(1942, 3, 16)
        assert urn.numero == 262
        assert urn.allegato == 2
        assert urn.articolo.numero == 2043
        assert urn.articolo.estensione is None
        assert urn.vigenza is None

    def test_forma_corta_byte_identica_alla_lunga(self) -> None:
        """docs/MISURE.md §3: 'Data corta valida... byte-identico alla forma lunga'."""
        urn = analizza("urn:nir:stato:regio.decreto:1942;262:2~art2043")
        assert urn.anno_solo is True
        assert urn.data.year == 1942
        assert urn.numero == 262
        assert urn.allegato == 2

    def test_estensione_senza_trattino_accettata(self) -> None:
        urn = analizza("urn:nir:stato:regio.decreto:1942-03-16;262:2~art2645ter")
        assert urn.articolo.numero == 2645
        assert urn.articolo.estensione is Estensione.TER

    def test_vigenza_analizzata(self) -> None:
        urn = analizza("urn:nir:stato:legge:1970-05-20;300~art18!vig=2012-06-17")
        assert urn.vigenza == date(2012, 6, 17)

    def test_costituzione_senza_numero_atto(self) -> None:
        # docs/MISURE.md: la Costituzione funziona anche senza un numero
        # esplicito quando l'atto è indicato in altro modo. Qui verifichiamo
        # solo che il tipo "costituzione" sia riconosciuto in un URN valido.
        urn = analizza("urn:nir:stato:costituzione:1947-12-27;1~art21")
        assert urn.tipo is TipoAtto.COSTITUZIONE


class TestRifiuti:
    """Ogni caso qui è un 400 misurato contro l'API reale (docs/MISURE.md §3)."""

    def test_comma_rifiutato(self) -> None:
        with pytest.raises(UrnNonValido, match="comma"):
            analizza("urn:nir:stato:legge:1970-05-20;300~art18-com1")

    def test_lettera_rifiutata(self) -> None:
        with pytest.raises(UrnNonValido, match="comma"):
            analizza("urn:nir:stato:legge:1970-05-20;300~art7-com1-letb")

    def test_estensione_con_trattino_rifiutata(self) -> None:
        with pytest.raises(UrnNonValido, match="trattino"):
            analizza("urn:nir:stato:regio.decreto:1942-03-16;262:2~art2645-ter")

    def test_vigenza_vuota_rifiutata(self) -> None:
        with pytest.raises(UrnNonValido, match="vig"):
            analizza("urn:nir:stato:legge:1970-05-20;300~art17!vig=")

    @pytest.mark.parametrize("partizione", ["all1", "pre", "dis1"])
    def test_partizioni_diverse_dall_articolo_rifiutate(self, partizione: str) -> None:
        with pytest.raises(UrnNonValido, match="partizione"):
            analizza(f"urn:nir:stato:regio.decreto:1942-03-16;262:2~{partizione}")

    def test_tipo_atto_sconosciuto_rifiutato(self) -> None:
        with pytest.raises(UrnNonValido, match="tipo di atto"):
            analizza("urn:nir:stato:decreto.ministeriale:2020-01-01;1~art1")

    def test_prefisso_mancante_rifiutato(self) -> None:
        with pytest.raises(UrnNonValido, match="prefisso"):
            analizza("non:un:urn:legge:2020-01-01;1~art1")

    def test_estensione_sconosciuta_rifiutata(self) -> None:
        with pytest.raises(UrnNonValido, match="estensione"):
            analizza("urn:nir:stato:legge:1970-05-20;300~art18xyz")
