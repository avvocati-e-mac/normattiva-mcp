"""Estensioni ordinali dell'articolo (bis, ter, ...), UNA sola sorgente.

Nel progetto di ricerca da cui questo pacchetto è stato portato (DS4 Chat),
due elenchi di queste estensioni erano scritti a mano in due punti diversi
del codice ed erano divergenti su sei grafie: un articolo con un'estensione
corretta veniva respinto perché il lettore non la riconosceva. Qui l'elenco
esiste in un punto solo (`Estensione`), e sia chi costruisce un URN sia chi
lo legge importano lo stesso enum: il difetto non può ripetersi perché non
c'è un secondo elenco da far divergere.

Provenienza, per gradi (vedi CLAUDE.md, "misurato ≠ storico noto ≠
inferito"):
  - **misurate** contro l'API: `bis` e `ter` (docs/MISURE.md §3);
  - **non misurate una per una** ma della stessa serie e con la stessa
    regola "senza trattino": da `quater` a `octies`;
  - **inferite** dalla nomenclatura latina standard usata dal legislatore
    italiano, per rendere costruibile ciò che prima non lo era (es. l'art.
    21-novies della l. 241/1990): da `novies` in poi.

NON è provato che Normattiva risponda 200 a un URN con una di queste
estensioni inferite. Se una risultasse 400, è un buco della misura — non
del design: l'esito resta comunque un errore dichiarato, mai un testo
plausibile al suo posto (vedi CLAUDE.md, regola 1).

Le estensioni si scrivono SENZA trattino: `art2645ter`, mai `art2645-ter`
(quest'ultima forma è 400, misurato — docs/MISURE.md §3).
"""

from enum import StrEnum


class Estensione(StrEnum):
    """Estensione ordinale di un articolo, nella grafia accettata dall'API."""

    # 2ª-8ª — misurate (bis, ter) o della stessa serie non misurata singolarmente
    BIS = "bis"
    TER = "ter"
    QUATER = "quater"
    QUINQUIES = "quinquies"
    SEXIES = "sexies"
    SEPTIES = "septies"
    OCTIES = "octies"

    # 9ª-14ª [inferite]. "quattuordecies" è la grafia alternativa di
    # "quaterdecies", entrambe in uso nella legislazione italiana.
    NOVIES = "novies"
    DECIES = "decies"
    UNDECIES = "undecies"
    DUODECIES = "duodecies"
    TERDECIES = "terdecies"
    QUATERDECIES = "quaterdecies"
    QUATTUORDECIES = "quattuordecies"

    # 15ª-19ª, doppia grafia dove la prassi la usa [inferite]. Le due grafie
    # NON sono sinonimi intercambiabili: quale delle due usi Normattiva non
    # è misurato, e chiedere l'una quando il sito vuole l'altra fa fallire
    # il controllo di coincidenza dell'intestazione — l'esito giusto, non un
    # testo servito al posto di un altro.
    QUINQUIESDECIES = "quinquiesdecies"
    QUINDECIES = "quindecies"
    SEXIESDECIES = "sexiesdecies"
    SEDECIES = "sedecies"
    SEPTIESDECIES = "septiesdecies"
    DUODEVICIES = "duodevicies"
    OCTIESDECIES = "octiesdecies"
    UNDEVICIES = "undevicies"
    NOVIESDECIES = "noviesdecies"

    # 20ª-25ª [inferite]. Le forme composte si scrivono attaccate come ogni
    # altra estensione: "vicies semel" diventa "viciessemel".
    VICIES = "vicies"
    VICIESSEMEL = "viciessemel"
    VICIESBIS = "viciesbis"
    VICIESTER = "viciester"
    VICIESQUATER = "viciesquater"
    VICIESQUINQUIES = "viciesquinquies"


def analizza_estensione(suffisso: str) -> Estensione | None:
    """Riconosce un suffisso dopo il numero dell'articolo, o None se assente.

    Solleva ValueError se il suffisso non è vuoto e non corrisponde a
    nessuna estensione nota — il chiamante lo converte nell'errore tipizzato
    appropriato (vedi urn.py).
    """
    if not suffisso:
        return None
    try:
        return Estensione(suffisso)
    except ValueError:
        raise ValueError(f"estensione dell'articolo sconosciuta: {suffisso!r}") from None
