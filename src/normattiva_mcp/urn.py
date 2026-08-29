"""Costruzione e lettura di URN-NIR (`urn:nir:stato:...`) per Normattiva.

La grammatica implementata qui NON è quella che la documentazione ufficiale
di Normattiva descrive: è quella MISURATA contro l'endpoint reale (vedi
docs/MISURE.md §3). Ogni rifiuto tipizzato sotto cita la riga della misura
che lo impone.

Il tipo `Urn` è pensato perché uno stato non rappresentabile (comma, lettera,
preambolo come partizione, estensione con trattino, `!vig=` vuoto) non possa
nemmeno essere costruito: la validazione vive in un punto solo — qui — non
sparsa nei chiamanti (vedi CLAUDE.md, regola 6 "un valore, un simbolo").

Deliberatamente NON esiste un parametro "comma" o "lettera": l'API risponde
400 a `~art18-com1` e a `~art7-com1-letb` sempre. Chi cerca un comma legge
l'intero articolo e lo isola nel testo restituito.

NON è provato che questa grammatica resti stabile nel tempo: l'endpoint è
un BFF interno non versionato (docs/LIMITI.md).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date as _date
from enum import StrEnum

from normattiva_mcp.estensioni import Estensione, analizza_estensione

_PREFISSO_URN = "urn:nir:stato:"
_BASE_PERMALINK = "https://www.normattiva.it/uri-res/N2Ls?"


class TipoAtto(StrEnum):
    """I 6 tipi di atto con `!vig=` verificato funzionante (docs/MISURE.md §5).

    Altri tipi possono esistere su Normattiva ma non sono stati provati
    contro l'API: aggiungerne uno qui è una dichiarazione "l'ho misurato",
    non una comodità sintattica.
    """

    COSTITUZIONE = "costituzione"
    LEGGE = "legge"
    REGIO_DECRETO = "regio.decreto"
    DECRETO_LEGISLATIVO = "decreto.legislativo"
    DECRETO_LEGGE = "decreto.legge"
    DPR = "decreto.del.presidente.della.repubblica"


class UrnNonValido(ValueError):
    """Un URN che l'API rifiuterebbe — sempre con una causa dichiarata.

    Il messaggio è scritto per essere mostrato a un LLM o a un avvocato,
    non solo per il debug: dice sempre COSA è sbagliato e, dove utile,
    PERCHÉ (la regola misurata che lo impone).
    """


@dataclass(frozen=True, slots=True)
class Articolo:
    """Un articolo, senza comma né lettera (non rappresentabili, vedi sopra)."""

    numero: int
    estensione: Estensione | None = None

    def __post_init__(self) -> None:
        if self.numero <= 0:
            raise UrnNonValido(f"numero dell'articolo non positivo: {self.numero}")

    @property
    def componente_urn(self) -> str:
        suffisso = self.estensione.value if self.estensione else ""
        return f"art{self.numero}{suffisso}"


@dataclass(frozen=True, slots=True)
class Urn:
    """Un URN-NIR completo per un singolo articolo di un atto normativo.

    Forma: ``urn:nir:stato:<tipo>:<data>;<numero>[:<allegato>]~art<N><estensione>[!vig=YYYY-MM-DD]``
    """

    tipo: TipoAtto
    data: _date
    numero: int
    articolo: Articolo
    allegato: int | None = None
    vigenza: _date | None = None
    anno_solo: bool = False
    """Data resa come solo anno (`1942` invece di `1942-03-16`).

    Misurato: l'API accetta entrambe le forme e le tratta come identiche
    (docs/MISURE.md §3, "Data corta valida"). Il campo esiste perché la
    forma canonica prodotta da questo pacchetto è sempre quella lunga
    (nessuna ambiguità in uscita); la forma corta si riconosce solo in
    lettura, quando l'URN arriva da un testo esterno (un rinvio normativo).
    """

    def __post_init__(self) -> None:
        if self.numero <= 0:
            raise UrnNonValido(f"numero dell'atto non positivo: {self.numero}")

    def con_vigenza(self, data_vigenza: _date) -> Urn:
        """Lo stesso URN chiesto a una data di vigenza diversa.

        Restituisce un URN NUOVO — l'originale non cambia. Serve alla
        ricaduta automatica su un articolo abrogato: l'URN originale resta
        quello da citare come "alla data odierna la norma risulta abrogata".
        """
        return replace(self, vigenza=data_vigenza)

    @property
    def _componente_data(self) -> str:
        if self.anno_solo:
            return f"{self.data.year:04d}"
        return self.data.strftime("%Y-%m-%d")

    @property
    def stringa(self) -> str:
        """La stringa URN canonica, forma completa."""
        s = f"{_PREFISSO_URN}{self.tipo.value}:{self._componente_data};{self.numero}"
        if self.allegato is not None:
            s += f":{self.allegato}"
        s += f"~{self.articolo.componente_urn}"
        if self.vigenza is not None:
            s += f"!vig={self.vigenza.strftime('%Y-%m-%d')}"
        return s

    @property
    def permalink(self) -> str:
        """Il link pubblico cliccabile — SOLO da mostrare, MAI da scaricare.

        Il portale restituisce l'intero atto in un unico blocco non
        segmentabile (docs/MISURE.md §2: 2.591.983 byte per il codice
        civile intero contro 1.287 byte dell'API per un solo articolo —
        fattore 2.013x). Il testo per il modello viene sempre dall'API
        (client.py), mai da questo URL.
        """
        return f"{_BASE_PERMALINK}{self.stringa}"


def analizza(testo: str) -> Urn:
    """Riconosce un URN-NIR, in forma lunga o corta, e rifiuta con un errore
    tipizzato ogni forma che l'API risponderebbe 400 (docs/MISURE.md §3):
    comma, lettera, partizioni diverse dall'articolo, estensione con
    trattino, `!vig=` vuoto.
    """
    if not testo.startswith(_PREFISSO_URN):
        raise UrnNonValido(
            f"non è un URN Normattiva (manca il prefisso {_PREFISSO_URN!r}): {testo!r}"
        )

    dopo_prefisso = testo[len(_PREFISSO_URN) :]

    primi_due_punti = dopo_prefisso.find(":")
    if primi_due_punti == -1:
        raise UrnNonValido(f"URN malformato, manca il tipo di atto: {testo!r}")
    tipo_grezzo = dopo_prefisso[:primi_due_punti]
    try:
        tipo = TipoAtto(tipo_grezzo)
    except ValueError:
        raise UrnNonValido(
            f"tipo di atto sconosciuto o non verificato: {tipo_grezzo!r}. "
            f"Tipi verificati: {', '.join(t.value for t in TipoAtto)}"
        ) from None
    resto = dopo_prefisso[primi_due_punti + 1 :]

    indice_tilde = resto.find("~")
    if indice_tilde == -1:
        raise UrnNonValido(f"URN malformato, manca '~art...': {testo!r}")
    testa = resto[:indice_tilde]
    coda = resto[indice_tilde + 1 :]

    # testa = "<data>;<numero>[:<allegato>]"
    indice_punto_virgola = testa.find(";")
    if indice_punto_virgola == -1:
        raise UrnNonValido(f"URN malformato, manca ';' prima del numero: {testo!r}")
    data_grezza = testa[:indice_punto_virgola]
    numero_e_allegato = testa[indice_punto_virgola + 1 :]

    data_valore, anno_solo = _analizza_data(data_grezza)

    parti = numero_e_allegato.split(":", maxsplit=1)
    try:
        numero = int(parti[0])
    except ValueError:
        raise UrnNonValido(f"numero dell'atto non valido: {parti[0]!r}") from None
    allegato: int | None = None
    if len(parti) > 1:
        try:
            allegato = int(parti[1])
        except ValueError:
            raise UrnNonValido(f"allegato non valido: {parti[1]!r}") from None

    # coda = "art<N><estensione>[!vig=YYYY-MM-DD]" oppure una partizione nota
    # per essere invalida (all/pre/dis, senza "art" davanti).
    parti_punto_escl = coda.split("!", maxsplit=1)
    parte_articolo = parti_punto_escl[0]
    vigenza: _date | None = None
    if len(parti_punto_escl) > 1:
        vig_grezzo = parti_punto_escl[1]
        if not vig_grezzo.startswith("vig="):
            raise UrnNonValido(f"URN malformato dopo '!': {testo!r}")
        vig_data_grezza = vig_grezzo[len("vig=") :]
        if not vig_data_grezza:
            raise UrnNonValido(
                "'!vig=' senza data è un 400 misurato: omettere il campo, "
                "non passare una data vuota (docs/MISURE.md §3)"
            )
        vigenza = _analizza_data_completa(vig_data_grezza)

    if parte_articolo.startswith(("all", "pre", "dis")):
        raise UrnNonValido(
            f"partizione non supportata dall'API Normattiva (400 misurato): {parte_articolo!r} "
            "(solo l'articolo intero è indirizzabile, mai allegati/preamboli/disposizioni "
            "come partizione — docs/MISURE.md §3)"
        )
    if not parte_articolo.startswith("art"):
        raise UrnNonValido(f"URN malformato, atteso 'art...': {parte_articolo!r}")
    dopo_art = parte_articolo[len("art") :]

    if "-com" in dopo_art or "-let" in dopo_art:
        raise UrnNonValido(
            f"comma o lettera non rappresentabili nell'URN Normattiva "
            f"(400 misurato): {parte_articolo!r} "
            "(docs/MISURE.md §3: leggere l'articolo intero e isolare il comma nel testo)"
        )
    if "-" in dopo_art:
        senza_trattino = dopo_art.replace("-", "")
        raise UrnNonValido(
            f"estensione con trattino non supportata: l'API vuole 'art{senza_trattino}', "
            f"non {parte_articolo!r} (400 misurato — docs/MISURE.md §3)"
        )

    cifre = ""
    for carattere in dopo_art:
        if carattere.isdigit():
            cifre += carattere
        else:
            break
    if not cifre:
        raise UrnNonValido(f"numero dell'articolo non valido: {parte_articolo!r}")
    numero_articolo = int(cifre)
    suffisso = dopo_art[len(cifre) :]
    try:
        estensione = analizza_estensione(suffisso)
    except ValueError as errore:
        raise UrnNonValido(f"{errore} (in {parte_articolo!r})") from None

    return Urn(
        tipo=tipo,
        data=data_valore,
        numero=numero,
        allegato=allegato,
        articolo=Articolo(numero=numero_articolo, estensione=estensione),
        vigenza=vigenza,
        anno_solo=anno_solo,
    )


def _analizza_data(grezza: str) -> tuple[_date, bool]:
    """Riconosce sia `YYYY` (anno solo) sia `YYYY-MM-DD` (data completa)."""
    if len(grezza) == 4 and grezza.isdigit():
        return _date(int(grezza), 1, 1), True
    return _analizza_data_completa(grezza), False


def _analizza_data_completa(grezza: str) -> _date:
    parti = grezza.split("-")
    if len(parti) != 3:
        raise UrnNonValido(f"data non valida: {grezza!r}")
    try:
        anno, mese, giorno = (int(p) for p in parti)
        return _date(anno, mese, giorno)
    except ValueError as errore:
        raise UrnNonValido(f"data non valida: {grezza!r} ({errore})") from None
