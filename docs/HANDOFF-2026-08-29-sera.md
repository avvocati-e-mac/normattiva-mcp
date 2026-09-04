# Handoff — 29 agosto 2026, sera (sostituisce HANDOFF-2026-08-29.md del mattino)

Per chi riprende il lavoro: questo file dice **dove siamo adesso**, dopo
una sessione intera passata a costruire il branch `mcp`, testarlo
end-to-end (Claude Desktop e opencode/DeepSeek v4 flash), trovare e
correggere un bug reale, completare il README e tagliare la prima
release. Leggilo prima di [CLAUDE.md](../CLAUDE.md).

Il file del mattino (`HANDOFF-2026-08-29.md`) resta nella cronologia git
per il racconto di come è stata scoperta l'avaria, ma è superato su tutto
il resto: quando questo file e quello divergono, vince questo.

## Stato del repository

- Pubblico su GitHub: **https://github.com/avvocati-e-mac/normattiva-mcp**
- Locale: `/Users/filippostrozzi/Documents/Sviluppo App/normattiva-mcp`
  (attenzione: il vecchio handoff dava un percorso diverso, `/Users/
  filippostrozzi/Sviluppo app/Normattiva MCP CLI` — non esiste su questa
  macchina; il percorso qui sopra è quello vero).
- `main` sincronizzato con `origin/main` (fino al commit `eb3101f`),
  pulito, **132 test verdi** (`uv run pytest`), lint pulito
  (`uv run ruff check .` e `ruff format --check .`).
- **Tag `v0.1.0` pubblicato**, con release note su GitHub
  (https://github.com/avvocati-e-mac/normattiva-mcp/releases/tag/v0.1.0).
- Identità git locale impostata esplicitamente su questo repository
  (`user.name`/`user.email`, era andata persa fra le sessioni — se
  ricapita, ripetere `git config --local user.name/user.email`).

## Cosa esiste e funziona ora (tutto, branch 0-8 del piano più extra)

Tutto quanto nell'handoff del mattino (impianto, misure, grammatica-urn,
tabella-fonti, lookup, parser, client, cli), **più**:

- **Branch `mcp` fuso**: `descrizioni.py` + `mcp_server.py`, **quattro
  strumenti MCP**: `normattiva_leggi_articolo`, `normattiva_link`,
  `normattiva_trova_fonte` (l'unico locale), `normattiva_leggi_urn`.
  Tetto caratteri misurato: 4.124/5.500 caratteri.
- **Refactor**: la risoluzione fonte+articolo (parsing numero,
  estensione, vigenza) è condivisa fra `cli.py` e `mcp_server.py` via
  `lookup.risolvi_riferimento` — non più due copie.
- **README completo**: installazione (`uv tool install --editable .`),
  elenco comandi/tool, esempio di config Claude Desktop, sezione
  sull'avaria.
- **`normattiva-mcp` installato come tool `uv`** (editable — resta
  sincronizzato col sorgente, nessun reinstall dopo una modifica al
  codice; serve solo riavviare il processo client che lo tiene aperto).
  Binari in `~/.local/bin/norm` e `~/.local/bin/norm-mcp`.
- **Registrato in due client MCP** per i test:
  - Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`,
    chiave `"normattiva"` (backup del config precedente salvato accanto,
    stesso nome + timestamp).
  - opencode: `~/.config/opencode/opencode.json`, chiave `"mcp.normattiva"`.

## Un bug reale trovato e corretto oggi — IMPORTANTE per chi aggiunge strumenti

**L'SDK MCP (`mcp` 2.1.1) tratta come crash silenzioso qualunque eccezione
sollevata da uno strumento che non sia una sua `ToolError`** (da
`mcp.server.mcpserver.exceptions`): il modello legge solo `"Error
executing tool <nome>"`, il messaggio scritto per lui sparisce. Scoperto
provando `normattiva_leggi_articolo`/`normattiva_link` a mano da Claude
Desktop durante l'indisponibilità osservata: il modello ha ricevuto un errore muto e ha
offerto di recitare l'articolo **a memoria** come ripiego — esattamente
il rischio che CLAUDE.md regola 1 vuole escludere.

Fix in `mcp_server.py`: ogni strumento passa da `@_traduci_errori`
(applicato appena sotto `@server.tool(...)`, sopra `async def`), che
avvolge l'INTERO corpo dello strumento (non solo la parte di rete —
`_risolvi_riferimento`/`analizza_urn` sollevano i loro errori PRIMA di
toccare la rete) e converte ogni eccezione in `ToolError`: un errore di
dominio con lo stesso messaggio, un imprevisto sanificato.

