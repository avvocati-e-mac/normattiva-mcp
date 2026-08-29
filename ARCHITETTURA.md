# Architettura

Questo documento dice **come è fatto** il progetto e **perché** è fatto così.
Dove diverge dal codice, vince il codice, e questo file va corretto nello
stesso commit che introduce la divergenza. Nei testi si cita il nome del
simbolo (funzione, classe, file), mai il numero di riga.

Gli ancoraggi sono stabili e citabili da altri documenti: `#figura`,
`#strati`, `#urn`, `#trappole`, `#guardiani`, `#fonti`, `#due-porte`,
`#budget`, `#limiti`, `#prove`.

Stato: **impianto iniziale**. Le sezioni sotto sono scheletri: si riempiono
di sostanza mano a mano che il branch corrispondente esiste, mai in anticipo
— un documento che descrive codice non ancora scritto è più fuorviante di un
documento vuoto.

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

*(da riempire al branch `impianto` → `grammatica-urn`: elenco dei moduli con
una riga di responsabilità ciascuno, mano a mano che nascono.)*

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

*(da riempire al branch `parser`: preambolo, abrogato, heading discordante.)*

## La tabella delle fonti {#fonti}

*(da riempire al branch `tabella-fonti`: formato di `data/fonti.json`, la
regola della provenienza, come `norm verifica` distingue un'avaria del
servizio da una riga davvero sbagliata.)*

## Le due porte {#due-porte}

*(da riempire ai branch `cli` e `mcp`: cosa sta nel tool MCP, cosa nella
risposta, perché CLI e server non si chiamano fra loro.)*

## Il budget del modello debole {#budget}

*(da riempire al branch `mcp`: il tetto di caratteri, i quattro livelli di
costo, come si misura con il banco di prova.)*

## Che cosa non facciamo {#limiti}

*(da riempire mano a mano — vedi anche `docs/LIMITI.md` per il dettaglio:
articoli con estensione negli atti in forma lista, ricerca esplorativa
debole sui concetti senza nome, export AKN mai usato.)*

## Come si prova che funziona {#prove}

*(da riempire mano a mano: i livelli di test — offline, fixture reali, live
opt-in, banco di prova con DeepSeek — man mano che esistono.)*
