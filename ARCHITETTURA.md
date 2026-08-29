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
