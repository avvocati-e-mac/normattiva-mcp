# Tool MCP e output

## Tool locali

### `normattiva_stato_rete()`

Restituisce `rapporto` e `aggregati_giornalieri`. Non contatta Normattiva. Usalo
prima di ogni workflow con più consultazioni.

### `normattiva_trova_fonte(testo: str)`

Cerca nome e alias nella tabella verificata inclusa nel progetto. Un risultato
assente non dimostra che la fonte sia assente dall'ordinamento.

### `normattiva_link(..., verifica=false)`

Parametri: `fonte`, `articolo`, `vigenza` opzionale. Costruisce localmente il
Markdown e restituisce lo stato protettivo locale. Non prova esistenza o vigenza.

## Tool capaci di rete

### `normattiva_leggi_articolo(fonte, articolo, vigenza=None)`

Via preferita quando sono noti fonte e numero dell'articolo. `vigenza`, se usata,
deve essere `YYYY-MM-DD`.

### `normattiva_leggi_urn(urn)`

Usalo soltanto con un URN completo già disponibile. Quando si parte da fonte e
numero, preferisci `normattiva_leggi_articolo`.

### `normattiva_link(..., verifica=true)`

Costruisce la citazione Markdown e verifica l'URN attraverso lo stesso recupero
protetto del testo. È il comportamento predefinito.

## `protezione_rete`

Le risposte capaci di rete contengono:

- `origine`: `locale`, `rete` o `cache`;
- `acquisita_il`: data dell'acquisizione servita;
- `attivita`, `consumo_attivita`, `consumo_globale`;
- `richieste_residue`;
- `cooldown_fino` e `ultimo_incidente`;
- `livello`: `ok`, `attenzione`, `critico` o `bloccato`;
- `avviso`: frase leggibile sulla quota;
- `rapporti`: operazioni distinte compiute per la risposta.

`avvisi` può inoltre contenere avvertenze sulla fonte, quota consumata, abrogazione,
preambolo o vigenza storica. Un cache hit non deve produrre un nuovo avviso di
consumo.

## Fail closed

Se il database protettivo non è disponibile, la rete resta disabilitata. Durante
un cooldown o in modalità offline senza cache, non tentare vie alternative e non
continuare il workflow con altri strumenti di rete.
