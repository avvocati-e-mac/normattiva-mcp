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
