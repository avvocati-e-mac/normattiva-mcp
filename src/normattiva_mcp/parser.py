"""Trasforma `articoloHtml` in un esito tipizzato — e SCOPRE gli errori
silenziosi che Normattiva restituisce sotto un innocuo HTTP 200.

Il controllo portante (docs/MISURE.md §11, trasferito dal progetto di
ricerca originale): «il numero d'articolo estratto dall'heading COINCIDE
con quello richiesto — è il solo controllo che avrebbe scoperto entrambi
gli errori» di una skill esterna. Un URN formalmente perfetto che punta al
nulla, o a un articolo diverso, è indistinguibile da uno giusto per
chiunque non faccia questo confronto: il portale risponde 200 a tutto, e
l'API risponde 200 con testo plausibile anche per un preambolo. Se
l'heading non coincide, qui si solleva un errore: MAI un risultato
"plausibile".

Le altre regole misurate:
  - i blocchi `art_aggiornamento-akn` sono cronologia di modifiche, non
    norma vigente: si separano, non si mescolano al testo (docs/MISURE.md
    §4, nota sui blocchi AGGIORNAMENTO).
  - un articolo abrogato restituisce poche decine di caratteri: è
    informazione, non un errore e non un vuoto (docs/MISURE.md §4.5).
  - `~art1` su molti atti restituisce 200 con il PREAMBOLO di
    promulgazione: se il testo non comincia con "Art. <N>", è preambolo
    (docs/MISURE.md §4.1).

Il markup reale (dalle catture in tests/fixtures/risposte/reale-*.json, 7
agosto 2026) ha tre proprietà da cui il codice sotto dipende:
  1. l'heading standard è `<h2 class="article-num-akn" id="art_N">Art. N</h2>`;
  2. nei codici approvati per allegato (art. 2043 c.c., art. 422 cod.nav.)
     quella classe NON compare: il testo sta in
     `<span class="attachment-just-text">` e comincia con "Art. N.";
  3. per `~art1` la risposta porta preambolo E articolo insieme — da qui
     il taglio in `_dal_heading`.
"""

from __future__ import annotations

import html as _html_lib
import re
from dataclasses import dataclass
from datetime import date as _date

from normattiva_mcp.estensioni import Estensione
from normattiva_mcp.urn import Articolo

_MARCATORE_AGGIORNAMENTO = "art_aggiornamento-akn"
_MARCATORE_HEADING = "article-num-akn"
_SOGLIA_ABROGATO = 200
"""Soglia dichiarata dalle misure (docs/MISURE.md §4.5: "ABROGATO in meno
di ~200 caratteri"). I casi osservati stanno fra 64 e 116 caratteri."""


@dataclass(frozen=True, slots=True)
class CorpoArticolo:
    """Il corpo di un articolo, con la cronologia già separata dal testo."""

    testo: str
    """Il testo dell'articolo, SENZA i blocchi di aggiornamento."""
    aggiornamenti: tuple[str, ...]
    """I blocchi di aggiornamento, uno per elemento, in ordine. Preziosi da
    conservare, mai da mescolare al testo."""
    heading: str
    """L'heading come è stato letto (es. "Art. 2043"): è la prova del
    controllo di coincidenza, va conservata e mostrata."""


@dataclass(frozen=True, slots=True)
class Abrogato:
    """L'articolo esiste ma è stato abrogato: 200, testo brevissimo."""

    messaggio: str
    data_abrogazione: _date | None
    """Letta dal messaggio quando è parsabile — serve a proporre il
    rilancio con !vig= al giorno precedente."""


@dataclass(frozen=True, slots=True)
class Preambolo:
    """La trappola `~art1`: 200, ma il testo è la premessa dell'atto, non
    l'articolo richiesto."""

    caratteri: int
    incipit: str


Esito = CorpoArticolo | Abrogato | Preambolo


class HtmlVuoto(ValueError):
    """Normattiva ha risposto senza testo dell'articolo."""


