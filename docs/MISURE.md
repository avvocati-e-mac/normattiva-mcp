# Misure — normattiva-mcp

Ogni fatto tecnico qui sotto è **misurato**, con la data, non dedotto dalla
documentazione ufficiale (che in almeno un punto è sbagliata — vedi §1). Le
misure di oggi sono coerenti con oltre 800 richieste reali documentate nel
progetto di ricerca `DS4-Chat` (agosto 2026), verificate di nuovo il
29 agosto 2026 durante la stesura di questo piano.

Regola per chi aggiunge una misura: **una richiesta spesa produce una riga
qui, nello stesso giorno**, con la data. Un fatto "riferito a voce" non
esiste per questo progetto.

---

## 1. L'endpoint vero, e perché la documentazione ufficiale è sbagliata

```
POST https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1/atto/dettaglio-atto-urn
Content-Type: application/json
Accept: application/json

{"urn": "urn:nir:stato:regio.decreto:1942-03-16;262:2~art2043"}
```

- **Nessuna chiave, nessuna registrazione.** Dati sotto licenza CC BY 4.0
  (Istituto Poligrafico e Zecca dello Stato).
- La documentazione ufficiale (`API_Normattiva_OpenData.pdf`, rev.
  09/01/2025) e la spec OpenAPI pubblicata su `dati.normattiva.it` dichiarano
  `server.url = http://localhost:9090/bff-opendata` — un indirizzo interno,
  inutilizzabile. **L'indirizzo vero è stato ricavato da
  `dati.normattiva.it/assets/env.js`**, il file di configurazione del
  portale (`window.env.url`), 29 agosto 2026.
- Il segmento `atto/` nel percorso è obbligatorio: senza, il gateway
  risponde 404 con `"No matching resource found for given API Request"`
  (misurato 29/08/2026).
- **Solo POST.** Un GET con `?urn=` non funziona.
- Solo due header servono: `Accept` e `Content-Type`. Nessun cookie, nessun
  User-Agent custom, nessun Referer (misurato in `DS4-Chat`, confermato
  29/08/2026).

## 2. Perché non si scarica mai il permalink del portale

Art. 2043 c.c., misurato 29/08/2026:

| Via | Peso | Contenuto utile | Tempo |
|---|---:|---|---:|
| API `dettaglio-atto-urn` | 1.287 byte | 180 caratteri: l'articolo esatto | 0,44 s |
| Permalink `uri-res/N2Ls?...` | 2.591.983 byte | tutto il codice civile, non segmentabile per articolo | ~3,3 s |

**Fattore ~2.013× in peso.** Per un modello con poca memoria di lavoro è la
differenza fra funzionare e non funzionare affatto.

## 3. Grammatica reale dell'URN (misurata, non documentata)

Formato: `urn:nir:stato:<tipo>:<data>;<numero>[:<allegato>]~art<N>[!vig=YYYY-MM-DD]`

| Regola | Prova (misurata in DS4-Chat, agosto 2026) |
|---|---|
| Commi e lettere **non esistono** | `~art18-com1`, `~art7-com1-letb` → 400 sempre |
| `bis`/`ter` **senza** trattino | `~art2645ter` → 200; `~art2645-ter` → 400 |
| Allegato obbligatorio per i codici storici | c.c. `262` senza `:2` → 404 con dump; c.c. `262:2` → 200 |
| Allegato **vietato** per il c.p.p. (D.P.R. 447/1988) | con `:1` → 404 |
| `!vig=` **senza** data | `~art17!vig=` → 400, nonostante la doc ufficiale la mostri |
| `@originale` | ignorato dall'API, risposta identica a senza suffisso |
| Partizioni `~all1`, `~pre`, `~dis1` | 400 tutte |
| `orderType` nella ricerca | non validato: valori arbitrari → risposte identiche |

Allegati verificati per i codici storici più usati: c.c. `262:2`, preleggi
`262:1`, c.p.c. `1443:1`, c.p. `1398:1`, l.fall. `267:1`, cod.nav. `327:1`.

## 4. Le nove trappole che il codice deve chiudere

### 4.1 `~art1` restituisce il preambolo, con HTTP 200

Misurato su almeno 13 atti. Nessuna avvisaglia nel codice di stato.

| URN | Caratteri restituiti | Cosa sono |
|---|---:|---|
| `decreto.legislativo:2001-06-08;231~art1` | 17.748 (misurato 29/08/2026) | «IL PRESIDENTE DELLA REPUBBLICA, Visti gli articoli 76 e 87…» |
| `decreto.legislativo:2008-04-09;81~art1` | 46.850 | preambolo |
| `legge:1970-05-20;300~art1` | 434 | «La Camera dei deputati ed il Senato hanno approvato» |
| `regio.decreto:1942-03-16;262:2~art1` (controllo) | — | ✓ «Art. 1. (Capacità giuridica)» — non affetto |

