# normattiva-mcp

CLI e server MCP per leggere, verificare e citare norme italiane da
Normattiva.it, pensati per essere usati anche da modelli LLM economici (es.
DeepSeek 4 flash). Il testo di un articolo viene sempre dall'API di
Normattiva, mai dal permalink del portale (2.000 volte più pesante per lo
stesso contenuto — vedi [ARCHITETTURA.md](ARCHITETTURA.md)).

## Cosa fa

**Da terminale** (`norm --help`):

- `norm leggi <fonte> <articolo>` — legge il testo verificato di un articolo
  (`norm leggi "codice civile" 2043`)
- `norm link <fonte> <articolo>` — costruisce la citazione Markdown,
  verificandola per difetto
- `norm urn <urn>` — legge un URN già in mano (es. un rinvio trovato in un
  testo)
- `norm fonti [testo]` — elenca le fonti verificate, o ne cerca una
- `norm doctor` — controlla se l'endpoint del testo risponde
- `norm stato` — mostra localmente cache, quote, cooldown e ultimo incidente
- `norm skill` — installa e aggiorna la skill Agent Skills per gli assistenti
- `norm verifica --tutte` — mostra prima il costo stimato; esegue solo con
  `--esegui`, dopo avere prenotato tutto il budget necessario

**Come server MCP** (`norm-mcp`), cinque strumenti:

- `normattiva_leggi_articolo` — stessa lettura di `norm leggi`
- `normattiva_link` — stessa citazione di `norm link`
- `normattiva_trova_fonte` — cerca una fonte nella tabella, nessuna rete
- `normattiva_leggi_urn` — stessa lettura di `norm urn`
- `normattiva_stato_rete` — stato locale della protezione, senza rete

Una futura ricerca full-text non è ancora esposta: se verrà aggiunta, dovrà
usare solo un canale Open Data ufficiale adatto al volume richiesto.

## Installazione