class HeadingDiscordante(ValueError):
    """L'heading esiste ma indica un altro articolo — l'errore silenzioso
    che nessun altro controllo scopre."""

    def __init__(self, richiesto: str, trovato: str) -> None:
        self.richiesto = richiesto
        self.trovato = trovato
        super().__init__(
            f'Normattiva ha restituito "{trovato}" invece di "{richiesto}": '
            "coordinate sbagliate, il testo NON è quello richiesto."
        )


def analizza(html_grezzo: str, richiesto: Articolo) -> Esito:
    """L'unico ingresso. `richiesto` è l'articolo che il chiamante ha
    chiesto: senza di esso non esiste il controllo di coincidenza, quindi
    non è opzionale.
    """
    parti = html_grezzo.split(_MARCATORE_AGGIORNAMENTO)

    # MISURATO: per `~art1` la risposta NON contiene solo il preambolo —
    # contiene il preambolo E POI l'articolo. Senza questo taglio il testo
    # arriverebbe al modello preceduto da migliaia di caratteri di "Visti
    # gli articoli...": non falso, ma spazzatura pagata a peso di contesto.
    corpo_html = _dal_heading(parti[0]) or parti[0]
    aggiornamenti = tuple(t for t in (_testo_semplice(p) for p in parti[1:]) if t)

    testo = _testo_semplice(corpo_html)
    testo_completo = _testo_semplice(html_grezzo)

    # 1. Abrogato PRIMA di ogni altra cosa: non ha heading utile, e
    #    trattarlo come vuoto o come preambolo perderebbe l'unica
    #    informazione che porta.
    if len(testo_completo) < _SOGLIA_ABROGATO and "ABROGAT" in testo_completo.upper():
        return Abrogato(
            messaggio=testo_completo,
            data_abrogazione=_data_abrogazione(testo_completo),
        )

    if not testo:
        raise HtmlVuoto("Normattiva ha risposto senza testo dell'articolo.")

    # 2. L'heading: prima dalla classe misurata, poi — se la classe non
    #    compare — dal testo stesso, che negli articoli veri comincia con
    #    "Art. <N>". La seconda via non è un ripiego permissivo: serve solo
    #    a trovare il numero, che viene comunque confrontato.
    heading = _heading(corpo_html) or _heading_dal_testo(testo)
    if heading is None:
        # 3. Nessun numero d'articolo da nessuna parte = preambolo.
        return Preambolo(caratteri=len(testo), incipit=testo[:120])

    if not _coincide(heading, richiesto):
        suffisso = richiesto.estensione.value if richiesto.estensione else ""
        raise HeadingDiscordante(
            richiesto=f"Art. {richiesto.numero}{suffisso}",
            trovato=heading.testo,
        )

    # 4. Il guardiano del preambolo. Il controllo di coincidenza protegge
    #    dall'articolo sbagliato, NON dal contenuto sbagliato sotto il
    #    numero giusto: un atto può rispondere "Art. 1" seguito dai
    #    "visti" — 4.673 caratteri di preambolo consegnati come se fossero
    #    il principio del risultato. Meglio dichiarare il preambolo che
    #    consegnare il testo sbagliato.
    if _sembra_preambolo(testo, dopo=heading.testo):
        return Preambolo(caratteri=len(testo), incipit=testo[:120])

    return CorpoArticolo(testo=testo, aggiornamenti=aggiornamenti, heading=heading.testo)


# --- Guardiano del preambolo -------------------------------------------

_FRASI_DI_PROMULGAZIONE = (
    "IL PRESIDENTE DELLA REPUBBLICA",
    "IL PRESIDENTE DEL CONSIGLIO DEI MINISTRI",
    "VISTI GLI ARTICOLI",
    "VISTO L'ARTICOLO",
    "VISTA LA LEGGE",
    "VISTO IL DECRETO",
    "VISTA LA DIRETTIVA",
    "VISTA LA DELIBERAZIONE DEL CONSIGLIO DEI MINISTRI",
    "SULLA PROPOSTA DEL",
    "UDITO IL PARERE DEL CONSIGLIO DI STATO",
    "SENTITA LA CONFERENZA",
    "EMANA IL SEGUENTE DECRETO",
    "IL SEGUENTE DECRETO LEGISLATIVO:",
)
_FORMULE_MINIME_PER_IL_PREAMBOLO = 2
"""Quante formule devono comparire perché il testo sia un preambolo. DUE,
non una: una sola frase può capitare in un articolo vero (l'art. 87 Cost.
comincia con "Il Presidente della Repubblica è il capo dello Stato"); due
o più sono la catena dei "visti", che in un articolo non esiste."""
_FINESTRA_DEL_PREAMBOLO = 400
"""La finestra in cui cercare le formule: solo l'inizio del corpo. Un
articolo che più avanti cita un decreto non deve essere respinto."""


