#!/usr/bin/env python3

# Copyright 2026 Beasof.com
# Licensed under the Apache License, Version 2.0.

import html
import json
import threading
import time
import traceback
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ============================================================
# CONFIG
# ============================================================

BASE_DIR      = Path(__file__).resolve().parent
CONFIG_FILE   = BASE_DIR / "config.cfg"
FAVORITES_FILE = BASE_DIR / "favorites.json"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR    = BASE_DIR / "static"

DEFAULT_CONFIG = {
    "BOSE_IP":            "192.168.1.52",
    "SERVER_HOST":        "0.0.0.0",
    "SERVER_PORT":        "8765",
    "RADIO_BROWSER_HOST": "https://de1.api.radio-browser.info",
}


def load_config():
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    return config


CONFIG           = load_config()
BOSE_IP          = CONFIG["BOSE_IP"]
SERVER_HOST      = CONFIG["SERVER_HOST"]
SERVER_PORT      = int(CONFIG["SERVER_PORT"])
RADIO_BROWSER_HOST = CONFIG["RADIO_BROWSER_HOST"].rstrip("/")


# ============================================================
# HTTP UTILS
# ============================================================

def http_request(url, method="GET", body=None, content_type=None,
                 timeout=8, extra_headers=None):
    headers = {"User-Agent": "SoundTouchRadio/1.0"}
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if body is not None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        if content_type:
            headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ============================================================
# BOSE SOUNDTOUCH API
# ============================================================

def bose_url(path):
    return f"http://{BOSE_IP}:8090{path}"

def bose_get(path):
    return http_request(bose_url(path), timeout=5).decode("utf-8", "replace")

def bose_post(path, xml):
    return http_request(
        bose_url(path), method="POST", body=xml,
        content_type="application/xml; charset=utf-8", timeout=8
    ).decode("utf-8", "replace")


# ============================================================
# XML HELPERS
# ============================================================

def xml_text(node, tag, default=""):
    if node is None:
        return default
    el = node.find(tag)
    if el is None or el.text is None:
        return default
    return el.text.strip()


# ============================================================
# BOSE INFO
# ============================================================

def get_info():
    root = ET.fromstring(bose_get("/info"))
    return {
        "ip":   BOSE_IP,
        "name": xml_text(root, "name"),
        "type": xml_text(root, "type"),
        "mac":  root.attrib.get("deviceID", ""),
    }


# ============================================================
# NOW PLAYING
# ============================================================

def get_now_playing():
    root    = ET.fromstring(bose_get("/now_playing"))
    content = root.find("ContentItem")
    return {
        "source":      root.attrib.get("source", ""),
        "name":        xml_text(content, "itemName"),
        "track":       xml_text(root, "track"),
        "artist":      xml_text(root, "artist"),
        "album":       xml_text(root, "album"),
        "stationName": xml_text(root, "stationName"),
        "description": xml_text(root, "description"),
        "playStatus":  xml_text(root, "playStatus"),
        "art":         xml_text(root, "art"),
    }


# ============================================================
# VOLUME
# ============================================================

def get_volume():
    root = ET.fromstring(bose_get("/volume"))
    mute = (root.findtext("muteenabled") or "").lower()
    return {
        "target": int(root.findtext("targetvolume") or 0),
        "actual": int(root.findtext("actualvolume") or 0),
        "mute":   mute == "true",
    }

def set_volume(value):
    value = max(0, min(100, int(value)))
    return bose_post("/volume", f"<volume>{value}</volume>")


# ============================================================
# KEYS
# ============================================================

def press_key(key):
    sender = "Gabbo"
    bose_post("/key", f'<key state="press"   sender="{sender}">{html.escape(key)}</key>')
    bose_post("/key", f'<key state="release" sender="{sender}">{html.escape(key)}</key>')


# ============================================================
# PRESETS
# ============================================================

def get_presets():
    root   = ET.fromstring(bose_get("/presets"))
    result = []
    for preset in root.findall("preset"):
        content = preset.find("ContentItem")
        result.append({
            "id":       int(preset.attrib.get("id", "0")),
            "name":     xml_text(content, "itemName"),
            "source":   content.attrib.get("source", "")   if content is not None else "",
            "location": content.attrib.get("location", "") if content is not None else "",
        })
    return result


# ============================================================
# PLAY RADIO STREAM  (UPnP AVTransport — post Bose cloud shutdown)
#
# LOCAL_INTERNET_RADIO e INTERNET_RADIO restituiscono
# UNKNOWN_SOURCE_ERROR 1005 dopo lo shutdown del cloud Bose (maggio 2026).
# L'unico metodo funzionante è UPnP AVTransport sulla porta 8091.
# Implementazione basata su: alinossier/soundtouch-local-presets (MIT)
# ============================================================

_virtual_presets      = {}
_virtual_presets_lock = threading.Lock()


def _save_virtual_preset(number, name, stream_url, favicon=""):
    with _virtual_presets_lock:
        _virtual_presets[number] = {"name": name, "stream_url": stream_url, "favicon": favicon}