**Non affetti**: atti con allegato (c.c., c.p.c., c.p., l.fall., cod.nav.),
Costituzione, c.p.p., T.U. Edilizia, T.U.I.R., d.lgs. 50/2016.

Correzione importante: `~art1` non restituisce *solo* il preambolo, lo
restituisce **e poi** l'articolo vero. Per il d.lgs. 231/2001 l'HTML
completo è 26.174 caratteri e l'heading `article-num-akn` compare al
carattere 3.591 — il guardiano deve saper trovare l'articolo dopo il
preambolo, non solo rifiutare in blocco.

### 4.2 Due forme di risposta

Alcuni atti mettono il contenuto in `data.lista` (array di 2: testo
originario + ripubblicazione con note) invece che in `data.atto`.

| URN | Forma |
|---|---|
| `2023-03-31;36~art3` (codice appalti) | `data.atto = null`, `data.lista` = 2 elementi |
| `2000-08-18;267~art42` (TUEL) | idem |
| `2001-06-06;380~art10` (T.U. edilizia) | idem |
| `2001-06-08;231~art1` | `data.atto` valorizzato |

Un client che legge solo `data.atto` classifica tre voci corrette come
rotte — successo osservato durante il red team di agosto.

### 4.3 Tre tipi di errore distinti, distinguibili

| Risposta | Byte | Significato | Uso |
|---|---:|---|---|
| `{"message":"atto non trovato"}` | ~43 | l'atto non esiste | errore definitivo |
| `{"message":"dataPubblicazioneGazzetta:... codiceRedazionale:... idArticolo:... artP:0", "code":null}` | ~168-171 | l'atto esiste, le coordinate (allegato/articolo) sono sbagliate | si può ritentare con un altro allegato |
| `{"code":"404","type":"Status report","message":"Runtime Error","description":"No matching resource found..."}` | 128 | indirizzo dell'endpoint sbagliato | difetto nostro, non del dato |
| `{"message":"urn assente o non valido...", "code":"1003"}`, HTTP **400** | 171 | URN ben formato ma atto inesistente | errore definitivo, diverso dal 404 breve |
| `{"message":"Errore generico della chiamata, riprovare più tardi","code":"1000"}`, HTTP **500** | 80 | **il servizio è in avaria adesso** | mai un giudizio sulla riga, mai un ritentativo automatico — vedi §7 |

I tre nomi del dump (`codiceRedazionale`, `idArticolo`, `artP`) **non sono
chiavi JSON**: stanno dentro la stringa `message`, separati da spazi.

### 4.4 400 = URN ben formato ma atto inesistente

Distinto dal 404: un 400 con `code: "1003"` significa che la sintassi era
valida ma nessun atto corrisponde (es. numero di legge inventato).

### 4.5 Articoli abrogati: risposta corta, non vuota

| URN | Caratteri | Testo |
|---|---:|---|
| `917~art51` (T.U.I.R.) | 69 | «PROVVEDIMENTO ABROGATO DAL D.LGS. 19 GIUGNO 2026, N. 117» |
| `633~art19` (IVA) | 64 | «ARTICOLO ABROGATO DAL D.LGS. 19 GENNAIO 2026, N. 10» |
| `196~art13` (Privacy) | 64 | «ARTICOLO ABROGATO DAL D.LGS. 10 AGOSTO 2018, N. 101» |

**Trattare "corto" come "vuoto" è sbagliato**: è la firma dell'abrogazione.
Il testo storico si recupera con `!vig=` alla data del giorno precedente
l'abrogazione (misurato: art. 51 T.U.I.R. → 23.681 caratteri con
`!vig=2020-12-31`).

### 4.6 Tutto il tributario sostanziale risponde ABROGATO al testo di oggi

TUIR, IVA (D.P.R. 633/1972), D.Lgs. 546/1992 (processo tributario):
recuperabili solo passando `!vig=` a una data storica.

### 4.7 Il permalink non va mai scaricato

Vedi §2.

### 4.8 Il portale risponde 200 anche a URN sbagliati

| URN richiesto | Cosa mostra il portale |
|---|---|
| `legge:1970-05-20;300~art18` (corretto) | LEGGE 300/1970, 200 |
| `legge:1970-01-01;300~art18` (giorno sbagliato) | la stessa pagina, byte per byte, 200 |
| `legge:1971-05-20;300~art18` (**anno** sbagliato) | **D.P.R. 300/1971 — atto completamente diverso**, 200 |
| `urn:questo-non-e-un-urn` | pagina di errore, comunque 200 |

**Un URN non si valida cliccandoci sopra: solo l'API discrimina** (400/404
espliciti). Il portale non è mai uno strumento di verifica.

### 4.9 Articoli con estensione negli atti in forma lista sono irraggiungibili

