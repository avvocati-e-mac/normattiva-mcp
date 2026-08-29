"""Risoluzione alias → URN, senza rete.

Perché questa è l'unica strada per i codici, non un'ottimizzazione
(docs/MISURE.md §6): la ricerca full-text non trova mai i codici storici —
"art. 2043 codice civile" restituisce un decreto qualsiasi, il codice
civile non compare — perché il numero di allegato (`262:2`) non esiste in
nessun campo indicizzato dal motore di ricerca. Un client che prova prima
la ricerca e poi "eventualmente" questa lookup ha già perso: per i codici
la ricerca restituisce rumore plausibile, non un errore che fa scattare un
ripiego.

Questo modulo è puro: nessuna rete, solo `fonti.py` più normalizzazione di
stringa. Chi vuole il testo dell'articolo passa l'URN prodotto qui al
client (client.py); questo modulo non lo fa e non lo sa fare.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date as _date

from normattiva_mcp.estensioni import analizza_estensione
from normattiva_mcp.fonti import Fonte, FonteNonDisponibile, TabellaFonti, carica_tabella
from normattiva_mcp.urn import Articolo, TipoAtto, Urn, UrnNonValido

_MESI_ITALIANI = {
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
}

# Le forme di tipo riconosciute per l'estrazione da una grafia estesa
# ("regio decreto 16 marzo 1942 n 267"). Nessuna coppia è prefisso
# dell'altra al secondo token, quindi al più una voce corrisponde a una
# data sequenza: l'ordine dell'elenco non cambia il risultato.
_TIPI_ESTESI: tuple[tuple[tuple[str, ...], TipoAtto], ...] = (
    (("costituzione",), TipoAtto.COSTITUZIONE),
    (("legge",), TipoAtto.LEGGE),
    (("regio", "decreto"), TipoAtto.REGIO_DECRETO),
    (("decreto", "legislativo"), TipoAtto.DECRETO_LEGISLATIVO),
    (("decreto", "legge"), TipoAtto.DECRETO_LEGGE),
    (("decreto", "del", "presidente", "della", "repubblica"), TipoAtto.DPR),
)


class RiferimentoSconosciuto(ValueError):
    """Nessuna fonte, verificata o non disponibile, corrisponde all'alias."""


class FonteNonDisponibileErrore(ValueError):
    """L'alias è noto ma la fonte è dichiaratamente assente da Normattiva.

    Il chiamante deve dirlo all'utente con la nota — non ritentare con
    un'altra grafia, non inventare un URN.
    """

    def __init__(self, fonte: FonteNonDisponibile) -> None:
        self.fonte = fonte
        super().__init__(f"{fonte.nome_canonico} non è disponibile su Normattiva: {fonte.nota}")


@dataclass(frozen=True, slots=True)
class RisultatoLookup:
    """L'esito di una risoluzione riuscita: l'URN, e da dove viene."""

    urn: Urn
    fonte: Fonte | None
    """La fonte verificata usata, se la richiesta è passata da un alias
    noto. None se l'URN è stato costruito da estremi non verificati."""
    avvertenze: tuple[str, ...]
    """Avvertimenti non bloccanti da mostrare insieme al risultato: la
    richiesta si risolve comunque, ma con una riserva che non si può
    nascondere (CLAUDE.md regola 2, "mai avvertenza silenziosa")."""


def normalizza_alias(grezzo: str) -> str:
    """Normalizza un alias in UN punto solo (CLAUDE.md regola 6): minuscolo,
    diacritici rimossi, punteggiatura tolta, spazi collassati. Rende
    equivalenti "c.c.", "cc" e "Codice Civile" — le tre grafie con cui un
    utente reale nomina lo stesso codice.
    """
    decomposto = unicodedata.normalize("NFKD", grezzo.lower())
    senza_diacritici = "".join(c for c in decomposto if not unicodedata.combining(c))
    risultato: list[str] = []
    ultimo_era_spazio = False
    for carattere in senza_diacritici:
        if carattere.isalnum():
            risultato.append(carattere)
            ultimo_era_spazio = False
        elif not ultimo_era_spazio:
            risultato.append(" ")
            ultimo_era_spazio = True
    return "".join(risultato).strip()


