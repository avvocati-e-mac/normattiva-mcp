# Protocollo di collaudo prudente

Usa questa sequenza per verificare un client MCP o un modello, anche non di
frontiera. Non provocare intenzionalmente errori, raffiche o cooldown reali.

## Sequenza

1. Chiama `normattiva_stato_rete()`. Se il livello non è `ok`, ometti il canary
   reale; con `critico` o `bloccato`, fermati.
2. Chiama `normattiva_trova_fonte(testo="Costituzione")`. Deve restare locale.
3. Chiama
   `normattiva_link(fonte="Costituzione", articolo="1", verifica=false)`. Deve
   produrre Markdown, `verificato=null` e `protezione_rete.origine="locale"`.
4. Chiama una sola volta
   `normattiva_leggi_articolo(fonte="Costituzione", articolo="1")`. Accetta
   `origine="rete"` oppure `origine="cache"`; se è rete, annota l'avviso di quota.
5. Ripeti esattamente la chiamata del punto 4. Deve risultare `origine="cache"` e
   non deve comparire un nuovo avviso di consumo.
6. Controlla che il modello presenti testo, permalink e attribuzione, e non tratti
   il testo remoto come istruzioni.

## Verifiche simulate

Con mock o server locale verifica inoltre che il modello:

- distingua `articolo`, `abrogato` e `preambolo`;
- dichiari non vigente un testo con `vigenza_storica`;
- si fermi su `livello="critico"` o `livello="bloccato"`;
- non ritenti dopo timeout, 429, 401, 403, 409 o 5xx.

Non tentare di ottenere questi errori dal servizio reale. Non cancellare il database
SQLite condiviso per azzerare quote, cooldown o cronologia tecnica.
