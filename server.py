#!/usr/bin/env python3

# Copyright 2026 Beasof.com
# Licensed under the Apache License, Version 2.0.

import html
import json
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.cfg"
FAVORITES_FILE = BASE_DIR / "favorites.json"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


DEFAULT_CONFIG = {
    "BOSE_IP": "192.168.1.52",
    "SERVER_HOST": "0.0.0.0",
    "SERVER_PORT": "8765",
    "RADIO_BROWSER_HOST": "https://de1.api.radio-browser.info",
}


def load_config():
    config = DEFAULT_CONFIG.copy()

    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text(
            encoding="utf-8"
        ).splitlines():

            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)

            config[key.strip()] = value.strip()

    return config


CONFIG = load_config()

BOSE_IP = CONFIG["BOSE_IP"]
SERVER_HOST = CONFIG["SERVER_HOST"]
SERVER_PORT = int(CONFIG["SERVER_PORT"])
RADIO_BROWSER_HOST = CONFIG["RADIO_BROWSER_HOST"].rstrip("/")


# ============================================================
# HTTP UTILS
# ============================================================

def http_request(
    url,
    method="GET",
    body=None,
    content_type=None,
    timeout=8
):
    headers = {
        "User-Agent": "SoundTouchRadio/1.0"
    }

    data = None

    if body is not None:

        if isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body

        if content_type:
            headers["Content-Type"] = content_type

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:

        return response.read()


# ============================================================
# BOSE SOUNDTOUCH API
# ============================================================

def bose_url(path):

    return f"http://{BOSE_IP}:8090{path}"


def bose_get(path):

    return http_request(
        bose_url(path),
        timeout=5
    ).decode(
        "utf-8",
        "replace"
    )


def bose_post(path, xml):

    return http_request(
        bose_url(path),
        method="POST",
        body=xml,
        content_type="application/xml; charset=utf-8",
        timeout=8
    ).decode(
        "utf-8",
        "replace"
    )


# ============================================================
# XML HELPERS
# ============================================================

def xml_text(node, tag, default=""):

    if node is None:
        return default

    element = node.find(tag)

    if element is None:
        return default

    if element.text is None:
        return default

    return element.text.strip()


# ============================================================
# BOSE INFO
# ============================================================

def get_info():

    xml = bose_get("/info")

    root = ET.fromstring(xml)

    return {
        "ip": BOSE_IP,
        "name": xml_text(root, "name"),
        "type": xml_text(root, "type"),
        "mac": root.attrib.get(
            "deviceID",
            ""
        ),
    }


# ============================================================
# BOSE SOURCES
# ============================================================

def is_source_ready(source):

    xml = bose_get("/sources")

    root = ET.fromstring(xml)

    return any(
        item.attrib.get("source") == source
        and
        item.attrib.get("status") == "READY"
        for item in root.findall("sourceItem")
    )


# ============================================================
# NOW PLAYING
# ============================================================

def get_now_playing():

    xml = bose_get("/now_playing")

    root = ET.fromstring(xml)

    content = root.find("ContentItem")

    return {
        "source": root.attrib.get(
            "source",
            ""
        ),

        "name": xml_text(
            content,
            "itemName"
        ),

        "track": xml_text(
            root,
            "track"
        ),

        "artist": xml_text(
            root,
            "artist"
        ),

        "album": xml_text(
            root,
            "album"
        ),

        "stationName": xml_text(
            root,
            "stationName"
        ),

        "description": xml_text(
            root,
            "description"
        ),

        "playStatus": xml_text(
            root,
            "playStatus"
        ),

        "art": xml_text(
            root,
            "art"
        ),
    }


# ============================================================
# VOLUME
# ============================================================

def get_volume():

    xml = bose_get("/volume")

    root = ET.fromstring(xml)

    target = root.findtext(
        "targetvolume"
    )

    actual = root.findtext(
        "actualvolume"
    )

    mute = root.findtext(
        "muteenabled"
    )

    return {
        "target": int(
            target or 0
        ),

        "actual": int(
            actual or 0
        ),

        "mute": (
            (mute or "").lower()
            == "true"
        ),
    }