def _anno_atto(fonte: Fonte) -> int:
    return fonte.data.year


@dataclass(frozen=True, slots=True)
class _EstremiEstratti:
    """Estremi (tipo, anno, numero) letti da una grafia estesa.

    Tipo nominato invece di una tupla perché il confronto per uguaglianza
    conta: due riconoscimenti diversi che producono lo stesso valore non
    sono un'ambiguità, due che producono valori diversi sì.
    """

    tipo: TipoAtto
    anno: int
    numero: int


def _estremi_con_data_estesa(resto: list[str], tipo: TipoAtto) -> _EstremiEstratti | None:
    """Forma (a): "<giorno> <mese> <anno> n <numero>", dopo il tipo.

    Non è un parser di date italiane: giorno e mese servono solo a
    riconoscere che la stringa ha la forma di una data estesa (delimitano
    dove finisce il tipo e dove inizia l'anno). La tabella delle fonti ha
    già giorno e mese di ogni fonte verificata: il rimatch ne ha bisogno
    solo per tipo, numero e anno.
    """
    if len(resto) != 5:
        return None
    if not resto[0].isdigit() or not (1 <= int(resto[0]) <= 31):
        return None
    if resto[1] not in _MESI_ITALIANI:
        return None
    if not resto[2].isdigit() or not (1000 <= int(resto[2]) <= 9999):
        return None
    if resto[3] != "n":
        return None
    if not resto[4].isdigit():
        return None
    return _EstremiEstratti(tipo=tipo, anno=int(resto[2]), numero=int(resto[4]))


def _estremi_senza_data(resto: list[str], tipo: TipoAtto) -> _EstremiEstratti | None:
    """Forma (b): "n <numero> del <anno>", dopo il tipo. Nessuna data da
    leggere: "del" è solo il legamento fra numero e anno.
    """
    if len(resto) != 4:
        return None
    if resto[0] != "n":
        return None
    if not resto[1].isdigit():
        return None
    if resto[2] != "del":
        return None
    if not resto[3].isdigit() or not (1000 <= int(resto[3]) <= 9999):
        return None
    return _EstremiEstratti(tipo=tipo, anno=int(resto[3]), numero=int(resto[1]))


def _estremi_da_grafia_estesa(normalizzato: str) -> _EstremiEstratti | None:
    """Estrae (tipo, anno, numero) da una grafia GIÀ NORMALIZZATA che
    rispetti esattamente, token per token, una delle due forme estese:
    (a) "<tipo> <giorno> <mese> <anno> n <numero>";
    (b) "<tipo> n <numero> del <anno>".

    Qualunque scostamento dalla forma esatta non estrae nulla: la chiamata
    resta un alias sconosciuto, mai un tentativo parziale. Se due
    riconoscimenti diversi producessero estremi diversi dalla stessa
    stringa, non si estrae nulla: un'ambiguità sintattica si rifiuta come
    si rifiuta un'ambiguità di tabella.
    """
    token = normalizzato.split(" ")
    trovati: list[_EstremiEstratti] = []
    for parole, tipo in _TIPI_ESTESI:
        if len(token) <= len(parole) or tuple(token[: len(parole)]) != parole:
            continue
        resto = token[len(parole) :]
        estremi_a = _estremi_con_data_estesa(resto, tipo)
        if estremi_a is not None:
            trovati.append(estremi_a)
        estremi_b = _estremi_senza_data(resto, tipo)
        if estremi_b is not None:
            trovati.append(estremi_b)
    if not trovati:
        return None
    primo = trovati[0]
    if not all(e == primo for e in trovati):
        return None
    return primo