def _sembra_preambolo(testo: str, *, dopo: str) -> bool:
    """True se il testo consegnato sotto quell'heading è in realtà la
    premessa dell'atto. Non guarda il numero richiesto: la trappola è
    misurata su `~art1` ma nulla garantisce che resti lì.
    """
    corpo = testo
    if corpo.startswith(dopo):
        corpo = corpo[len(dopo) :]
    finestra = corpo[:_FINESTRA_DEL_PREAMBOLO].replace("’", "'").upper()
    trovate = 0
    for frase in _FRASI_DI_PROMULGAZIONE:
        if frase in finestra:
            trovate += 1
            if trovate >= _FORMULE_MINIME_PER_IL_PREAMBOLO:
                return True
    return False


# --- Heading -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Heading:
    testo: str
    numero: int
    estensione: str
    """L'estensione come appare nell'heading, già normalizzata in
    minuscolo e senza trattini/punti/spazi: l'URN vuole "2645ter" ma il
    testo stampato può dire "Art. 2645-ter"."""


def _dal_heading(frammento_html: str) -> str | None:
    """Il markup dall'apertura del tag che porta `article-num-akn` in poi,
    o None se quella classe non compare (il caso `attachment-just-text` dei
    codici: l'art. 2043 c.c. e l'art. 422 cod.nav. non hanno heading di
    classe, e lì non c'è preambolo da tagliare).
    """
    indice_classe = frammento_html.find(_MARCATORE_HEADING)
    if indice_classe == -1:
        return None
    indice_apertura = frammento_html.rfind("<", 0, indice_classe)
    if indice_apertura == -1:
        return None
    return frammento_html[indice_apertura:]


def _heading(frammento_html: str) -> _Heading | None:
    """Legge il testo del primo elemento che porta la classe
    `article-num-akn`, senza assumere quale tag sia."""
    indice_classe = frammento_html.find(_MARCATORE_HEADING)
    if indice_classe == -1:
        return None
    indice_chiusura_tag = frammento_html.find(">", indice_classe)
    if indice_chiusura_tag == -1:
        return None
    resto = frammento_html[indice_chiusura_tag + 1 :]
    indice_apertura_tag_successivo = resto.find("<")
    grezzo = (
        resto if indice_apertura_tag_successivo == -1 else resto[:indice_apertura_tag_successivo]
    )
    return _heading_da_testo(_testo_semplice(grezzo))


def _heading_dal_testo(testo: str) -> _Heading | None:
    """Il ripiego: l'articolo vero comincia con "Art. 2043." anche quando
    la classe non compare nel markup che ci è stato dato."""
    return _heading_da_testo(testo[:40])


_SEPARATORI_ESTENSIONE = frozenset({"-", " ", ".", " "})

# L'elenco delle estensioni ordinali ammesse è DERIVATO da estensioni.py,
# non ricopiato: due elenchi latini scritti a mano divergono, e il giorno
# che divergono l'errore è invisibile — se l'atto stampa "Art. 21-novies" e
# noi abbiamo chiesto l'art. 21, il confronto DEVE dire discordante, non
# "uguale perché l'estensione non l'ho saputa leggere".
_ESTENSIONI_NOTE: frozenset[str] = frozenset(e.value for e in Estensione)


