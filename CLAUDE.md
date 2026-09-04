# CLAUDE.md — mappa del progetto

Questo file è la mappa: dice **cosa leggere prima di cosa**. La fotografia di
come funziona davvero il sistema — cioè il "come" e il "perché" — sta in
[ARCHITETTURA.md](ARCHITETTURA.md). Se questo file e il codice divergono,
**vince il codice**, e questo file va corretto nello stesso commit che lo fa
divergere.

## Missione

Un server MCP e una riga di comando che permettono a un LLM — **anche non di
frontiera, in particolare DeepSeek 4 flash** — di trovare, leggere, verificare
e citare norme italiane da Normattiva.it, restituendo link URN in Markdown.

Il proprietario è un **avvocato, non un tecnico**: ogni messaggio d'errore,
ogni riga di documentazione rivolta a lui deve spiegare esiti e limiti con
linguaggio concreto, mai con un codice nudo.

Il progetto è **pubblico**, a differenza dei suoi due progetti gemelli
(`mcp-bdm`, `italgiure-web-mcp`, entrambi privati). Codice sotto licenza MIT;
i dati che gli strumenti restituiscono sono di Normattiva.it (Istituto
Poligrafico e Zecca dello Stato) sotto licenza CC BY 4.0 — le due licenze
sono distinte e vanno dichiarate entrambe (vedi README.md).

## Documenti da leggere prima di modificare

Non si leggono tutti ogni volta. Questa è la mappa: a sinistra ciò che stai
per fare, a destra ciò che devi avere letto prima di farlo.

| Prima di… | leggi… |
|---|---|
| toccare `urn.py` o `estensioni.py` | `docs/MISURE.md`, sezione sulla grammatica URN |
| toccare `parser.py` o `guardiani.py` | `docs/MISURE.md`, sezione sulle trappole, **e** le fixture in `tests/fixtures/risposte/` |
| toccare `client.py` | `docs/MISURE.md`, sezione sull'API e sui tre tipi di 404/500 |
| toccare `protezione.py` o i limiti di rete | [ARCHITETTURA.md](ARCHITETTURA.md#avaria) e README.md, poi i test offline in `tests/test_protezione.py` |
| toccare `fonti.py` o `data/fonti.json` | la regola della provenienza qui sotto |
| toccare `descrizioni.py` | il test del tetto di caratteri, prima di aggiungere una riga |
| una decisione architetturale non coperta | [ARCHITETTURA.md](ARCHITETTURA.md), poi `docs/IDEE-SCARTATE.md`; se anche lì manca, si chiede al proprietario, non si inventa |
| capire cosa NON funziona | `docs/LIMITI.md` |

## Se documento e codice divergono, vince il codice

E il documento si corregge nello stesso commit che lo fa divergere. Nei
documenti si cita il **nome del simbolo** (funzione, classe, file), mai il
numero di riga: i numeri invecchiano, i nomi no.

## Le regole vincolanti

1. **Mai un testo plausibile al posto di un errore.** Un preambolo non è un
   articolo anche se l'API risponde 200. Un guardiano che lo lascia passare
   è un difetto grave, non un dettaglio.
2. **Mai un troncamento, una vigenza o un'avvertenza silenziosa.** Se un
   risultato viene tagliato, retrodatato, o è incerto, lo si dice nel testo
   della risposta — un campo fratello ignorabile non basta.
3. **Misurato ≠ dato storico noto ≠ inferito**: ogni fatto tecnico dichiara
   quale dei tre è, con la data della misura quando c'è.
4. **Il permalink del portale non si scarica mai.** È 2.000 volte più pesante
   dell'API per lo stesso contenuto (vedi `docs/MISURE.md`).
5. **Un URN non si valida cliccandoci sopra.** Il portale risponde 200 anche
   a URN sbagliati. Solo l'API discrimina.
6. **Un valore, un simbolo.** Base URL, cifre misurate, messaggi di
   attribuzione: ognuno vive in un punto solo (`config.py`, `misure.py`,
   `citazione.py`), mai ricopiato.
7. **Chi aggiunge una fonte alla tabella scrive la provenienza e un
   articolo di controllo.** Una riga senza prova non entra.
8. **Rete prudente e fail-closed.** Ogni HTTP passa da `ProtezioneTraffico`;
   niente retry automatici, scraping HTML, browser automation, proxy o cambio
   IP/VPN. Un cooldown o un livello `critico`/`bloccato` impone di avvertire
   l'utente e fermare il workflow.
9. **I limiti sono locali.** Le soglie 30/2/60 sono cautele del progetto,
   non limiti dichiarati da Normattiva; possono solo essere ridotte. Prima di
   aumentare volume o servire terzi servono istruzioni scritte del gestore.

## Struttura e stile del codice

File piccoli, uno scopo ciascuno (nessuno oltre ~330 righe). Le due porte —
`cli.py` e `mcp_server.py` — sono sottili: traducono input e output, non
decidono; non si chiamano fra loro, chiamano entrambe gli stessi moduli di
dominio. Dettagli e motivazioni di ogni divisione: [ARCHITETTURA.md](ARCHITETTURA.md#strati).

## Il tetto sul sapere consegnato al modello

Le descrizioni degli strumenti MCP sono sotto un tetto di caratteri
verificato da un test (`tests/test_tetto_descrizioni.py`). Il criterio: si
scrive solo ciò che cambia una decisione del modello. **Alzare il tetto per
far entrare testo nuovo è vietato: si taglia.** Dettagli in
[ARCHITETTURA.md](ARCHITETTURA.md#budget).

## Commit atomici, un branch per funzione

Ogni commit rappresenta una sola intenzione reversibile. Un branch per
funzione, fuso su `main` prima del successivo. Prima di committare: leggere
`git diff --staged` per intero, verificare che test e lint passino, includere
test e documentazione nello stesso commit del codice che descrivono.

## Regole di release

Il titolo della release GitHub contiene soltanto il tag di versione (`vX.Y.Z`),
senza commenti. Le note includono sempre il comando `uv tool install` puntato
alla wheel della stessa release e dichiarano che installa sia `norm` sia
`norm-mcp`. Si allegano wheel e sdist ricostruiti dal commit taggato, con i
relativi SHA-256. `logs/`, database e telemetria locale non entrano mai nella
release.

## Come si esegue

```sh
uv sync --extra dev
uv run pytest                                    # suite offline
NORMATTIVA_LIVE_TESTS=1 uv run pytest tests/live -m live   # opt-in, richieste reali
uv run norm --help
uv run norm-mcp --help
```
