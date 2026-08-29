# Idee scartate

Cosa è stato considerato e perché non è nel progetto. Serve a non
riproporre la stessa idea senza sapere che è già stata verificata e
respinta.

## Scaricare il permalink del portale per ottenere il testo

Scartato: 2.013 volte più pesante dell'API per lo stesso contenuto, e
restituisce l'atto intero, non l'articolo (vedi `docs/MISURE.md` §2).

## Usare `ricerca/avanzata` invece di `ricerca/semplice`

Scartato: dà connection reset riproducibile in ogni prova (vedi
`docs/MISURE.md` §6). Non è chiaro se sia un difetto lato server o un
comportamento intenzionale contro un pattern di richiesta; in ogni caso non
utilizzabile.

## Esporre l'export AKN come strumento

Scartato: richiede una sessione applicativa che l'API dati non prevede, ed è
sempre l'atto intero (oltre 10 MB per il codice civile). Nessun vantaggio
sul singolo articolo rispetto a `dettaglio-atto-urn`. Vedi
`docs/LIMITI.md`.

## Un tool `normattiva_commi` per leggere singoli commi

Scartato: i commi e le lettere non esistono come partizione indirizzabile
dall'API (`~art18-com1` → 400 sempre, misurato). Un tool che promette questa
capacità mentirebbe. Il parametro "comma" non compare in nessuno schema di
input: reso irrappresentabile, non rifiutato a runtime.

## Un tool `normattiva_grafo_rinvii` per seguire i rimandi normativi

I link `<a href="...uri-res/N2Ls?urn:nir:...">` dentro `articoloHtml` sono
interessanti (un grafo dei rinvii fra norme), ma non chiudono nessuna
trappola già misurata. `normattiva_leggi_urn` copre già il caso d'uso "ho
trovato un URN nel testo, voglio leggerlo" senza bisogno di un tool dedicato
al grafo. Rimandato: si riconsidera solo se emerge un bisogno reale, non a
tavolino.

## Unificare `normattiva_leggi_articolo` e `normattiva_leggi_urn` in un solo tool

Scartato. Unificarli richiederebbe due parametri mutuamente esclusivi
(`fonte`+`articolo` oppure `urn`) — la forma che un modello debole confonde
più spesso, lo stesso motivo per cui il parametro "comma" è irrappresentabile
invece che rifiutato a runtime. I due tool partono anche da input diversi:
`leggi_articolo` dal linguaggio dell'avvocato, `leggi_urn` da una stringa
tecnica già in mano (es. un rinvio trovato in un testo).

## Ampliare a mano la tabella delle fonti fino a coprire "tutte le leggi"

Scartato. L'archivio di Normattiva conta decine di migliaia di atti (una
sola parola come "decreto" ne trova quasi 89.000): mille righe scritte a
mano sposterebbero la copertura dallo 0,05% a poco più, per settimane di
lavoro che invecchia da solo. Misurato: delle 47 fonti iniziali solo 16
chiudono un errore che la ricerca non risolverebbe da sola (gli 8 codici
storici con allegato più 8 con un avviso di abrogazione/preambolo da
conoscere in anticipo). La tabella resta il caso speciale, non l'elenco
generale; cresce con l'uso tramite `norm fonti aggiungi`, mai a tavolino.

## Un fallback Playwright/browser sul permalink del portale durante un'avaria API

Considerato dopo l'avaria del 29/08/2026 (`docs/MISURE.md` §7, §7.1, §7.2).
Scartato per ora: quel giorno stesso ha prodotto la prova più forte contro
l'idea. La prima avaria (§7, ~10 minuti) ha colpito solo
`dettaglio-atto-urn`, lasciando il portale raggiungibile — l'unico scenario
in cui un fallback browser avrebbe avuto un bersaglio. La seconda (§7.1,
§7.2, ~25+ minuti, la maggioranza del tempo osservato) ha portato giù
l'intero dominio `normattiva.it` a livello TCP, portale incluso — confermato
con `curl` puro e con un browser Chrome reale, che si è comportato in modo
identico a `httpx`. API e portale condividono lo stesso dominio e
verosimilmente la stessa infrastruttura di origine: non sono superfici di
guasto indipendenti, quindi un fallback che assume "l'uno può cadere senza
l'altro" scommette contro la correlazione strutturale osservata, non solo
contro la sfortuna di un giorno.

Anche nello scenario favorevole, il costo di farlo con sicurezza è alto
quanto il lavoro già fatto per l'API: il portale è un HTML diverso
(l'atto intero impaginato, non `articoloHtml`), servirebbe il suo proprio
guardiano dell'heading (CLAUDE.md regola 1, regola 5 — §4.8 mostra che il
portale risponde 200 anche a un URN con l'anno sbagliato, restituendo un
atto diverso senza segnalarlo) e le sue fixture reali, in un secondo
`parser.py` per un percorso atteso attivarsi qualche minuto l'anno. Resta
anche 2.000× più pesante per lo stesso contenuto (`docs/MISURE.md` §2,
CLAUDE.md regola 4): un'eccezione così rara non ripaga il costo di
manutenzione di un secondo estrattore.

Si riconsidera solo se si accumulano più osservazioni indipendenti di
un'avaria selettiva (solo API, portale su) — non a tavolino da un singolo
episodio — e solo con la sua propria misura in `docs/MISURE.md`, i suoi
guardiani, e un marchio di trust distinto da `TRUST_ESTERNO` (es.
`external_source_scraped_unverified`) che dichiari il testo come non
passato dai controlli di `parser.py`. Nel frattempo, il guadagno diagnostico
reale e a basso costo è estendere `norm doctor` a distinguere "solo
l'endpoint dati è giù" da "tutto il dominio è giù", non a servire testo
scaricato dal portale.