**Se aggiungi un ulteriore strumento (la ricerca full-text sarebbe il sesto),
mettigli `@_traduci_errori` fra `@server.tool(...)` e `async def`, o il
bug si ripete silenziosamente** — nessun test lo scopre se non passa
davvero per `_tool_manager.call_tool()` o per un client MCP vero: i test
che chiamano la funzione decorata direttamente (come in
`tests/test_mcp_server.py`) lo *verificano* correttamente perché
`_traduci_errori` è già applicato all'oggetto chiamato, ma un test
scritto PRIMA del fix, che chiamasse la funzione grezza sotto il
decoratore, non l'avrebbe mai trovato.

## Testato end-to-end oggi (non solo con fixture)

- **Claude Desktop (Sonnet 5)**: `normattiva_trova_fonte` e
  `normattiva_link` (verifica=false) — entrambi corretti, log MCP
  ispezionato (`~/Library/Logs/Claude/mcp-server-normattiva.log`).
  `normattiva_leggi_articolo` provato PRIMA del fix (errore muto → il
  modello ha recitato a memoria, comportamento indesiderato osservato dal
  vivo).
- **opencode + DeepSeek v4 flash** (via OpenRouter, id esatto
  `openrouter/deepseek/deepseek-v4-flash`, MAI la variante con la tilde
  `~deepseek/...-latest`, instabile): tutti e tre gli strumenti locali
  provati con successo; `normattiva_leggi_articolo` provato DOPO il fix,
  fallito per l'avaria come atteso, ma con l'errore leggibile — DeepSeek
  ha riportato il messaggio vero, escluso l'inferenza "la norma non
  esiste", suggerito `norm doctor`, e **non** ha recitato nulla a
  memoria. Un solo run per modello, non comparabile alla lettera (vedi
  sotto) — dettagli completi in `docs/MISURE.md` §9.

## Nota operativa superata

Questo handoff descrive osservazioni storiche da una singola installazione:
non prova con certezza un'avaria generale, né esclude un blocco individuale.
La politica attuale non prescrive test da un'altra rete e vieta cambio di IP,
VPN o proxy per continuare dopo un rifiuto. In caso di incidente, consulta
solo lo stato locale, avverti l'utente e non ritentare durante il cooldown.
Un eventuale canary reale è un'operazione manuale e isolata, non un test CI
né una verifica ricorrente.

## Regole da non dimenticare (oltre a quelle del CLAUDE.md)

1. **Ogni strumento MCP nuovo porta `@_traduci_errori`** (vedi sopra) —
   la regola più a rischio di essere dimenticata perché il sintomo
   (errore muto) non lo scopre nessun test che non passi per l'SDK vero.
2. **`norm-mcp` è installato editable**: modificare il sorgente non
   richiede un reinstall, ma il processo client (Claude Desktop, una
   sessione opencode) va riavviato per caricare il codice nuovo.
3. **Provare sempre a mano con un client MCP vero**, non solo con
   `.fn()` nei test: il bug di oggi esisteva esattamente nel confine fra
   la funzione Python e l'SDK, invisibile chiamando la funzione
   direttamente.
4. **Un run singolo con un modello non è un banco di prova**: il branch
   `banco` (dieci compiti misurati, non ancora iniziato) resta la sede
   giusta per un confronto vero; quanto osservato oggi va citato come
   punto di partenza, non come conclusione.

## Cosa resta da fare (dal piano originale, aggiornato)

9. `ricerca` — `ricerca.py`, quinto tool MCP `normattiva_cerca`. Bloccato
   dalla rete per lo sviluppo/verifica contro l'API reale.
10. `banco` — banco di prova vero con DeepSeek 4 flash via OpenRouter (i
    dieci compiti del piano). L'infrastruttura per farlo esiste già
    (opencode configurato, id modello confermato — vedi memoria di
    progetto `project_deepseek_test_harness` nel sistema di memoria di
    Claude, se disponibile in questa sessione).
11. `skill` — riscrittura di `skill-legali/normattiva` (repository
    diverso) per chiamare `normattiva_trova_fonte`.
12. `pubblicazione` — **in gran parte già fatto** in questa sessione
    (README, versione 0.1.0, licenze dichiarate, prima release
    taggata). Verificare se resta altro (badge, CI, changelog?) prima di
    considerarlo chiuso.

## File da leggere per orientarsi, in ordine

1. Questo file
2. `CLAUDE.md` — mappa e regole vincolanti (§ "Il tetto sul sapere
   consegnato al modello" ora ha sostanza vera, non più un placeholder)
3. `ARCHITETTURA.md` — sezioni `#due-porte` e `#budget` ora scritte con
   la sostanza del branch `mcp`
4. `docs/MISURE.md` — §7-7.2 (l'avaria), §9 (il run Claude/DeepSeek)
5. `docs/IDEE-SCARTATE.md` — include ora la voce sul fallback Playwright,
   scartato con motivazione (l'avaria di oggi stessa ne è la prova)
