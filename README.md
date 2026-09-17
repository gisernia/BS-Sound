# SoundTouch Radio

Interfaccia web locale, semplice e responsive per controllare un diffusore **Bose SoundTouch** e cercare/ascoltare radio online tramite [Radio Browser](https://www.radio-browser.info/).

Il progetto è pensato per essere eseguito nella rete domestica: non richiede account, database o dipendenze Python esterne.

Creato da [Beasof.com](https://beasof.com).

> Questo progetto non è affiliato, associato o approvato da Bose.

## Funzionalità

- Visualizzazione dello stato e del contenuto in riproduzione
- Play/Pausa, brano precedente/successivo e mute
- Controllo del volume
- Richiamo dei sei preset Bose
- Ricerca di stazioni radio per nome e paese
- Preferiti salvati localmente
- Tema chiaro, scuro o basato sulle impostazioni di sistema
- Interfaccia ottimizzata anche per smartphone

## Requisiti

- Python 3.8 o superiore
- Un dispositivo Bose SoundTouch raggiungibile dalla stessa rete

## Installazione e avvio

Clona il repository e accedi alla cartella del progetto:

```bash
git clone https://github.com/TUO-UTENTE/soundtouch-radio.git
cd soundtouch-radio
```

Crea la configurazione locale a partire dall'esempio:

```bash
cp config.example.cfg config.cfg
```

Apri `config.cfg` e imposta l'indirizzo IP del tuo dispositivo Bose:

```ini
BOSE_IP=192.168.1.50
```

Infine avvia il server:

```bash
./server.py
```

L'interfaccia sarà disponibile all'indirizzo mostrato nel terminale, normalmente:

```text
http://<IP-DEL-COMPUTER>:8765
```

Per interrompere il server premi `Ctrl+C`.

## Configurazione

| Opzione | Descrizione | Valore predefinito |
| --- | --- | --- |
| `BOSE_IP` | Indirizzo IP del diffusore Bose SoundTouch | `192.168.1.50` |
| `SERVER_HOST` | Interfaccia di rete su cui esporre il server | `0.0.0.0` |
| `SERVER_PORT` | Porta dell'interfaccia web | `8765` |
| `RADIO_BROWSER_HOST` | Endpoint dell'API Radio Browser | `https://de1.api.radio-browser.info` |

## Privacy e sicurezza

Il server non implementa autenticazione: usalo solo su una rete fidata e non esporre la porta su Internet. I file `config.cfg` e `favorites.json`, che possono contenere dati personali della tua rete e delle tue preferenze, sono esclusi da Git per impostazione predefinita.

## Licenza

Distribuito con [Apache License 2.0](LICENSE). Il file [NOTICE](NOTICE) richiede di mantenere l'attribuzione a [Beasof.com](https://beasof.com) nelle redistribuzioni e nelle opere derivate.