def _heading_da_testo(grezzo: str) -> _Heading | None:
    # Deve cominciare con "Art" per essere un heading d'articolo: un
    # preambolo che nomina "gli articoli 76 e 87" non deve passare di qui.
    ripulito = grezzo.strip()
    if not ripulito.lower().startswith("art"):
        return None

    # 1. Salta "Art" e la punteggiatura che lo separa dal numero.
    cursore = 3
    while cursore < len(ripulito) and ripulito[cursore] in (".", " ", " "):
        cursore += 1

    # 2. Il numero.
    inizio_cifre = cursore
    while cursore < len(ripulito) and ripulito[cursore].isdigit():
        cursore += 1
    if inizio_cifre == cursore:
        return None
    numero = int(ripulito[inizio_cifre:cursore])
    fine_del_numero = cursore

    # 3. L'estensione, SE è una delle ordinali latine note. Tutto il resto
    #    (rubrica, primo comma, qualunque cosa) non è estensione: l'heading
    #    finisce al numero. È l'elenco chiuso che impedisce a una rubrica
    #    non parentetica ("Art. 542. Concorso di coniuge e figli") di
    #    diventare un'estensione inventata che respinge l'articolo giusto.
    dopo_separatore = fine_del_numero
    while dopo_separatore < len(ripulito) and ripulito[dopo_separatore] in _SEPARATORI_ESTENSIONE:
        dopo_separatore += 1
    fine_delle_lettere = dopo_separatore
    while fine_delle_lettere < len(ripulito) and (
        ripulito[fine_delle_lettere].isalpha() or ripulito[fine_delle_lettere] == "-"
    ):
        fine_delle_lettere += 1
    candidata = "".join(
        c for c in ripulito[dopo_separatore:fine_delle_lettere].lower() if c.isalpha()
    )
    estensione = candidata if candidata in _ESTENSIONI_NOTE else ""

    # L'heading finisce con il numero e la sua eventuale estensione, MAI
    # con ciò che segue: nel markup reale dei codici, heading e rubrica
    # stanno nello stesso blocco senza tag di mezzo.
    fine = fine_delle_lettere if estensione else fine_del_numero
    testo = ripulito[:fine].strip(" .")
    return _Heading(testo=testo, numero=numero, estensione=estensione)


def _coincide(heading: _Heading, richiesto: Articolo) -> bool:
    """Coincidenza: numero uguale ed estensione uguale a meno di trattini,
    punti e maiuscole. Un articolo senza estensione non coincide con uno
    che ne ha una."""
    if heading.numero != richiesto.numero:
        return False
    attesa = richiesto.estensione.value if richiesto.estensione else ""
    return heading.estensione == attesa


# --- Abrogazione -----------------------------------------------------------

_MESI = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def _data_abrogazione(messaggio: str) -> _date | None:
    """ "...ABROGATO DAL D.LGS. 19 GIUGNO 2026, N. 117" -> 2026-06-19.
    Serve a proporre il rilancio con !vig= al giorno precedente. Restituisce
    None se il messaggio non porta una data leggibile — normale, non un
    errore: alcuni messaggi sono troncati già nella risposta di Normattiva.
    """
    parole = [p for p in re.split(r"[ ,.;:\n\t]+", messaggio.lower()) if p]
    for indice, parola in enumerate(parole):
        mese = _MESI.get(parola)
        if mese is None:
            continue
        if indice == 0 or indice + 1 >= len(parole):
            continue
        try:
            giorno = int(parole[indice - 1])
            anno = int(parole[indice + 1])
            return _date(anno, mese, giorno)
        except ValueError:
            continue
    return None


# --- HTML -> testo -----------------------------------------------------


def _testo_semplice(frammento_html: str) -> str:
    """Spoglia i tag e normalizza gli spazi. Non è un parser HTML generale:
    il contenuto viene da un endpoint istituzionale, non da pagine
    arbitrarie, e ciò che serve è il testo che finirà nel contesto del
    modello.
    """
    risultato: list[str] = []
    dentro_tag = False
    for carattere in frammento_html:
        if carattere == "<":
            dentro_tag = True
        elif carattere == ">":
            dentro_tag = False
            risultato.append(" ")
        elif not dentro_tag:
            risultato.append(carattere)
    testo = _html_lib.unescape("".join(risultato))
    pezzi = testo.split()
    return " ".join(pezzi)
