"""La tabella delle fonti verificate: dati, non codice.

Contiene le fonti che la ricerca full-text di Normattiva NON può risolvere
da sola — principalmente i codici storici, dove il numero di allegato
(`:2` per il codice civile, `:1` per il codice di procedura civile, ecc.)
non compare in nessun campo restituito dalla ricerca (docs/MISURE.md §6).

Non è, e non deve diventare, un elenco di "tutte le leggi": l'archivio di
Normattiva conta decine di migliaia di atti, e aggiungerne mille a mano
sarebbe un lavoro enorme che lascerebbe il problema aperto (vedi
docs/IDEE-SCARTATE.md). Questa tabella è la rubrica dei numeri difficili,
non l'elenco telefonico: per tutto il resto la ricerca (ricerca.py) è la
via normale.

I dati vivono in `data/fonti.json`, leggibile e modificabile da un avvocato
senza saper programmare. Il codice qui si limita a caricarli in dataclass
tipizzati e a fornire la ricerca per alias.

Ogni riga porta obbligatoriamente una `provenienza`: dove è stato
verificato quel dato. È la disciplina che ha fatto scoprire i due errori
della skill esistente (legge fallimentare datata 1942-01-16 invece di
1942-03-16; codice della navigazione senza l'allegato :1) — un dato senza
prova non entra in questa tabella.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as _date
from functools import lru_cache
from importlib import resources
from typing import Literal

from normattiva_mcp.urn import Articolo, TipoAtto, Urn

StatoFonte = Literal["vigente", "abrogata"]


@dataclass(frozen=True, slots=True)
class Fonte:
    """Una fonte normativa verificata, con l'URN base per raggiungerla."""

    nome_canonico: str
    alias: tuple[str, ...]
    tipo: TipoAtto
    data: _date
    numero: int
    allegato: int | None
    articolo_di_controllo: str
    """Un articolo che DEVE rispondere con testo vero (non preambolo, non
    abrogato) — usato da `norm verifica` per provare la riga. Deve essere un
    numero puro: nessuna estensione, per restare semplice da controllare."""
    art1_e_preambolo: bool
    """Se True, l'articolo 1 di questa fonte restituisce il preambolo di
    promulgazione invece del vero articolo 1 (docs/MISURE.md §4.1). Chi
    consuma questa fonte deve saperlo PRIMA di chiedere l'art. 1."""
    stato: StatoFonte
    nota_stato: str | None
    provenienza: str

    def urn_per_articolo(self, numero_articolo: int) -> Urn:
        """Costruisce l'URN per un articolo di questa fonte."""
        return Urn(
            tipo=self.tipo,
            data=self.data,
            numero=self.numero,
            allegato=self.allegato,
            articolo=Articolo(numero=numero_articolo),
        )

    def urn_di_controllo(self) -> Urn:
        """L'URN dell'articolo di controllo, per `norm verifica`."""
        return self.urn_per_articolo(int(self.articolo_di_controllo))


@dataclass(frozen=True, slots=True)
class FonteNonDisponibile:
    """Una fonte che l'utente potrebbe cercare ma che non è su Normattiva.

    Dichiararla esplicitamente evita che un modello interpreti un 404
    generico come "la norma non esiste nell'ordinamento": qui il messaggio
    dice perché non è raggiungibile DA QUESTO STRUMENTO.
    """

    nome_canonico: str
    alias: tuple[str, ...]
    nota: str


@dataclass(frozen=True, slots=True)
class TabellaFonti:
    verificate: tuple[Fonte, ...]
    non_disponibili: tuple[FonteNonDisponibile, ...]

    def trova(self, testo: str) -> Fonte | FonteNonDisponibile | None:
        """Cerca una fonte per nome o alias, senza distinguere maiuscole.

        Restituisce `None` se nessuna fonte (verificata o non disponibile)
        corrisponde — il chiamante decide come trattare l'assenza (per
        esempio, provando la ricerca full-text prima di arrendersi).
        """
        chiave = testo.strip().lower()
        if not chiave:
            return None
        for fonte in self.verificate:
            if chiave == fonte.nome_canonico.lower() or chiave in (a.lower() for a in fonte.alias):
                return fonte
        for non_disp in self.non_disponibili:
            if chiave == non_disp.nome_canonico.lower() or chiave in (
                a.lower() for a in non_disp.alias
            ):
                return non_disp
        return None


def _decodifica_stato(grezzo: dict) -> tuple[StatoFonte, str | None]:
    kind = grezzo["kind"]
    if kind not in ("vigente", "abrogata"):
        raise ValueError(f"stato di fonte sconosciuto: {kind!r}")
    return kind, grezzo.get("nota")


def _decodifica_fonte(grezza: dict) -> Fonte:
    anno, mese, giorno = (int(p) for p in grezza["data"].split("-"))
    stato, nota_stato = _decodifica_stato(grezza["stato"])
    return Fonte(
        nome_canonico=grezza["nome_canonico"],
        alias=tuple(grezza["alias"]),
        tipo=TipoAtto(grezza["tipo"]),
        data=_date(anno, mese, giorno),
        numero=grezza["numero"],
        allegato=grezza.get("allegato"),
        articolo_di_controllo=grezza["articolo_di_controllo"],
        art1_e_preambolo=grezza["art1_e_preambolo"],
        stato=stato,
        nota_stato=nota_stato,
        provenienza=grezza["provenienza"],
    )


def _decodifica_non_disponibile(grezza: dict) -> FonteNonDisponibile:
    return FonteNonDisponibile(
        nome_canonico=grezza["nome_canonico"],
        alias=tuple(grezza["alias"]),
        nota=grezza["nota"],
    )


@lru_cache(maxsize=1)
def carica_tabella() -> TabellaFonti:
    """Carica `data/fonti.json` una sola volta per processo (il file non
    cambia durante l'esecuzione — un nuovo processo lo rilegge da capo)."""
    percorso = resources.files("normattiva_mcp.data").joinpath("fonti.json")
    testo = percorso.read_text(encoding="utf-8")
    grezzo = json.loads(testo)
    verificate = tuple(_decodifica_fonte(f) for f in grezzo["verificate"])
    non_disponibili = tuple(_decodifica_non_disponibile(f) for f in grezzo["non_disponibili"])
    return TabellaFonti(verificate=verificate, non_disponibili=non_disponibili)
