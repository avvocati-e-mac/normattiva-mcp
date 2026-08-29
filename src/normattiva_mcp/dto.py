"""Le due forme di risposta di `dettaglio-atto-urn`, risolte in un punto solo.

Per alcuni atti l'API mette il contenuto in `data.atto`; per altri
`data.atto` è `null` e il contenuto sta in `data.lista` (un array di 2
elementi: il testo originario e la ripubblicazione con le note). Un client
che legge solo `data.atto` classifica tre voci corrette come rotte — è
successo davvero durante il red team di agosto (docs/MISURE.md §4.2).

Tutto qui è `decodeIfPresent`-equivalente: un campo che sparisce dalla
risposta deve produrre un errore leggibile più avanti nella pipeline, non un
crash qui. Questo modulo non decide se il testo è un preambolo o un
abrogato — quello è compito di guardiani.py, che lavora sul testo già
estratto da parser.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NodoAtto:
    """Un nodo `atto` grezzo dalla risposta API — o il primo elemento di
    `data.lista`, quando è quella la forma usata. Corrisponde 1:1 ai campi
    JSON, senza interpretazione.
    """

    titolo: str | None
    sotto_titolo: str | None
    articolo_html: str | None
    articolo_data_inizio_vigenza: str | None
    articolo_data_fine_vigenza: str | None


def _decodifica_nodo(grezzo: dict) -> NodoAtto:
    return NodoAtto(
        titolo=grezzo.get("titolo"),
        sotto_titolo=grezzo.get("sottoTitolo"),
        articolo_html=grezzo.get("articoloHtml"),
        articolo_data_inizio_vigenza=grezzo.get("articoloDataInizioVigenza"),
        articolo_data_fine_vigenza=grezzo.get("articoloDataFineVigenza"),
    )


def nodo_utile(corpo_risposta: dict) -> NodoAtto | None:
    """Risolve le due forme in un punto solo: restituisce il nodo da usare,
    o None se la risposta non ne contiene nessuno (corpo malformato — il
    chiamante lo tratta come un errore di trasporto, non come "atto
    inesistente").

    Precedenza a `data.atto` quando presente; altrimenti il primo elemento
    di `data.lista` (il testo originario, non la ripubblicazione con note —
    è quello che un lettore umano si aspetta leggendo "l'articolo").
    """
    dati = corpo_risposta.get("data") or {}
    atto = dati.get("atto")
    if atto is not None:
        return _decodifica_nodo(atto)

    lista = dati.get("lista")
    if lista:
        return _decodifica_nodo(lista[0])

    return None
