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
- `norm verifica --tutte` — verifica l'intera tabella delle fonti contro
  l'API (decine di richieste — solo da terminale, mai da un modello)

**Come server MCP** (`norm-mcp`), quattro strumenti:

- `normattiva_leggi_articolo` — stessa lettura di `norm leggi`
- `normattiva_link` — stessa citazione di `norm link`
- `normattiva_trova_fonte` — cerca una fonte nella tabella, nessuna rete
- `normattiva_leggi_urn` — stessa lettura di `norm urn`

Un quinto strumento (`normattiva_cerca`, ricerca full-text) arriva con un
prossimo rilascio.

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

## Se Normattiva è in avaria

Capita, e non è un difetto di questo progetto: normattiva.it ha avuto
un'avaria reale e prolungata il 29 agosto 2026 (vedi `docs/MISURE.md` §7,
§7.1, §7.2). Quando succede, gli strumenti non restano appesi né inventano
un testo plausibile: rispondono con un errore chiaro ("il servizio è in
avaria adesso" o "Normattiva è stata sospesa dopo guasti ripetuti"), e le
istruzioni consegnate al modello gli dicono di non concluderne che la norma
non esiste e di non ritentare da solo.

Per capire se è un'avaria vera (non un problema di rete locale):

1. `norm doctor` — sonda specificamente l'endpoint del testo
   (`dettaglio-atto-urn`), quello che si è già guastato da solo mentre il
   resto del sito rispondeva.
2. Se persiste, prova da un'altra rete (es. dati mobili invece del Wi-Fi):
   un'avaria vera resta irraggiungibile anche da lì; un problema locale no.

`normattiva_trova_fonte` funziona comunque durante un'avaria: non tocca la
rete, legge solo la tabella locale delle fonti verificate.

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
