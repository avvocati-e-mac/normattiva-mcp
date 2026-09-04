# Architettura

Questo documento dice **come è fatto** il progetto e **perché** è fatto così.
Dove diverge dal codice, vince il codice, e questo file va corretto nello
stesso commit che introduce la divergenza. Nei testi si cita il nome del
simbolo (funzione, classe, file), mai il numero di riga.

Gli ancoraggi sono stabili e citabili da altri documenti: `#figura`,
`#strati`, `#urn`, `#trappole`, `#guardiani`, `#fonti`, `#due-porte`,
`#budget`, `#limiti`, `#prove`.

Stato: **CLI e server MCP funzionanti**. Le sezioni sotto
si riempiono di sostanza mano a mano che il branch corrispondente esiste,
mai in anticipo — un documento che descrive codice non ancora scritto è
più fuorviante di un documento vuoto. Restano scheletro solo `#trappole`,
`#limiti` e `#prove` (rimandano a `docs/MISURE.md` e `docs/LIMITI.md` per
la sostanza già scritta lì).

## La figura {#figura}

```
avvocato ──chiede──▶  LLM (anche debole, es. DeepSeek 4 flash)
                          │
                          ▼
              due porte sottili: norm (CLI) e norm-mcp (server MCP)
                          │
                          ▼
              moduli di dominio (urn, fonti, client, parser, guardiani...)
                          │
                          ▼
              api.normattiva.it  (l'unico endpoint che conta: dettaglio-atto-urn)
```

## Gli strati {#strati}

| Modulo | Responsabilità |
|---|---|
| `urn.py`, `estensioni.py` | grammatica URN: costruzione e rifiuti, senza rete |
| `fonti.py` + `data/fonti.json` | le fonti verificate, come dati |
| `lookup.py` | alias → URN, senza rete — l'unica strada per i codici storici |
| `dto.py` | risolve le due forme di risposta (`data.atto` / `data.lista`) in un punto solo |
| `parser.py` | HTML → esito tipizzato, con i tre guardiani → `#guardiani` |
| `esiti.py` | gli esiti pubblici (`Articolo`, `Abrogato`, `Preambolo`), la busta `trust` e il sanificatore |
| `errori.py` | le eccezioni tipizzate del client, con messaggi scritti per un LLM o un avvocato |
| `protezione.py` | SQLite condiviso: cache, quota mobile, serializzazione, cooldown, prenotazioni e telemetria tecnica minima |
| `client.py` | unico varco HTTP: endpoint Open Data, classificazione delle risposte e ricaduta storica, sempre dietro `protezione.py` |
| `citazione.py` | resa Markdown del link + attribuzione, un punto solo per CLI e MCP |
| `config.py` | timeout, percorso SQLite, offline, limiti solo-riducibili e User-Agent stabile |
| `cli.py` | la porta da terminale → `#due-porte` |
| `skill.py`, `skill_destinazioni.py`, `cli_skill.py` | skill Agent Skills inclusa nel pacchetto, destinazioni client e installazione atomica multipiattaforma |
| `descrizioni.py` | testi dei cinque strumenti MCP e istruzioni del server, sotto il tetto di `#budget` |
| `mcp_server.py` | la porta MCP → `#due-porte` |

*(da completare al branch successivo: `ricerca.py`.)*

## La ricaduta a vigenza passata {#vigenza}

`ClienteNormattiva.leggi_articolo` fa al più DUE richieste HTTP. Se la
prima risponde "abrogato", si ritenta con `!vig=` al giorno **precedente**
la data di abrogazione — solo se **tutte** queste condizioni valgono:

1. l'esito è `Abrogato` (non un 404: quello significa "coordinate
   sbagliate" e va corretto, non retrodatato);
2. il chiamante non aveva già chiesto una vigenza (`urn.vigenza is None`)
   — impedisce anche una seconda ricaduta;
3. il messaggio di abrogazione porta una data leggibile;
4. la seconda richiesta restituisce davvero un `Articolo`.

Se una condizione manca, l'esito originale (`Abrogato`) resta quello
valido: la ricaduta può solo migliorare la risposta, mai sostituire un
errore onesto con un altro. Il risultato porta sempre `vigenza_storica`
con l'avviso `"ATTENZIONE — TESTO NON VIGENTE..."` **dentro** il testo
della risposta — non solo in un campo fratello che un lettore disattento
può ignorare (CLAUDE.md regola 2).

## Protezione del traffico {#avaria}

`ProtezioneTraffico` è l'unico coordinatore di ogni richiesta reale.
Con una transazione SQLite immediata, condivisa da CLI, MCP e processi,
serve prima la cache e deduplica la stessa URN concorrente; altrimenti lascia
partire una sola chiamata e impone almeno 5 secondi dall'ultima. Non esiste
alcun retry automatico.