Richiede [uv](https://docs.astral.sh/uv/) e Python 3.12-3.14.

```sh
uv tool install --editable .
```

Installa entrambi i comandi (`norm`, `norm-mcp`) in `~/.local/bin`, restando
sincronizzati col sorgente (utile durante lo sviluppo; per un uso normale
basta `uv tool install normattiva-mcp` una volta pubblicato su PyPI).

## Collegare il server MCP a un assistente

Esempio per Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "normattiva": {
      "command": "/Users/tuonome/.local/bin/norm-mcp",
      "args": []
    }
  }
}
```

Riavvia l'app dopo aver modificato il file. Il server parla solo su stdio,
nessuna porta di rete aperta.

## Installare la skill Agent Skills

La skill portabile [`normattiva-mcp`](skills/normattiva-mcp/SKILL.md) segue lo
standard aperto [Agent Skills](https://agentskills.io/) e non contiene estensioni
specifiche di un singolo modello. È inclusa anche nel pacchetto Python, così la CLI
può installarla dopo un'installazione da PyPI, `uv tool` o `pipx`.

```sh
norm skill list
norm skill install opencode
norm skill install claude-code
norm skill install codex
norm skill install pi
norm skill install all
```

`install all` installa soltanto nei client rilevati tramite il loro binario o la
directory di configurazione e indica quelli saltati. Indicando un client preciso,
l'installazione viene invece eseguita anche se il relativo binario non è sul `PATH`.

Il livello predefinito è personale. Per installarla solo nel progetto corrente:

```sh
norm skill install opencode --level project
```

Le destinazioni sono quelle native dei client: `~/.claude/skills`,
`~/.agents/skills`, `~/.config/opencode/skills` e `~/.pi/agent/skills`; a livello
progetto diventano rispettivamente `.claude/skills`, `.agents/skills`,
`.opencode/skills` e `.pi/skills`. `norm skill update` aggiorna le copie già
installate, `norm skill show` mostra la sorgente e `norm skill uninstall <client>`
la rimuove dal client indicato.

Per collaudare un modello, il protocollo incluso parte da operazioni locali, usa al
massimo un canary reale e richiede che la ripetizione identica sia servita dalla
cache. Gli errori e l'arresto su `critico`/`bloccato` vanno provati solo con mock o
server locale.

## Uso prudente della rete

> **Avvertenza:** osservazioni empiriche indicano che, dopo un numero elevato di
> richieste, Normattiva.it può smettere di rispondere in modo persistente da uno
> specifico indirizzo IP pur restando raggiungibile da altre reti. Non vi è una
> conferma ufficiale che si tratti di un ban, e sintomi analoghi possono dipendere
> anche da filtri o problemi di instradamento. Considerare comunque concreto il
> rischio: usare l'MCP con parsimonia, evitare raffiche e parallelismo e fermarsi
> al primo errore o cooldown senza tentare di proseguire tramite altre reti.

Il programma usa soltanto l'endpoint Open Data documentato `POST
.../atto/dettaglio-atto-urn`, mai scraping HTML, browser automation, proxy
o cambio di IP/VPN. Il permalink è generato come link, ma non viene scaricato.

Un database SQLite condiviso coordina CLI, MCP e processi concorrenti: una
sola richiesta reale alla volta, almeno 5 secondi fra richieste e cache
condivisa. Il testo vigente resta in cache 7 giorni, quello storico 30;
gli errori deterministici 400/404 un'ora. `NORMATTIVA_OFFLINE=1` usa solo
la cache; se il database protettivo non è disponibile, non viene inviata
nessuna richiesta.

I limiti seguenti sono **cautele locali del progetto, non limiti comunicati
da Normattiva**: 30 consultazioni e 2 diagnosi per 24 ore mobili, con un
massimo assoluto di 60. Si possono solo ridurre con le variabili d'ambiente;
non aumentare da flag CLI o tool MCP. Ogni tentativo HTTP, anche fallito,
consuma quota e non esistono retry automatici.

Configurazione facoltativa: `NORMATTIVA_STATO_DB` sceglie il file SQLite;
`NORMATTIVA_OFFLINE=1` disabilita la rete; `NORMATTIVA_LIMITE_CONSULTAZIONI`,
`NORMATTIVA_LIMITE_DIAGNOSI` e `NORMATTIVA_LIMITE_ASSOLUTO` possono soltanto
ridurre le rispettive soglie. `NORMATTIVA_CONTATTO_USER_AGENT` aggiunge un
contatto volontario al User-Agent stabile del progetto.

Un 429 comporta il rispetto di `Retry-After` e comunque almeno 6 ore di
pausa; 401/403/409 24 ore; 5xx o risposta malformata 15 minuti. Timeout,
reset e TLS sono eventi indeterminati, non prova di ban, e avviano un
cooldown crescente. Durante il cooldown, avvisa l'utente e non ritentare:
non cambiare IP, VPN o proxy per proseguire.

Ogni risposta MCP che può usare la rete include `protezione_rete`; la CLI
scrive il consumo reale su stderr (per esempio `consultazione 7/30 — totale
9/60`). A 50%, 80% e 90% il livello diventa rispettivamente attenzione o
critico. Quando è `critico` o `bloccato`, il modello deve fermare il workflow
e avvertire l'utente. Prima di un'attività con più consultazioni, usa
`norm stato` o `normattiva_stato_rete`.

`norm doctor` non esegue rete durante un cooldown e fa al massimo una
richiesta. La verifica completa è limitata a una ogni 7 giorni e parte solo
se il budget intero è prenotabile. Prima di aumentare i volumi o offrire il
servizio a terzi, chiedere al gestore indicazioni scritte su limiti, canale
bulk e modalità d'uso preferite. Future operazioni massive devono usare solo
eventuali canali ufficiali asincroni/bulk, mai un fan-out articolo per articolo.

## Documentazione

- [CLAUDE.md](CLAUDE.md) — mappa del progetto, regole vincolanti
- [ARCHITETTURA.md](ARCHITETTURA.md) — come è fatto e perché

## Licenza

Il **codice** di questo repository è distribuito con licenza MIT (vedi
[LICENSE](LICENSE)).

I **dati** restituiti dagli strumenti (testi normativi, metadati degli atti)
provengono da Normattiva.it, Istituto Poligrafico e Zecca dello Stato, e sono
distribuiti con licenza [Creative Commons Attribuzione 4.0 Internazionale
(CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/deed.it). Ogni
risposta degli strumenti include l'attribuzione richiesta dalla licenza.
