"""Errori tipizzati del client. Ogni messaggio è scritto per essere letto
da un LLM o da un avvocato, non solo per il debug: dice sempre COSA è
sbagliato e, dove serve, PERCHÉ.

I due 404 applicativi sono casi DISTINTI perché la reazione giusta è
diversa: `AttoInesistente` è definitivo, `CoordinateSbagliate` dice che
l'atto c'è e vale la pena riprovare con un altro allegato (docs/MISURE.md
§4.3). Il terzo 404 (`EndpointNonTrovato`) non parla dell'atto: parla di
noi — è un difetto del programma, mai una legge inesistente.
"""

from __future__ import annotations


class NormattivaErrore(Exception):
    """Radice comune di tutti gli errori del client."""


class AttoInesistente(NormattivaErrore):
    """404 breve (~43 byte): l'atto non esiste."""

    def __init__(self, urn: str) -> None:
        self.urn = urn
        super().__init__(f"Normattiva non ha questo atto: {urn}")


class CoordinateSbagliate(NormattivaErrore):
    """404 con dump (~170 byte): l'atto esiste, le coordinate (allegato o
    articolo) sono sbagliate — si può riprovare con un altro allegato."""

    def __init__(self, urn: str, dump: str) -> None:
        self.urn = urn
        self.dump = dump
        super().__init__(
            f"L'atto esiste ma le coordinate sono sbagliate (allegato o articolo): {urn}"
        )


class EndpointNonTrovato(NormattivaErrore):
    """404 del GATEWAY, non dell'applicazione: stiamo chiamando un
    indirizzo che l'API non espone. È un difetto del programma, non una
    legge inesistente — misurato: 128 byte, chiave `description` con
    "No matching resource found for given API Request"."""

    def __init__(self, dettaglio: str) -> None:
        self.dettaglio = dettaglio
        super().__init__(
            f"Difetto del programma, non una legge inesistente: normattiva-mcp sta "
            f"chiamando un indirizzo che l'API di Normattiva non espone ({dettaglio}). "
            "Finché non viene corretto nel codice, la consultazione della norma non "
            "funziona: non concludere nulla da questo errore."
        )


class SintassiRifiutata(NormattivaErrore):
    """400: la sintassi dell'URN è stata rifiutata dall'API (commi,
    lettere, estensione con trattino, !vig= vuoto...). Non si ritenta mai:
    è una risposta corretta a una domanda malformata."""

    def __init__(self, urn: str, dettaglio: str | None = None) -> None:
        self.urn = urn
        base = f"Normattiva ha rifiutato la forma dell'URN (400): {urn}"
        super().__init__(f"{base} — {dettaglio}" if dettaglio else base)


class HttpInatteso(NormattivaErrore):
    """Un codice di stato che non rientra in nessuno dei casi previsti."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"Normattiva ha risposto {status}.")


class RispostaIllegibile(NormattivaErrore):
    """Il corpo non è JSON valido, o non contiene né data.atto né
    data.lista."""

    def __init__(self, dettaglio: str) -> None:
        self.dettaglio = dettaglio
        super().__init__(f"Risposta di Normattiva non interpretabile: {dettaglio}")


class TestoAssente(NormattivaErrore):
    """Nessun testo d'articolo in nessuna delle due forme di risposta."""

    def __init__(self, urn: str) -> None:
        self.urn = urn
        super().__init__(f"Normattiva ha risposto senza testo per {urn}.")


class ServizioInAvaria(NormattivaErrore):
    """500: il servizio è in avaria ADESSO. Non un giudizio sulla norma,
    non un giudizio su una fonte della tabella — solo un fatto temporaneo
    (docs/MISURE.md §7, misurato il 29/08/2026: l'endpoint del testo è
    stato giù per una decina di minuti mentre il resto dell'API
    funzionava). Mai un ritentativo automatico."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(
            f"Normattiva ha risposto {status}: il servizio è in avaria adesso, "
            "non un giudizio sulla norma cercata. Riprova più tardi."
        )


class GuastoDiTrasporto(NormattivaErrore):
    """Un guasto di rete/trasporto, dopo i ritentativi consentiti."""

    def __init__(self, dettaglio: str) -> None:
        self.dettaglio = dettaglio
        super().__init__(f"Errore di rete verso Normattiva: {dettaglio}")


class CircuitoAperto(NormattivaErrore):
    """Il circuit breaker ha sospeso le chiamate dopo guasti ripetuti."""

    def __init__(self, riapre_tra_secondi: float) -> None:
        self.riapre_tra_secondi = riapre_tra_secondi
        super().__init__(
            f"Normattiva è stata sospesa dopo guasti ripetuti: "
            f"riprova fra {int(riapre_tra_secondi)} s."
        )