def get_virtual_preset(number):
    with _virtual_presets_lock:
        return _virtual_presets.get(number)


def resolve_stream_url(url):
    """Risolve playlist .pls/.m3u al primo URL diretto trovato."""
    if not url:
        return url
    if url.lower().endswith((".pls", ".m3u")):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SoundTouchRadio/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                for line in resp.read().decode("utf-8", "ignore").splitlines():
                    line = line.strip()
                    if line.startswith("http://") or line.startswith("https://"):
                        return line
                    if line.startswith("File1="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return url

def _force_http(url):
    """La Bose SoundTouch non supporta HTTPS per UPnP."""
    return "http://" + url[8:] if url.startswith("https://") else url


def _soap_envelope(action, body):
    return (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body>'
        f'<u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">{body}</u:{action}>'
        '</s:Body>'
        '</s:Envelope>'
    )

def _post_avtransport(action, body):
    url     = f"http://{BOSE_IP}:8091/AVTransport/Control"
    payload = _soap_envelope(action, body).encode("utf-8")
    headers = {
        "User-Agent":  "SoundTouchRadio/1.0",
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction":  f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read()

def play_upnp(stream_url):
    _post_avtransport(
        "SetAVTransportURI",
        f"<InstanceID>0</InstanceID>"
        f"<CurrentURI>{html.escape(stream_url)}</CurrentURI>"
        f"<CurrentURIMetaData></CurrentURIMetaData>",
    )
    _post_avtransport("Play", "<InstanceID>0</InstanceID><Speed>1</Speed>")

def play_radio(name, stream_url, favicon=""):
    if not stream_url:
        raise ValueError("La stazione non ha un URL stream.")
    play_upnp(_force_http(resolve_stream_url(stream_url)))
    return "OK"

def store_radio_preset(number, name, stream_url, favicon=""):
    if not 1 <= number <= 6:
        raise ValueError("Preset deve essere 1..6")
    if not stream_url:
        raise ValueError("La stazione non ha un URL stream.")
    _save_virtual_preset(number, name, _force_http(resolve_stream_url(stream_url)), favicon)


# ============================================================
# RADIO BROWSER
# ============================================================

def radio_search(query, country="", limit=40):
    params = {
        "name":        query,
        "limit":       str(min(max(limit, 1), 100)),
        "order":       "votes",
        "reverse":     "true",
        "hidebroken":  "true",
    }
    if country:
        params["countrycode"] = country.upper()
    url      = RADIO_BROWSER_HOST + "/json/stations/search?" + urllib.parse.urlencode(params)
    stations = json.loads(http_request(url, timeout=12).decode("utf-8"))
    result   = []
    for s in stations:
        stream = s.get("url_resolved") or s.get("url")
        if not stream:
            continue
        result.append({
            "id":       s.get("stationuuid", ""),
            "name":     s.get("name", ""),
            "country":  s.get("country", ""),
            "language": s.get("language", ""),
            "codec":    s.get("codec", ""),
            "bitrate":  s.get("bitrate", 0),
            "homepage": s.get("homepage", ""),
            "favicon":  s.get("favicon", ""),
            "stream":   stream,
        })
    return result


# ============================================================
# FAVORITES
# ============================================================

_favorites_lock = threading.Lock()

def load_favorites():
    if not FAVORITES_FILE.exists():
        return []
    try:
        data = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

def save_favorites(favorites):
    with _favorites_lock:
        FAVORITES_FILE.write_text(
            json.dumps(favorites, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )


# ============================================================
# WEB INTERFACE
# ============================================================

MIME_TYPES = {
    ".css":   "text/css; charset=utf-8",
    ".js":    "application/javascript; charset=utf-8",
    ".html":  "text/html; charset=utf-8",
    ".png":   "image/png",
    ".jpg":   "image/jpeg",
    ".svg":   "image/svg+xml",
    ".ico":   "image/x-icon",
    ".woff2": "font/woff2",
    ".woff":  "font/woff",
}

def render_template(name):
    path = TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Template non trovato: {name}")
    return path.read_bytes()

def serve_static(filename):
    path = STATIC_DIR / filename
    try:
        path.resolve().relative_to(STATIC_DIR.resolve())
    except ValueError:
        raise PermissionError("Accesso negato")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File statico non trovato: {filename}")
    return MIME_TYPES.get(path.suffix.lower(), "application/octet-stream"), path.read_bytes()


# ============================================================
# WEB SERVER
# ============================================================

class Handler(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw    = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    # ── GET ──────────────────────────────────────────────────

    def do_GET(self):
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path   = parsed.path

            # Home
            if path == "/":
                data = render_template("index.html")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            # Static files
            if path.startswith("/static/"):
                try:
                    ct, data = serve_static(path[len("/static/"):])
                except (FileNotFoundError, PermissionError) as exc:
                    self.send_json({"ok": False, "error": str(exc)}, 404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(data)
                return

            # Status
            if path == "/api/status":
                info   = get_info()
                now    = get_now_playing()
                volume = get_volume()
                # Merge preset Bose + preset virtuali (i virtuali hanno priorità)
                merged = {p["id"]: p for p in get_presets()}
                with _virtual_presets_lock:
                    for num, vp in _virtual_presets.items():
                        merged[num] = {"id": num, "name": vp["name"],
                                       "source": "VIRTUAL", "location": ""}
                self.send_json({
                    "ok": True,
                    "device":  info,
                    "now":     now,
                    "volume":  volume,
                    "presets": sorted(merged.values(), key=lambda p: p["id"]),
                })
                return

            # Radio search
            if path == "/api/search":
                qs      = urllib.parse.parse_qs(parsed.query)
                q       = qs.get("q",       [""])[0]
                country = qs.get("country", [""])[0]
                self.send_json({"ok": True, "stations": radio_search(q, country)})
                return

            # Favorites
            if path == "/api/favorites":
                self.send_json({"ok": True, "favorites": load_favorites()})
                return

            self.send_json({"ok": False, "error": "Not found"}, 404)

        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)

    # ── POST ─────────────────────────────────────────────────

    def do_POST(self):
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path   = parsed.path

            # Key
            if path.startswith("/api/key/"):
                press_key(urllib.parse.unquote(path[len("/api/key/"):]))
                self.send_json({"ok": True})
                return

            # Volume
            if path.startswith("/api/volume/"):
                value = int(path[len("/api/volume/"):])
                set_volume(value)
                self.send_json({"ok": True, "volume": value})
                return

            # Preset
            if path.startswith("/api/preset/"):
                parts  = path.split("/")
                if len(parts) not in (4, 5):
                    raise ValueError("URL preset non valido")
                number = int(parts[3])
                if not 1 <= number <= 6:
                    raise ValueError("Preset deve essere 1..6")
                action = parts[4] if len(parts) == 5 else "play"

                if action == "store":
                    s      = self.read_json()
                    stream = s.get("stream") or s.get("url_resolved") or s.get("url", "")
                    if not stream:
                        raise ValueError("La stazione non ha uno stream valido.")
                    store_radio_preset(number, s.get("name", "Radio"), stream, s.get("favicon", ""))

                elif action == "remove":
                    bose_post("/removePreset", f'<preset id="{number}"/>')

                elif action == "play":
                    virtual = get_virtual_preset(number)
                    if virtual:
                        play_upnp(virtual["stream_url"])
                    else:
                        # Preset fisico Bose (post-cloud può non funzionare)
                        try:
                            press_key(f"PRESET_{number}")
                        except Exception:
                            pass

                else:
                    raise ValueError("Azione preset non valida")

                self.send_json({"ok": True})
                return

            # Play
            if path == "/api/play":
                s      = self.read_json()
                stream = s.get("stream") or s.get("url_resolved") or s.get("url")
                if not stream:
                    raise ValueError("La stazione non ha uno stream.")
                play_radio(s.get("name", "Radio"), stream, s.get("favicon", ""))
                self.send_json({"ok": True})
                return

            # Favorite
            if path == "/api/favorite":
                s      = self.read_json()
                stream = s.get("stream") or s.get("url_resolved") or s.get("url")
                if not stream:
                    raise ValueError("Stream mancante.")
                s["stream"]  = stream
                station_id   = s.get("id") or stream
                favorites    = [f for f in load_favorites()
                                if (f.get("id") or f.get("stream")) != station_id]
                favorites.insert(0, s)
                favorites = favorites[:100]
                save_favorites(favorites)
                self.send_json({"ok": True, "favorites": favorites})
                return

            self.send_json({"ok": False, "error": "Not found"}, 404)

        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            print(f"[BOSE HTTP ERROR] {exc.code} {exc.reason}: {body[:300]}")
            self.send_json({
                "ok": False,
                "error": f"Bose HTTP {exc.code}: {exc.reason}" + (f" — {body[:200]}" if body else "")
            }, 502)

        except Exception as exc:
            print(f"[ERROR] {traceback.format_exc()}")
            self.send_json({"ok": False, "error": str(exc)}, 500)

    def log_message(self, fmt, *args):
        print(f"[HTTP] {self.address_string()} - {fmt % args}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print()
    print("======================================")
    print("       SOUNDTOUCH RADIO")
    print("======================================")
    print(f"Bose: http://{BOSE_IP}:8090")
    print(f"Web : http://<IP-PC>:{SERVER_PORT}")
    print()

    try:
        info = get_info()
        print("✓ Bose raggiunta")
        print(f"  Nome : {info['name']}")
        print(f"  Tipo : {info['type']}")
        print(f"  IP   : {BOSE_IP}")
    except Exception as exc:
        print("✗ ATTENZIONE: La Bose non risponde.")
        print(f"  Errore: {exc}")
        print("  Controlla BOSE_IP in config.cfg.")

    print()
    server = ThreadingHTTPServer((SERVER_HOST, SERVER_PORT), Handler)
    print("Server avviato. Premi CTRL+C per uscire.")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nChiusura...")
        server.server_close()