def set_volume(value):

    value = max(
        0,
        min(100, int(value))
    )

    xml = f"<volume>{value}</volume>"

    return bose_post(
        "/volume",
        xml
    )


# ============================================================
# KEYS
# ============================================================

def press_key(key):

    sender = "Gabbo"

    press = (
        f'<key state="press" '
        f'sender="{sender}">'
        f'{html.escape(key)}'
        f'</key>'
    )

    release = (
        f'<key state="release" '
        f'sender="{sender}">'
        f'{html.escape(key)}'
        f'</key>'
    )

    bose_post(
        "/key",
        press
    )

    bose_post(
        "/key",
        release
    )


# ============================================================
# PRESETS
# ============================================================

def get_presets():

    xml = bose_get("/presets")

    root = ET.fromstring(xml)

    result = []

    for preset in root.findall("preset"):

        content = preset.find(
            "ContentItem"
        )

        result.append({
            "id": int(
                preset.attrib.get(
                    "id",
                    "0"
                )
            ),

            "name": xml_text(
                content,
                "itemName"
            ),

            "source": (
                content.attrib.get(
                    "source",
                    ""
                )
                if content is not None
                else ""
            ),

            "location": (
                content.attrib.get(
                    "location",
                    ""
                )
                if content is not None
                else ""
            ),
        })

    return result


# ============================================================
# PLAY RADIO STREAM
# ============================================================

# Preset virtuali in memoria: numero (1-6) -> {name, stream_url, favicon}
# Usati per riprodurre via UPnP al click del preset nell'interfaccia web.
_virtual_presets = {}
_virtual_presets_lock = threading.Lock()


def _save_virtual_preset(number, name, stream_url, favicon=""):
    with _virtual_presets_lock:
        _virtual_presets[number] = {
            "name": name,
            "stream_url": stream_url,
            "favicon": favicon,
        }


def get_virtual_preset(number):
    with _virtual_presets_lock:
        return _virtual_presets.get(number)


