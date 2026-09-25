# SoundTouch Radio

Interfaccia web locale, semplice e responsive per controllare un diffusore **Bose SoundTouch** e cercare/ascoltare radio online tramite [Radio Browser](https://www.radio-browser.info/).

Il progetto è pensato per essere eseguito nella rete domestica: non richiede account, database o dipendenze Python esterne.

Creato da [Beasof.com](https://beasof.com).

> Questo progetto non è affiliato, associato o approvato da Bose.

---

## Contesto: shutdown del cloud Bose (maggio 2026)

Il 6 maggio 2026 Bose ha spento i server cloud SoundTouch. Da quel momento:

- La sorgente `LOCAL_INTERNET_RADIO` restituisce `UNKNOWN_SOURCE_ERROR 1005` — non funziona più perché richiedeva il cloud Bose per risolvere le stazioni.
- I preset fisici (tasti 1–6) salvati con stazioni TuneIn o altri servizi cloud non si avviano più.
- AirPlay, Bluetooth, Spotify Connect e AUX continuano a funzionare normalmente.

Questo progetto risolve il problema usando **UPnP AVTransport** sulla porta `8091` del diffusore, che è completamente locale e non dipende da alcun server Bose. È l'unico metodo confermato funzionante per lo streaming di radio Internet post-cloud.

---

## Funzionalità

- Visualizzazione dello stato e del contenuto in riproduzione
- Play/Pausa, brano precedente/successivo e mute
- Controllo del volume
- Ricerca di stazioni radio per nome e paese tramite [Radio Browser](https://www.radio-browser.info/)
- Riproduzione diretta via **UPnP AVTransport** (porta 8091) — funziona post-cloud
- **Preset virtuali**: salva fino a 6 stazioni nell'app; al click vengono riprodotte via UPnP
- Preferiti salvati localmente in JSON
- Tema chiaro, scuro o basato sulle impostazioni di sistema
- Interfaccia ottimizzata anche per smartphone
- Frontend separato in `templates/` e `static/` — HTML, CSS e JS modificabili senza toccare il server

---

## Come funziona la riproduzione (dettaglio tecnico)

La Bose SoundTouch espone tre interfacce locali:

| Porta | Protocollo | Uso |
|-------|-----------|-----|
| `8090` | HTTP REST | Info, volume, tasti, preset, now playing |
| `8080` | WebSocket  | Eventi in tempo reale |
| `8091` | UPnP/DLNA (SOAP) | **Riproduzione stream audio** |

Per avviare uno stream, il server invia due chiamate SOAP sequenziali alla porta `8091`:

```
SetAVTransportURI  →  imposta lo stream URL
Play               →  avvia la riproduzione
```

Entrambe richiedono l'header `SOAPAction` corretto — senza di esso il receiver UPnP ignora la richiesta. Gli stream devono usare **HTTP** (non HTTPS): la Bose non supporta TLS per UPnP.

I **preset virtuali** sono salvati in memoria dal server Python. Quando clicchi un preset nell'interfaccia web, l'app recupera lo stream URL salvato e lo invia direttamente via UPnP. I preset fisici sulla Bose non vengono modificati.

---

## Struttura del progetto

```
BS Sound/
├── server.py          # Server Python (stdlib pura, nessuna dipendenza esterna)
├── templates/
│   └── index.html     # Markup HTML
├── static/
│   ├── style.css      # Stili
│   └── app.js         # Logica client
├── config.cfg         # Configurazione locale (esclusa da git)
├── favorites.json     # Preferiti locali (escluso da git)
├── config.example.cfg
└── favorites.example.json
```

---

## Requisiti

- Python 3.8 o superiore (solo libreria standard — nessun `pip install`)
- Un diffusore Bose SoundTouch raggiungibile sulla stessa rete locale

---

## Installazione e avvio

```bash
git clone https://github.com/TUO-UTENTE/soundtouch-radio.git
cd soundtouch-radio

cp config.example.cfg config.cfg
cp favorites.example.json favorites.json
```

Apri `config.cfg` e imposta l'IP del tuo diffusore Bose:

```ini
BOSE_IP=192.168.1.50
```

Avvia il server:

```bash
python3 server.py
```

L'interfaccia è disponibile all'indirizzo mostrato nel terminale, normalmente:

```
http://<IP-DEL-COMPUTER>:8765
```

Per interrompere: `Ctrl+C`.

---

## Configurazione

| Opzione | Descrizione | Valore predefinito |
|---------|-------------|-------------------|
| `BOSE_IP` | Indirizzo IP del diffusore Bose SoundTouch | `192.168.1.52` |
| `SERVER_HOST` | Interfaccia di rete su cui esporre il server | `0.0.0.0` |
| `SERVER_PORT` | Porta dell'interfaccia web | `8765` |
| `RADIO_BROWSER_HOST` | Endpoint dell'API Radio Browser | `https://de1.api.radio-browser.info` |

## Debug metadati ICY

Il frontend include un pannello di debug opzionale per verificare i metadati ricevuti dalla Bose e dallo stream radio in tempo reale.

- Il flag di configurazione si legge da `config.cfg` con la chiave `debug_icy`.
- Il template HTML lo usa in [templates/index.html](templates/index.html).
- Il pannello è mostrato/hidden da [static/app.js](static/app.js).
- Lo stile del box di debug è in [static/style.css](static/style.css).

Esempio in `config.cfg`:

```ini
debug_icy=true
```

Quando il debug è spento, il pannello rimane nascosto e non lascia file o log inutili nel repository.

---

## Note sugli stream

- Usa **URL HTTP** (non HTTPS): la Bose non supporta TLS per UPnP.
- Le playlist `.pls` e `.m3u` vengono risolte automaticamente al primo stream diretto trovato.
- Se uno stream non parte, verifica che sia raggiungibile dalla rete locale e che il codec sia supportato (MP3 e AAC sono i più affidabili).

---

## Privacy e sicurezza

Il server non implementa autenticazione: usalo solo su una rete fidata, non esporre la porta su Internet. I file `config.cfg` e `favorites.json` sono esclusi da Git per impostazione predefinita.

---

## Crediti

- Metodo UPnP post-cloud basato su [alinossier/soundtouch-local-presets](https://github.com/alinossier/soundtouch-local-presets) (MIT).
- Ricerca stazioni tramite [Radio Browser](https://www.radio-browser.info/) (CC0).

---

## Licenza

Distribuito con [Apache License 2.0](LICENSE). Il file [NOTICE](NOTICE) richiede di mantenere l'attribuzione a [Beasof.com](https://beasof.com) nelle redistribuzioni e nelle opere derivate.