TUEL (147-bis, 147-ter, 243-bis, 6-bis), d.p.r. 380/2001 (6-bis, 23-bis,
34-bis): 6 casi su 27 provati falliscono con 404 (dump coerente: l'API
capisce la richiesta ma non trova l'articolo). `!vig=` non recupera nulla
(404 breve, peggio del 404 con dump). **Limite noto, senza rimedio trovato**:
va dichiarato all'utente, non nascosto.

## 5. Multivigenza — la funzione più preziosa, e funziona ovunque

`!vig=AAAA-MM-GG` funziona su tutti i tipi di atto provati (Costituzione,
regio decreto, legge, decreto legislativo, decreto legge, D.P.R.), con
`articoloDataInizioVigenza` coerente (formato `yyyyMMdd`, senza trattini;
`99999999` = nessuna fine).

Art. 18 legge 300/1970, stesso endpoint, solo `!vig=` diverso:

| `!vig=` | Caratteri | Contenuto |
|---|---:|---|
| *(assente)* | 14.503 | testo vigente oggi |
| `2012-06-17` | 6.214 | pre-Fornero |
| `2015-03-06` | 12.974 | testo Fornero |
| `1990-01-01` | 2.446 | testo pre-1990 |

## 6. La ricerca (`ricerca/semplice`): forte sugli atti nominati, cieca sui codici

```
POST .../ricerca/semplice
{"testoRicerca": "...", "orderType": "", "filtriMap": {},
 "paginazione": {"paginaCorrente": 1, "numeroElementiPerPagina": N},
 "limitaAnniVigenza": false}
```

(Nota: lo schema usa `paginaCorrente`/`numeroElementiPerPagina`, non i nomi
che appaiono nella spec OpenAPI generata da `dati.normattiva.it`, che è
`Paginazione` con quegli stessi campi — verificato leggendo il bundle
Angular del portale, 29/08/2026.)

Misurato oggi su sei atti **fuori** dalla tabella delle fonti (codice
comunicazioni elettroniche, T.U. bancario, codice del consumo, CAD): la
ricerca trova l'atto e l'URN ricostruito dai suoi campi (`denominazioneAtto`,
`giornoProvvedimento`, `meseProvvedimento`, `annoProvvedimento`,
`numeroProvvedimento`) funziona **4 casi su 4** provati contro l'API.

Resta debole su:
- **concetti senza nome proprio** ("whistleblowing" → un solo risultato
  sbagliato, un decreto su un concorso pubblico);
- **i codici storici**: la ricerca trova il codice civile, ma **nessuno dei
  campi restituiti contiene il numero di allegato**. Senza quel numero
  l'URN dà 404 sempre — non è un limite risolvibile con più dati, il dato
  non è nell'indice del sito.

`ricerca/avanzata` (`POST .../ricerca/avanzata`) dà **connection reset
riproducibile**, misurato più volte il 29/08/2026: non va usata.

## 7. Fatto nuovo del 29 agosto 2026: l'endpoint del testo può andare in avaria

Durante le misure di oggi, `dettaglio-atto-urn` ha risposto
`500 {"code":"1000","message":"Errore generico della chiamata, riprovare più tardi"}`
su ogni URN per circa dieci minuti, mentre `ricerca/semplice`,
`tipologiche/estensioni` e il portale pubblico continuavano a rispondere
normalmente. Due controlli fatti per escludere le ipotesi peggiori:

- **Non è un blocco per volume di richieste**: 25 richieste di fila senza
  pausa, zero errori, né prima né dopo l'avaria.
- **Non è un cambio di contratto dell'API**: appena l'endpoint è tornato
  su, l'art. 2043 c.c. ha risposto byte-identico (1.287 byte) alla misura
  di stamattina e a quella di agosto.

Era un'avaria transitoria e specifica di quell'endpoint. **Conseguenza
pratica**: un controllo di salute generico ("il sito risponde?") direbbe
"tutto bene" mentre l'unica funzione che conta è ferma — il controllo deve
sondare `dettaglio-atto-urn` in particolare. E un 500 va sempre trattato
come "il servizio è giù adesso", mai come "la norma non esiste", senza
ritentativi automatici (che rischierebbero di aggravare un'eventuale causa
reale di rate-limit, anche se qui non ne abbiamo trovata).

## 8. Prestazioni generali

~800 richieste reali documentate fra agosto e il 29 agosto 2026: mediana
0,26 s, **zero 429, zero 5xx sistematici** (a parte l'avaria isolata di
cui sopra), nessun degrado su raffiche di richieste concorrenti o
sequenziali. Nessun rate limit osservato sull'endpoint dati. Un WAF esiste
nel perimetro di `dati.normattiva.it` (risponde 409 su alcuni path, es.
`robots.txt` e i GET con query string) ma non ha mai colpito
`api.normattiva.it`.