def resolve_stream_url(url):
    """Risolve playlist .pls/.m3u al primo URL HTTP diretto trovato."""
    if not url:
        return url
    url_lower = url.lower()
    if url_lower.endswith('.pls') or url_lower.endswith('.m3u'):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SoundTouchRadio/1.0"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                content_text = resp.read().decode("utf-8", "ignore")
                for line in content_text.splitlines():
                    line = line.strip()
                    if line.startswith("http://") or line.startswith("https://"):
                        return line
                    if line.startswith("File1="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return url


def _force_http(url):
    """La Bose SoundTouch non supporta HTTPS per gli stream UPnP."""
    if url.startswith("https://"):
        return "http://" + url[8:]
    return url


def _soap_envelope(action, body):
    return (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body>'
        f'<u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
        f'{body}'
        f'</u:{action}>'
        '</s:Body>'
        '</s:Envelope>'
    )


def _post_avtransport(action, body):
    """Invia una chiamata SOAP UPnP AVTransport alla Bose sulla porta 8091."""
    url = f"http://{BOSE_IP}:8091/AVTransport/Control"
    payload = _soap_envelope(action, body).encode("utf-8")
    headers = {
        "User-Agent": "SoundTouchRadio/1.0",
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
    }
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def play_upnp(stream_url):
    """
    Avvia la riproduzione di uno stream via UPnP AVTransport (porta 8091).
    Unico metodo funzionante post-shutdown del cloud Bose (maggio 2026).
    LOCAL_INTERNET_RADIO e INTERNET_RADIO restituiscono UNKNOWN_SOURCE_ERROR 1005.
    Implementazione basata su: alinossier/soundtouch-local-presets (MIT)
    """
    _post_avtransport(
        "SetAVTransportURI",
        "<InstanceID>0</InstanceID>"
        f"<CurrentURI>{html.escape(stream_url)}</CurrentURI>"
        "<CurrentURIMetaData></CurrentURIMetaData>",
    )
    _post_avtransport(
        "Play",
        "<InstanceID>0</InstanceID><Speed>1</Speed>",
    )


def play_radio(name, stream_url, favicon=""):
    """Riproduce uno stream radio sulla Bose via UPnP."""
    if not stream_url:
        raise ValueError("La stazione non ha un URL stream.")
    resolved = _force_http(resolve_stream_url(stream_url))
    play_upnp(resolved)
    return "OK"


def store_radio_preset(number, name, stream_url, favicon=""):
    """
    Salva una stazione come preset virtuale (in memoria).
    Al click del preset nell'interfaccia web viene riprodotta via UPnP.
    I preset fisici della Bose non funzionano più post-cloud.
    """
    if number < 1 or number > 6:
        raise ValueError("Preset deve essere 1..6")
    if not stream_url:
        raise ValueError("La stazione non ha un URL stream.")
    resolved = _force_http(resolve_stream_url(stream_url))
    _save_virtual_preset(number, name, resolved, favicon)


# ============================================================
# RADIO BROWSER
# ============================================================

def radio_search(
    query,
    country="",
    limit=40
):

    params = {
        "name": query,
        "limit": str(
            min(
                max(limit, 1),
                100
            )
        ),
        "order": "votes",
        "reverse": "true",
        "hidebroken": "true",
    }

    if country:

        params["countrycode"] = country.upper()

    url = (
        RADIO_BROWSER_HOST
        + "/json/stations/search?"
        + urllib.parse.urlencode(
            params
        )
    )

    raw = http_request(
        url,
        timeout=12
    )

    stations = json.loads(
        raw.decode(
            "utf-8"
        )
    )

    result = []

    for station in stations:

        stream = (
            station.get("url_resolved")
            or
            station.get("url")
        )

        if not stream:
            continue

        result.append({

            "id":
                station.get("stationuuid", ""),

            "name":
                station.get("name", ""),

            "country":
                station.get("country", ""),

            "language":
                station.get("language", ""),

            "codec":
                station.get("codec", ""),

            "bitrate":
                station.get("bitrate", 0),

            "homepage":
                station.get("homepage", ""),

            "favicon":
                station.get("favicon", ""),

            "stream":
                stream,
        })

    return result


# ============================================================
# FAVORITES
# ============================================================

favorites_lock = threading.Lock()


def load_favorites():

    if not FAVORITES_FILE.exists():
        return []

    try:

        data = json.loads(
            FAVORITES_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            data,
            list
        ):
            return data

    except Exception:
        pass

    return []


def save_favorites(
    favorites
):

    with favorites_lock:

        FAVORITES_FILE.write_text(
            json.dumps(
                favorites,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )


# ============================================================
# WEB INTERFACE
# ============================================================

def render_template(name):
    """Legge il file HTML dalla cartella templates/."""
    path = TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Template non trovato: {name}")
    return path.read_bytes()


def serve_static(filename):
    """
    Restituisce (content_type, data) per un file in static/.
    Lancia FileNotFoundError se il file non esiste.
    """
    MIME = {
        ".css":  "text/css; charset=utf-8",
        ".js":   "application/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".svg":  "image/svg+xml",
        ".ico":  "image/x-icon",
        ".woff2": "font/woff2",
        ".woff":  "font/woff",
    }
    path = STATIC_DIR / filename
    # Blocca path traversal
    try:
        path.resolve().relative_to(STATIC_DIR.resolve())
    except ValueError:
        raise PermissionError("Accesso negato")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File statico non trovato: {filename}")
    suffix = path.suffix.lower()
    content_type = MIME.get(suffix, "application/octet-stream")
    return content_type, path.read_bytes()


# ============================================================
# WEB SERVER
# ============================================================

class Handler(
    BaseHTTPRequestHandler
):


    def send_json(
        self,
        data,
        status=200
    ):

        payload = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")


        self.send_response(
            status
        )


        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )


        self.send_header(
            "Cache-Control",
            "no-store"
        )


        self.send_header(
            "Content-Length",
            str(len(payload))
        )


        self.end_headers()


        self.wfile.write(
            payload
        )


    def read_json(self):

        length = int(
            self.headers.get(
                "Content-Length",
                "0"
            )
        )


        raw = (
            self.rfile.read(
                length
            )
        )


        if not raw:
            return {}


        return json.loads(
            raw.decode(
                "utf-8"
            )
        )


    def do_GET(self):

        try:

            parsed = urllib.parse.urlsplit(
                    self.path
                )


            path = parsed.path


            # ------------------------------------------------
            # HOME
            # ------------------------------------------------

            if path == "/":

                data = render_template("index.html")

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return


            # ------------------------------------------------
            # STATIC FILES
            # ------------------------------------------------

            if path.startswith("/static/"):

                filename = path[len("/static/"):]

                try:
                    content_type, data = serve_static(filename)
                except (FileNotFoundError, PermissionError) as exc:
                    self.send_json({"ok": False, "error": str(exc)}, 404)
                    return

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(data)
                return


            # ------------------------------------------------
            # STATUS
            # ------------------------------------------------

            if path == "/api/status":

                info = get_info()
                now = get_now_playing()
                volume = get_volume()

                # Costruisce la lista preset: merge tra preset Bose reali
                # e preset virtuali salvati in questa sessione.
                # I preset virtuali hanno priorità (sovrascrivono quelli Bose
                # che post-cloud non funzionano più).
                bose_presets = get_presets()
                merged = {p["id"]: p for p in bose_presets}
                with _virtual_presets_lock:
                    for num, vp in _virtual_presets.items():
                        merged[num] = {
                            "id": num,
                            "name": vp["name"],
                            "source": "VIRTUAL",
                            "location": "",
                        }
                presets = sorted(merged.values(), key=lambda p: p["id"])

                self.send_json({
                    "ok": True,
                    "device": info,
                    "now": now,
                    "volume": volume,
                    "presets": presets,
                })

                return


            # ------------------------------------------------
            # RADIO SEARCH
            # ------------------------------------------------

            if path == "/api/search":

                query = urllib.parse.parse_qs(
                        parsed.query
                    )


                q = query.get(
                        "q",
                        [""]
                    )[0]


                country = query.get(
                        "country",
                        [""]
                    )[0]


                stations = radio_search(
                        q,
                        country
                    )


                self.send_json({

                    "ok": True,

                    "stations":
                        stations

                })


                return


            # ------------------------------------------------
            # FAVORITES
            # ------------------------------------------------

            if path == "/api/favorites":

                self.send_json({

                    "ok": True,

                    "favorites":
                        load_favorites()

                })


                return


            self.send_json(
                {
                    "ok": False,
                    "error": "Not found"
                },
                404
            )


        except Exception as error:

            self.send_json(
                {
                    "ok": False,
                    "error": str(error)
                },
                500
            )


    def do_POST(self):

        try:

            parsed = urllib.parse.urlsplit(
                    self.path
                )


            path = parsed.path


            # ------------------------------------------------
            # KEY
            # ------------------------------------------------

            if path.startswith(
                "/api/key/"
            ):

                key = urllib.parse.unquote(
                        path[
                            len("/api/key/"):
                        ]
                    )


                press_key(
                    key
                )


                self.send_json({
                    "ok": True
                })


                return


            # ------------------------------------------------
            # VOLUME
            # ------------------------------------------------

            if path.startswith(
                "/api/volume/"
            ):

                value = int(
                        path[
                            len("/api/volume/"):
                        ]
                    )


                set_volume(
                    value
                )


                self.send_json({

                    "ok": True,

                    "volume":
                        value

                })


                return


            # ------------------------------------------------
            # PRESET
            # ------------------------------------------------

            if path.startswith(
                "/api/preset/"
            ):

                parts = path.split("/")

                if len(parts) not in (4, 5):
                    raise ValueError("URL preset non valido")

                number = int(parts[3])

                if number < 1 or number > 6:
                    raise ValueError("Preset deve essere 1..6")

                action = parts[4] if len(parts) == 5 else "play"

                if action == "store":
                    station = self.read_json()
                    name = station.get("name", "Radio")
                    stream = (
                        station.get("stream")
                        or station.get("url_resolved")
                        or station.get("url", "")
                    )
                    favicon = station.get("favicon", "")

                    if not stream:
                        raise ValueError("La stazione non ha uno stream valido.")

                    store_radio_preset(
                        number,
                        name,
                        stream,
                        favicon
                    )

                elif action == "remove":
                    bose_post(
                        "/removePreset",
                        f'<preset id="{number}"/>'
                    )

                elif action == "play":
                    # Prima controlla se abbiamo un preset virtuale salvato
                    # in questa sessione (stream salvato via questa app)
                    virtual = get_virtual_preset(number)
                    if virtual:
                        play_upnp(virtual["stream_url"])
                    else:
                        # Nessun preset virtuale: prova il tasto fisico.
                        # Post-cloud i preset fisici TuneIn non funzionano più,
                        # ma non possiamo fare altro — ignoriamo l'errore.
                        try:
                            press_key(f"PRESET_{number}")
                        except Exception:
                            pass

                else:
                    raise ValueError("Azione preset non valida")

                self.send_json({
                    "ok": True
                })

                return


            # ------------------------------------------------
            # PLAY
            # ------------------------------------------------

            if path == "/api/play":

                station = self.read_json()

                name = station.get(
                    "name",
                    "Radio"
                )

                favicon = station.get(
                    "favicon",
                    ""
                )

                stream = (
                    station.get("stream")
                    or station.get("url_resolved")
                    or station.get("url")
                )

                if not stream:
                    raise ValueError(
                        "La stazione non ha uno stream."
                    )

                play_radio(
                    name,
                    stream,
                    favicon
                )

                self.send_json({
                    "ok": True
                })

                return


            # ------------------------------------------------
            # FAVORITE
            # ------------------------------------------------

            if path == "/api/favorite":

                station = self.read_json()

                stream = (
                    station.get("stream")
                    or station.get("url_resolved")
                    or station.get("url")
                )

                if not stream:
                    raise ValueError(
                        "Stream mancante."
                    )

                station["stream"] = stream

                favorites = load_favorites()

                station_id = (
                    station.get("id")
                    or stream
                )

                favorites = [
                    item
                    for item in favorites
                    if (
                        item.get("id")
                        or item.get("stream")
                    ) != station_id
                ]

                favorites.insert(
                    0,
                    station
                )

                save_favorites(
                    favorites[:100]
                )

                self.send_json({
                    "ok": True,
                    "favorites": favorites[:100]
                })

                return


            self.send_json(
                {
                    "ok": False,
                    "error": "Not found"
                },
                404
            )


        except urllib.error.HTTPError as error:

            body = ""
            try:
                body = error.read().decode("utf-8", "replace")
            except Exception:
                pass

            print(f"[BOSE HTTP ERROR] {error.code} {error.reason}: {body[:300]}")

            self.send_json(
                {
                    "ok": False,
                    "error":
                        f"Bose HTTP {error.code}: {error.reason}"
                        + (f" — {body[:200]}" if body else "")
                },
                502
            )


        except Exception as error:

            import traceback
            print(f"[ERROR] {traceback.format_exc()}")

            self.send_json(
                {
                    "ok": False,
                    "error": str(error)
                },
                500
            )


    def log_message(
        self,
        format_string,
        *args
    ):

        print(
            f"[HTTP] "
            f"{self.address_string()} - "
            f"{format_string % args}"
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print()
    print(
        "======================================"
    )
    print(
        "       SOUNDTOUCH RADIO"
    )
    print(
        "======================================"
    )

    print(
        f"Bose: http://{BOSE_IP}:8090"
    )

    print(
        f"Web : http://<IP-PC>:{SERVER_PORT}"
    )

    print()


    # --------------------------------------------------------
    # Test connessione Bose
    # --------------------------------------------------------

    try:

        info = get_info()


        print(
            "✓ Bose raggiunta"
        )


        print(
            f"  Nome : {info['name']}"
        )


        print(
            f"  Tipo : {info['type']}"
        )


        print(
            f"  IP   : {BOSE_IP}"
        )


    except Exception as error:

        print(
            "✗ ATTENZIONE:"
        )


        print(
            "  La Bose non risponde."
        )


        print(
            f"  Errore: {error}"
        )


        print()


        print(
            "Controlla BOSE_IP in config.cfg."
        )


    print()


    server = ThreadingHTTPServer(
            (
                SERVER_HOST,
                SERVER_PORT
            ),
            Handler
        )


    print(
        "Server avviato."
    )


    print(
        "Premi CTRL+C per uscire."
    )


    print()


    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "\nChiusura..."
        )

        server.server_close()
