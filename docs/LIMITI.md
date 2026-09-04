# Limiti noti — dichiarati, non nascosti

Ciò che questo progetto **non** sa fare, o non fa bene. Un limite dichiarato
qui è preferibile a un errore silenzioso: un avvocato che sa cosa lo
strumento non copre può cercare altrove; uno che riceve una risposta
sbagliata con l'aria di essere giusta no.

## Articoli con estensione negli atti in forma "lista" sono irraggiungibili

TUEL (art. 147-bis, 147-ter, 147-quinquies, 243-bis, 6-bis), D.P.R. 380/2001
— T.U. Edilizia (art. 6-bis, 23-bis, 34-bis). Misurato: 6 casi su 27 provati
danno 404, anche passando `!vig=`. Vedi `docs/MISURE.md` §4.9. Nessuna via di
recupero trovata: l'articolo esiste nella legge ma l'API non lo indirizza
quando l'atto risponde nella forma "lista" invece che "atto singolo".

**Comportamento del programma**: un errore dedicato che dice esplicitamente
che è un limite noto di Normattiva, non un difetto di questo strumento, e
che l'articolo esiste comunque (solo non raggiungibile per questa via).

## La ricerca full-text è debole sui concetti senza nome proprio

"Whistleblowing", "responsabilità extracontrattuale" e simili non trovano
l'atto giusto in modo affidabile — la ricerca lavora sul titolo e sul testo
dell'atto, non è un motore semantico. Funziona bene per gli atti che hanno
già un nome ("codice della crisi d'impresa", "equo compenso"). Vedi
`docs/MISURE.md` §6.

## I codici storici non sono ricostruibili dalla ricerca

Il numero di allegato (es. `:2` per il codice civile) non compare in nessun
campo restituito dalla ricerca. Per questi atti l'unica via affidabile è la
tabella delle fonti verificate (`normattiva_trova_fonte`).

## L'export Akoma Ntoso (AKN) non è usato

`GET /do/atto/caricaAKN` sul portale richiede una sessione applicativa (a
freddo restituisce 200 con una pagina di errore) ed è sempre l'atto intero,
mai il singolo articolo — per il codice civile pesa oltre 10 MB. Nessun
vantaggio rispetto all'API per articolo.

## L'export via API richiede conferma e-mail

La catena `ricerca-asincrona/nuova-ricerca` → `conferma-ricerca` →
`check-status` → download richiede un token confermato via e-mail:
inutilizzabile in un flusso interattivo con un LLM.

## Da verificare: tre tipi di allegati per i codici (non ancora misurato)

Un progetto di terzi esaminato il 29/08/2026 (ispezione informativa, nessun
codice copiato) distingue tre concetti diversi per un codice storico:
disposizioni di attuazione, disposizioni di coordinamento/transitorie, e
regolamento di esecuzione — non tutti i codici li hanno tutti (es. il c.p.c.
ha attuazione e transitorie, il c.p. solo coordinamento, il c.p.p. solo un
regolamento). La tabella attuale (`data/fonti.json`) non distingue questi
tre casi come voci separate. Non è chiaro se serva: nessuna misura diretta
lo ha ancora richiesto. Da verificare se e quando un caso reale lo chiede,
non da implementare a tavolino.

## L'endpoint può andare in avaria senza preavviso

Il BFF (`bff-opendata`) non è un'API pubblica versionata con un contratto
dichiarato. Il 29 agosto 2026 l'endpoint del testo ha dato un incidente
compatibile con un'avaria, ma non conclusivamente distinguibile da una
limitazione individuale (vedi `docs/MISURE.md` §7). Il programma registra
l'incertezza, applica un cooldown e non ritenta automaticamente; non può
prevenire né qualificare definitivamente l'evento.

## Le soglie di traffico sono locali, non un contratto del gestore

Le quote 30 consultazioni, 2 diagnosi e 60 richieste complessive in 24 ore
mobili sono una cautela deliberatamente conservativa di questo progetto. Non
derivano da una comunicazione di Normattiva e non vanno interpretate come un
permesso a raggiungerle. Possono essere abbassate dall'utente, non alzate da
flag CLI o strumenti MCP.

Il progetto non usa proxy, rotazione/cambio IP o VPN per aggirare cooldown e
non fa scraping HTML né browser automation. Un 429, un errore di autorizzazione
o un evento di trasporto fermano localmente i tentativi secondo la politica
documentata nel README. L'assenza di errori non autorizza aumenti automatici.

Prima di aumentare sostanzialmente i volumi o mettere il servizio a
disposizione di terzi, occorre chiedere al gestore indicazioni scritte su
limiti, canale bulk/asincrono e modalità preferite. Un'eventuale elaborazione
massiva futura dovrà usare esclusivamente quel canale ufficiale, non richieste
articolo per articolo.