def _risultato_per_fonte(
    fonte: Fonte,
    articolo: Articolo | None,
    vigenza_alla_data,
) -> RisultatoLookup:
    """Costruisce il risultato per una fonte già trovata, sia per alias
    esatto sia per rimatch da grafia estesa: STESSO percorso, quindi
    necessariamente stesso URN (allegato compreso) e stesse avvertenze.
    """
    art = articolo if articolo is not None else Articolo(numero=1)
    urn = Urn(
        tipo=fonte.tipo,
        data=fonte.data,
        numero=fonte.numero,
        allegato=fonte.allegato,
        articolo=art,
        vigenza=vigenza_alla_data,
    )

    avvertenze: list[str] = []
    if fonte.stato == "abrogata" and fonte.nota_stato:
        avvertenze.append(f"fonte abrogata: {fonte.nota_stato}")
    if fonte.art1_e_preambolo and art.numero == 1 and art.estensione is None:
        avvertenze.append(
            "l'articolo 1 di questa fonte restituisce il preambolo di promulgazione, "
            "non il vero articolo 1 (docs/MISURE.md §4.1)"
        )
    return RisultatoLookup(urn=urn, fonte=fonte, avvertenze=tuple(avvertenze))


def risolvi_alias(
    grezzo: str,
    *,
    articolo: Articolo | None = None,
    vigenza_alla_data=None,
    tabella: TabellaFonti | None = None,
) -> RisultatoLookup:
    """Risolve un alias a un URN, con articolo opzionale (default: 1).

    Solleva `RiferimentoSconosciuto` se nessuna fonte corrisponde,
    `FonteNonDisponibileErrore` se la fonte è nota ma non su Normattiva.
    """
    tab = tabella if tabella is not None else carica_tabella()
    normalizzato = normalizza_alias(grezzo)

    for fonte in tab.verificate:
        if any(normalizza_alias(a) == normalizzato for a in fonte.alias) or (
            normalizza_alias(fonte.nome_canonico) == normalizzato
        ):
            return _risultato_per_fonte(fonte, articolo, vigenza_alla_data)

    for non_disp in tab.non_disponibili:
        if any(normalizza_alias(a) == normalizzato for a in non_disp.alias) or (
            normalizza_alias(non_disp.nome_canonico) == normalizzato
        ):
            raise FonteNonDisponibileErrore(non_disp)

    # Nessun alias esatto: prova a estrarre (tipo, numero, anno) da una
    # grafia estesa e RIMATCHARE la stessa tabella verificata — mai
    # costruire l'URN dagli estremi (quello perderebbe l'allegato per i
    # codici storici, producendo un link rotto).
    estratto = _estremi_da_grafia_estesa(normalizzato)
    if estratto is not None:
        # Zero o più di una corrispondenza: rifiuto, mai la fonte
        # sbagliata (collisione nota: regio.decreto 262/1942 è sia il
        # Codice Civile sia le Preleggi, differiscono solo per allegato).
        corrispondenze = [
            f
            for f in tab.verificate
            if f.tipo == estratto.tipo
            and f.numero == estratto.numero
            and _anno_atto(f) == estratto.anno
        ]
        if len(corrispondenze) == 1:
            return _risultato_per_fonte(corrispondenze[0], articolo, vigenza_alla_data)

    raise RiferimentoSconosciuto(f'Nessuna fonte normativa nota per "{grezzo}"')


def risolvi_riferimento(
    fonte: str, numero_articolo: str, vigenza: str | None = None
) -> RisultatoLookup:
    """Risolve "fonte" + "numero articolo" (grafia libera, es. "21novies") + una
    vigenza opzionale (YYYY-MM-DD) a un URN. UNICA sorgente di questo parsing:
    `cli.py` e `mcp_server.py` chiamano questa funzione, mai una copia propria
    (CLAUDE.md regola 6, "un valore, un simbolo" — vale anche per la logica di
    lettura, non solo per le costanti).

    Solleva `UrnNonValido` se il numero non inizia con cifre o l'estensione non
    è riconosciuta, e propaga `RiferimentoSconosciuto`/`FonteNonDisponibileErrore`
    da `risolvi_alias`.
    """
    cifre = ""
    for carattere in numero_articolo:
        if carattere.isdigit():
            cifre += carattere
        else:
            break
    if not cifre:
        raise UrnNonValido(f"numero dell'articolo non valido: {numero_articolo!r}")
    suffisso = numero_articolo[len(cifre) :]
    estensione = analizza_estensione(suffisso) if suffisso else None

    articolo = Articolo(numero=int(cifre), estensione=estensione)
    vigenza_alla_data = _date.fromisoformat(vigenza) if vigenza else None
    return risolvi_alias(fonte, articolo=articolo, vigenza_alla_data=vigenza_alla_data)