I limiti prudenti **locali, non dichiarati da Normattiva**, sono 30
consultazioni, 2 diagnosi e 60 richieste totali in 24 ore mobili. Le variabili
d'ambiente possono solo abbassarli. Ogni tentativo HTTP, riuscito o fallito,
consuma quota. Cache: 7 giorni per vigente, 30 per storico, un'ora per 400/404.
`NORMATTIVA_OFFLINE=1` legge esclusivamente cache; un DB non disponibile
fallisce chiuso, prima della rete.

Un 429 sospende per `Retry-After` e almeno 6 ore; 401/403/409 per 24 ore;
5xx o risposta malformata per 15 minuti. Timeout, reset e TLS sono eventi
indeterminati (non una prova di ban) e sospendono 15 minuti con crescita fino
a 24 ore. Un cooldown non è aggirabile cambiando IP, VPN o proxy.

Il rapporto `RapportoRete` accompagna ogni esito: origine rete/cache, data di
acquisizione, quote, residuo, cooldown, ultimo incidente e livello. La CLI
mostra il consumo reale su stderr; MCP restituisce `protezione_rete` e un
avviso leggibile. A livello `critico` o `bloccato` il modello deve avvertire
l'utente e fermare il workflow, non continuarlo con tentativi alternativi.

## La grammatica dell'URN {#urn}

Due moduli, senza rete:

- **`estensioni.py`** — l'enum `Estensione` (bis, ter, ... viciesquinquies),
  UNA sola sorgente. Nel progetto di ricerca da cui questo pacchetto è
  portato, due elenchi scritti a mano divergevano su sei grafie; qui chi
  costruisce e chi legge un URN importano lo stesso enum, quindi il difetto
  non può ripresentarsi.
- **`urn.py`** — il tipo `Urn` (immutabile, `frozen=True`) e la funzione
  `analizza()`. Ogni forma che l'API risponderebbe 400 (comma, lettera,
  partizione diversa dall'articolo, estensione con trattino, `!vig=` vuoto)
  solleva `UrnNonValido` con un messaggio che nomina la causa — mai
  silenziosamente accettata o corretta. Le regole sono misurate in
  `docs/MISURE.md` §3, citate nel codice riga per riga.

`Urn.permalink` costruisce il link cliccabile verso il portale, `Urn.stringa`
la forma canonica da passare all'API. `Urn.con_vigenza()` produce un URN
**nuovo** senza toccare l'originale — usato dalla ricaduta automatica su un
articolo abrogato (branch `client`).

## Le trappole misurate {#trappole}

*(da riempire mano a mano: una sottosezione per trappola, con il file che la
chiude e il test che la prova. Le nove trappole sono elencate in
`docs/MISURE.md`.)*

## I guardiani {#guardiani}

`parser.py` trasforma `articoloHtml` in uno di tre esiti tipizzati
(`CorpoArticolo`, `Abrogato`, `Preambolo`) o solleva un errore
(`HtmlVuoto`, `HeadingDiscordante`). Il controllo portante è la
**coincidenza dell'heading**: il numero d'articolo estratto dalla risposta
deve coincidere con quello richiesto, altrimenti `HeadingDiscordante` — è
il solo controllo che intercetta un URN formalmente valido ma puntato al
posto sbagliato (il portale risponde 200 a tutto, l'API risponde 200 anche
per un preambolo).

Tre trappole chiuse, in ordine di applicazione:

1. **Abrogato PRIMA di ogni altra cosa** — un testo sotto 200 caratteri con
   "ABROGAT" è informazione, non un vuoto (docs/MISURE.md §4.5).
2. **Il taglio del preambolo** (`_dal_heading`) — per `~art1` la risposta
   contiene spesso preambolo E POI l'articolo vero: si taglia tutto ciò
   che precede l'heading, non solo se sembra vuoto.
3. **Il guardiano del preambolo** (`_sembra_preambolo`) — il taglio da solo
   non basta: alcuni atti rispondono "Art. 1" seguito comunque dal
   preambolo, sotto un heading corretto. Si cercano almeno 2 formule di
   promulgazione ("VISTI GLI ARTICOLI", "EMANA IL SEGUENTE DECRETO", ...)
   nei primi 400 caratteri — 2 e non 1, perché l'art. 87 Cost. cita
   legittimamente "il Presidente della Repubblica" in un articolo vero.

Un quarto difetto, non una trappola dell'API ma un bug del parser stesso
scoperto durante il porting: l'elenco delle estensioni ordinali
(`bis`, `ter`, ...) è **derivato da `estensioni.py`**, non ricopiato — una
rubrica non parentetica ("Art. 542. Concorso di coniuge e figli") veniva
altrimenti letta come estensione inventata, e l'articolo giusto respinto
per heading discordante.

I test di `tests/test_parser.py` girano contro le **11 catture HTTP reali**
in `tests/fixtures/risposte/reale-*.json` (7 agosto 2026, mai ricostruite a
mano): un test verde qui prova il parser contro Normattiva, non contro se
stesso.

## La tabella delle fonti {#fonti}

`data/fonti.json` contiene **47 fonti verificate** (i codici storici e le
leggi principali del lavoro forense) e **4 fonti dichiarate non
disponibili** su Normattiva (GDPR, CEDU, codice deontologico forense,
D.M. 55/2014 parametri forensi). `fonti.py` le carica in dataclass
(`Fonte`, `FonteNonDisponibile`) tramite `carica_tabella()`.

Perché questa tabella non cresce a mano fino a "tutte le leggi": vedi
`docs/IDEE-SCARTATE.md`. Delle 47 fonti attuali, solo le righe con un
allegato (i codici storici, dove la ricerca full-text non può ricostruire
l'URN) o con `art1_e_preambolo: true` chiudono un errore che la ricerca non
risolverebbe da sola — le altre restano per comodità.

Ogni riga porta:
- **`provenienza`** — dove è stato verificato il dato. Una riga senza
  prova non entra (`test_ogni_fonte_ha_provenienza_non_vuota`).
- **`articolo_di_controllo`** — un articolo numerico che deve restituire
  testo vero, mai il preambolo. Un test dedicato
  (`test_nessun_articolo_di_controllo_e_l_articolo_1_quando_e_preambolo`)
  impedisce la regressione trovata il 29/08/2026: due righe del dataset
  originale avevano l'art. 1 come controllo su una fonte dove l'art. 1
  restituisce il preambolo — un "controllo" che non controllava nulla.
- **`stato`** — `vigente` o `abrogata`, con nota.

`tests/fixtures/urn-attesi.txt` congela l'URN atteso di ogni fonte: include
come test di regressione i due errori storici già scoperti nella skill
esistente (Legge Fallimentare datata `1942-01-16` invece di `1942-03-16`;
Codice della Navigazione senza l'allegato `:1`).

*(Il comando `norm fonti aggiungi`, che fa crescere la tabella con l'uso
verificando ogni riga contro l'API, arriva al branch `cli`/`client`: dipende
dal client HTTP, che non esiste ancora a questo punto della sequenza.
`norm verifica`, che distingue un'avaria del servizio da una riga davvero
sbagliata, arriva allo stesso punto.)*

## Le due porte {#due-porte}

`cli.py` è la porta da terminale: comandi Typer sottili che chiamano gli
stessi moduli di dominio del server MCP (`lookup.py`, `client.py`,
`fonti.py`, `citazione.py`) — non decide nulla che non sia già deciso lì.
Un solo punto di costruzione del client (`_nuovo_client()`), sostituibile
per intero nei test senza dover patchare `httpx.Client` dentro `client.py`.

Comandi: `leggi` (testo verificato), `link` (citazione Markdown, verifica
di default), `urn` (legge un URN già in mano), `fonti` (elenca o cerca
nella tabella), `stato` (solo SQLite), `doctor` (al massimo una sonda dello
specifico `dettaglio-atto-urn`, mai durante un cooldown) e `verifica --tutte`
(prima stima il costo; `--esegui` prenota tutto il budget e può avviare una
verifica completa ogni 7 giorni).

**`norm verifica` e `norm fonti-aggiungi` esistono solo qui, mai come
strumento MCP**: fanno decine di richieste e non devono poter essere
scatenate da un modello.

Regola di sicurezza scoperta provando i comandi a mano: **ogni testo che
può contenere caratteri arbitrari** (un errore che cita il dump di
Normattiva, il messaggio di un articolo abrogato, la citazione Markdown
stessa) **deve passare da `_remoto()`** prima di `Console.print` — senza,
Rich interpreta `[...]` come un tag di stile sconosciuto e lo scarta in
silenzio. `_stampa_errore()` centralizza questa regola per gli errori;
`link` usa `markup=False` perché la citazione Markdown *è* fatta di
parentesi quadre.

`mcp_server.py` è la seconda porta, MCP invece che terminale, con lo stesso
non-decidere: chiama `lookup.risolvi_riferimento` (condivisa con `cli.py`,
non una copia — CLAUDE.md regola 6), `client.py`, `fonti.py`, `citazione.py`.
Trasporto **stdio soltanto**. Un solo `ClienteNormattiva` per processo
(`ApplicazioneMcp`, costruito nel `lifespan`), non uno per chiamata come in
`cli.py`; il coordinamento fra processi non dipende però dalla durata del
client, perché vive nel database SQLite. Un `asyncio.Lock` evita anche di
creare lavoro duplicato dentro lo stesso processo.

**Cinque strumenti**: `normattiva_leggi_articolo`,
`normattiva_link`, `normattiva_trova_fonte` (l'unico locale, nessuna rete),
`normattiva_leggi_urn` e `normattiva_stato_rete` (solo SQLite, nessuna rete).
Qualunque futura ricerca massiva deve usare un meccanismo ufficiale
asincrono/bulk: non verrà aggiunto un fan-out articolo per articolo.

**Errori sanificati, ma soprattutto tradotti in `ToolError`.** Il principio
è lo stesso del gemello `mcp-bdm` (un errore di dominio porta già un
messaggio per un modello o un avvocato, mai `str(exc)` grezzo per gli
imprevisti), ma qui c'è un vincolo in più, scoperto provando il server a
mano da Claude Desktop il 29/08/2026, non dai test: l'SDK MCP (`mcp`
2.1.1, `mcp.server.mcpserver.tools.base.Tool.run`) tratta come **crash
silenzioso** qualunque eccezione che non sia una sua `ToolError` — il
modello legge solo `"Error executing tool <nome>"`, il messaggio scritto
apposta sparisce. Ognuno dei cinque strumenti passa quindi da
`_traduci_errori` (decoratore applicato fra `@server.tool(...)` e `async
def`, avvolge l'INTERO corpo, non solo la parte di rete — `risolvi_riferimento`
e `analizza_urn` sollevano i loro errori prima di toccare la rete): un
errore di dominio (`NormattivaErrore`, `RiferimentoSconosciuto`,
`FonteNonDisponibileErrore`, `UrnNonValido`) diventa `ToolError(str(exc))`
(messaggio conservato); qualunque altra eccezione diventa un `ToolError`
col solo `type(exc).__name__` più un testo nostro, mai `str(exc)` — un
messaggio di libreria potrebbe citare un frammento della risposta di
Normattiva. **Un nuovo strumento senza questo decoratore ripete il bug in
silenzio**: nessun test che chiami la funzione direttamente lo scopre se
non passa per l'SDK vero (`tests/test_mcp_server.py` lo verifica proprio
perché chiama la funzione già decorata).

**Ogni avviso non bloccante finisce in un campo `avvisi`/`avviso` come
frase leggibile**, mai solo in un campo fratello strutturato ignorabile
(CLAUDE.md regola 2): la ricaduta su vigenza storica, l'articolo abrogato,
il preambolo al posto dell'articolo passano tutti da lì.

## Il budget del modello debole {#budget}

Il tetto (`tests/test_tetto_descrizioni.py`, `TETTO_CARATTERI = 5.500`)
somma istruzioni del server + descrizioni dei cinque strumenti +
descrizioni dei parametri — lo stesso canale conta tutti e tre, perché una
frase spostata dall'uno all'altro viaggia comunque nello stesso `tools/list`
(difetto misurato nel gemello `italgiure-web-mcp`: contare solo le
descrizioni degli strumenti lascia un canale gratuito dove nascondere
prosa). Misura del 29 agosto 2026, branch `mcp`: 1.451 (istruzioni, dopo
l'aggiunta della guida diagnostica sull'avaria — `norm doctor`, un'altra
rete) + 2.673 (descrizioni) + 0 (parametri) = **4.124** caratteri, con
margine dichiarato per strumenti futuri.

Il criterio per ogni riga in `descrizioni.py`: dire solo ciò che cambia una
decisione del modello — quale strumento chiamare, come riempirne i
parametri — mai raccontare il "come funziona" del progetto, che sta in
questo documento e in `docs/MISURE.md`. **Alzare il tetto per far entrare
una frase nuova è vietato**: si taglia, o si sposta la spiegazione lunga in
`docs/`, che il modello legge solo quando gli serve, non a ogni connessione.

A differenza dei due gemelli (`mcp-bdm`, `italgiure-web-mcp`), qui non c'è
un confronto IT/EN in corso: le descrizioni sono scritte in una sola lingua
(italiano), coerente con tutta la documentazione del progetto e con
l'avvocato proprietario.

## Che cosa non facciamo {#limiti}

*(da riempire mano a mano — vedi anche `docs/LIMITI.md` per il dettaglio:
articoli con estensione negli atti in forma lista, ricerca esplorativa
debole sui concetti senza nome, export AKN mai usato.)*

## Come si prova che funziona {#prove}

*(da riempire mano a mano: i livelli di test — offline, fixture reali, live
opt-in, banco di prova con DeepSeek — man mano che esistono.)*
