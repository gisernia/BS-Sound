#!/usr/bin/env python3

# Copyright 2026 Beasof.com
# Licensed under the Apache License, Version 2.0.

import html
import json
import threading
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

    sender = "SoundTouchRadio"

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

def play_radio(
    name,
    stream_url,
    favicon=""
):

    if not stream_url:
        raise ValueError(
            "La stazione non ha un URL stream."
        )

    # URL-encode della radio.
    #
    # SoundTouch accetta LOCAL_INTERNET_RADIO
    # con type=stationurl.
    #
    # Formato usato:
    #
    #   location="...?streamUrl=<URL>"
    #
    # Questo è il meccanismo documentato/usato
    # dalle implementazioni SoundTouch.
    #
    encoded_stream = urllib.parse.quote(
        stream_url,
        safe=""
    )

    location = (
        "http://contentapi.gmuth.de/"
        "station.php?"
        "name="
        + urllib.parse.quote(
            name,
            safe=""
        )
        +
        "&streamUrl="
        +
        encoded_stream
    )

    xml = (
        '<ContentItem '
        'source="LOCAL_INTERNET_RADIO" '
        'type="stationurl" '
        f'location="{html.escape(location, quote=True)}" '
        'isPresetable="false">'
        f'<itemName>{html.escape(name)}</itemName>'
    )

    if favicon:

        xml += (
            f'<containerArt>'
            f'{html.escape(favicon)}'
            f'</containerArt>'
        )

    xml += "</ContentItem>"

    return bose_post(
        "/select",
        xml
    )


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

        params[
            "countrycode"
        ] = country.upper()

    url = (
        RADIO_BROWSER_HOST
        +
        "/json/stations/search?"
        +
        urllib.parse.urlencode(
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
            station.get(
                "url_resolved"
            )
            or
            station.get(
                "url"
            )
        )

        if not stream:
            continue

        result.append({

            "id":
                station.get(
                    "stationuuid",
                    ""
                ),

            "name":
                station.get(
                    "name",
                    ""
                ),

            "country":
                station.get(
                    "country",
                    ""
                ),

            "language":
                station.get(
                    "language",
                    ""
                ),

            "codec":
                station.get(
                    "codec",
                    ""
                ),

            "bitrate":
                station.get(
                    "bitrate",
                    0
                ),

            "homepage":
                station.get(
                    "homepage",
                    ""
                ),

            "favicon":
                station.get(
                    "favicon",
                    ""
                ),

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

HTML = r"""
<!DOCTYPE html>

<html lang="it" data-theme="system">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,
             initial-scale=1,
             viewport-fit=cover"
>

<meta
    name="apple-mobile-web-app-capable"
    content="yes"
>

<title>SoundTouch Radio</title>


<style>

:root {

    color-scheme: dark;

    --page-bg: #101010;
    --surface-bg: #1b1b1b;
    --header-bg: #181818;
    --control-bg: #292929;
    --input-bg: #101010;
    --border: #333;
    --control-border: #444;
    --text: #eee;
    --muted: #aaa;
    --subtle: #999;
    --image-bg: #222;
    --primary-bg: #eee;
    --primary-text: #111;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}


:root[data-theme="light"] {

    color-scheme: light;

    --page-bg: #f5f5f7;
    --surface-bg: #ffffff;
    --header-bg: #ffffff;
    --control-bg: #f0f0f2;
    --input-bg: #ffffff;
    --border: #d7d7dc;
    --control-border: #c6c6cc;
    --text: #1c1c1e;
    --muted: #5d5d64;
    --subtle: #6f6f77;
    --image-bg: #ececf0;
    --primary-bg: #1c1c1e;
    --primary-text: #ffffff;
}


@media (prefers-color-scheme: light) {

    :root[data-theme="system"] {

        color-scheme: light;

        --page-bg: #f5f5f7;
        --surface-bg: #ffffff;
        --header-bg: #ffffff;
        --control-bg: #f0f0f2;
        --input-bg: #ffffff;
        --border: #d7d7dc;
        --control-border: #c6c6cc;
        --text: #1c1c1e;
        --muted: #5d5d64;
        --subtle: #6f6f77;
        --image-bg: #ececf0;
        --primary-bg: #1c1c1e;
        --primary-text: #ffffff;
    }
}


* {
    box-sizing: border-box;
}


body {

    margin: 0;

    background: var(--page-bg);

    color: var(--text);
}


header {

    position: sticky;

    top: 0;

    z-index: 10;

    padding: 15px;

    background: var(--header-bg);

    border-bottom:
        1px solid var(--border);
}


h1 {

    margin: 0 0 5px;

    font-size: 21px;
}


.status {

    font-size: 13px;

    color: var(--muted);
}


.theme-control {

    display: flex;

    align-items: center;

    gap: 6px;

    margin-top: 10px;

    font-size: 13px;

    color: var(--muted);
}


select {

    font: inherit;

    color: var(--text);

    background: var(--control-bg);

    border: 1px solid var(--control-border);

    border-radius: 8px;

    padding: 5px 8px;
}


main {

    max-width: 900px;

    margin: auto;

    padding: 14px;
}


.card {

    background: var(--surface-bg);

    border:
        1px solid var(--border);

    border-radius: 16px;

    padding: 14px;

    margin-bottom: 14px;
}


.row {

    display: flex;

    gap: 8px;

    align-items: center;

    flex-wrap: wrap;
}


input,
button {

    font: inherit;
}


input {

    background: var(--input-bg);

    color: var(--text);

    border:
        1px solid var(--control-border);

    border-radius: 11px;

    padding: 11px;

    min-width: 0;
}


.searchbox {

    flex: 1;

    min-width: 160px;
}


button {

    background: var(--control-bg);

    color: var(--text);

    border:
        1px solid var(--control-border);

    border-radius: 11px;

    padding: 10px 13px;
}


button.primary {

    background: var(--primary-bg);

    color: var(--primary-text);
}


button:active {

    transform: scale(.97);
}


.now-title {

    font-size: 18px;

    font-weight: 600;
}


.now-details {

    color: var(--muted);

    font-size: 13px;

    margin-top: 4px;
}


.controls {

    margin-top: 13px;
}


.volume {

    flex: 1;

    min-width: 130px;
}


.station {

    display: flex;

    gap: 10px;

    align-items: center;

    padding: 11px 0;

    border-bottom:
        1px solid var(--border);
}


.station:last-child {

    border-bottom: none;
}


.station img {

    width: 45px;

    height: 45px;

    object-fit: contain;

    border-radius: 8px;

    background: var(--image-bg);
}


.station-main {

    flex: 1;

    min-width: 0;
}


.station-name {

    font-weight: 600;

    overflow: hidden;

    white-space: nowrap;

    text-overflow: ellipsis;
}


.station-meta {

    color: var(--subtle);

    font-size: 12px;

    margin-top: 3px;
}


.preset {

    flex: 1;

    min-width: 110px;
}


.small {

    color: var(--subtle);

    font-size: 12px;

}


.error {

    color: #ff8d8d;

    white-space: pre-wrap;
}


</style>

</head>


<body>


<header>

<h1>📻 SoundTouch Radio</h1>

<div
    class="status"
    id="status"
>
Connessione...
</div>


<div class="theme-control">

<label for="themeSelect">Tema</label>

<select
    id="themeSelect"
    aria-label="Tema dell'interfaccia"
    onchange="setTheme(this.value)"
>
    <option value="system">Sistema</option>
    <option value="light">Light</option>
    <option value="dark">Dark</option>
</select>

</div>

</header>


<main>


<!-- NOW PLAYING -->

<section class="card">

<div
    class="now-title"
    id="nowTitle"
>
—
</div>


<div
    class="now-details"
    id="nowDetails"
>
</div>


<div
    class="row controls"
>

<button onclick="sendKey('PLAY_PAUSE')">
⏯
</button>

<button onclick="sendKey('PREV_TRACK')">
⏮
</button>

<button onclick="sendKey('NEXT_TRACK')">
⏭
</button>

<button onclick="sendKey('MUTE')">
🔇
</button>


<input
    class="volume"
    id="volume"
    type="range"
    min="0"
    max="100"
    value="0"
    oninput="changeVolume(this.value)"
>


<span id="volumeText">
--
</span>

</div>

</section>


<!-- SEARCH -->

<section class="card">

<div class="row">

<input
    id="query"
    class="searchbox"
    placeholder="Cerca radio..."
    onkeydown="
        if(event.key === 'Enter')
            searchRadio()
    "
>


<button
    class="primary"
    onclick="searchRadio()"
>
Cerca
</button>

</div>


<div
    class="row"
    style="margin-top:8px"
>

<input
    id="country"
    placeholder="Paese ISO, es. IT"
>


<button
    onclick="loadFavorites()"
>
⭐ Preferite
</button>

</div>

</section>


<!-- PRESETS -->

<section class="card">

<b>Preset Bose</b>

<div
    class="row"
    id="presets"
    style="margin-top:10px"
>
</div>

</section>


<!-- RESULTS -->

<section class="card">

<div id="results"></div>

<div
    class="error"
    id="error"
></div>

</section>


</main>


<script>


let volumeTimer = null;


const THEME_STORAGE_KEY = "soundtouch-radio-theme";


function setTheme(theme) {

    const validTheme =
        ["system", "light", "dark"].includes(theme)
            ? theme
            : "system";


    document.documentElement.dataset.theme = validTheme;


    try {

        localStorage.setItem(
            THEME_STORAGE_KEY,
            validTheme
        );

    }

    catch(error) {

        // La scelta resta attiva anche se il browser blocca localStorage.

    }

}


function initializeTheme() {

    let theme = "system";


    try {

        theme = localStorage.getItem(
            THEME_STORAGE_KEY
        ) || theme;

    }

    catch(error) {

        // Usa il tema di sistema se localStorage non è disponibile.

    }


    if(
        !["system", "light", "dark"].includes(theme)
    ) {

        theme = "system";

    }


    document.documentElement.dataset.theme = theme;


    document.getElementById(
        "themeSelect"
    ).value = theme;

}


async function api(
    url,
    options = {}
) {

    const response =
        await fetch(
            url,
            options
        );


    const text =
        await response.text();


    let data;


    try {

        data =
            JSON.parse(text);

    }

    catch {

        throw new Error(
            text
            ||
            "Risposta non valida"
        );

    }


    if (
        !response.ok
        ||
        data.ok === false
    ) {

        throw new Error(
            data.error
            ||
            "Errore"
        );

    }


    return data;
}



function escapeHtml(value) {

    return String(
        value ?? ""
    ).replace(
        /[&<>"']/g,
        function(c) {

            return {

                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;"

            }[c];

        }
    );
}



async function refresh() {

    try {

        const data =
            await api(
                "/api/status"
            );


        const device =
            data.device;


        document.getElementById(
            "status"
        ).textContent =
            "Bose: "
            +
            (
                device.name
                ||
                device.type
                ||
                "SoundTouch"
            )
            +
            " · "
            +
            device.ip;


        const now =
            data.now;


        document.getElementById(
            "nowTitle"
        ).textContent =

            now.stationName
            ||
            now.name
            ||
            now.track
            ||
            "Niente in riproduzione";


        document.getElementById(
            "nowDetails"
        ).textContent =

            [
                now.artist,
                now.track,
                now.album,
                now.playStatus
            ]
            .filter(Boolean)
            .join(" · ");


        document.getElementById(
            "volume"
        ).value =
            data.volume.actual;


        document.getElementById(
            "volumeText"
        ).textContent =
            data.volume.actual;


        renderPresets(
            data.presets
        );


        document.getElementById(
            "error"
        ).textContent = "";

    }

    catch(error) {

        document.getElementById(
            "status"
        ).textContent =
            "❌ Bose non raggiungibile";


        document.getElementById(
            "error"
        ).textContent =
            error.message;

    }

}



function renderPresets(
    presets
) {

    const box =
        document.getElementById(
            "presets"
        );


    box.innerHTML = "";


    for(
        let i = 1;
        i <= 6;
        i++
    ) {

        const preset =
            (
                presets || []
            ).find(
                p => p.id === i
            );


        const button =
            document.createElement(
                "button"
            );


        button.className =
            "preset";


        button.textContent =

            i
            +
            ": "
            +
            (
                preset
                ?.name
                ||
                "vuoto"
            );


        button.onclick =
            function() {

                callPreset(i);

            };


        box.appendChild(
            button
        );

    }

}



async function callPreset(
    number
) {

    try {

        await api(
            "/api/preset/"
            +
            number,
            {
                method: "POST"
            }
        );


        await refresh();

    }

    catch(error) {

        showError(error);

    }

}



async function sendKey(
    key
) {

    try {

        await api(
            "/api/key/"
            +
            encodeURIComponent(
                key
            ),
            {
                method: "POST"
            }
        );


        await refresh();

    }

    catch(error) {

        showError(error);

    }

}



function changeVolume(
    value
) {

    document.getElementById(
        "volumeText"
    ).textContent =
        value;


    clearTimeout(
        volumeTimer
    );


    volumeTimer =
        setTimeout(
            async function() {

                try {

                    await api(
                        "/api/volume/"
                        +
                        value,
                        {
                            method:
                                "POST"
                        }
                    );

                }

                catch(error) {

                    showError(
                        error
                    );

                }

            },
            150
        );

}



async function searchRadio() {

    const query =
        document.getElementById(
            "query"
        ).value.trim();


    if(!query)
        return;


    const country =
        document.getElementById(
            "country"
        ).value.trim();


    try {

        const data =
            await api(
                "/api/search?q="
                +
                encodeURIComponent(
                    query
                )
                +
                "&country="
                +
                encodeURIComponent(
                    country
                )
            );


        renderStations(
            data.stations
        );

    }

    catch(error) {

        showError(error);

    }

}



function renderStations(
    stations
) {

    const box =
        document.getElementById(
            "results"
        );


    box.innerHTML = "";


    if(
        !stations
        ||
        stations.length === 0
    ) {

        box.textContent =
            "Nessuna stazione trovata.";

        return;

    }


    stations.forEach(
        function(station) {

            const row =
                document.createElement(
                    "div"
                );


            row.className =
                "station";


            const img =
                station.favicon
                ||
                "";


            row.innerHTML =

                '<img src="'
                +
                escapeHtml(img)
                +
                '" onerror="this.style.visibility=\'hidden\'">'
                +

                '<div class="station-main">'
                +

                '<div class="station-name">'
                +
                escapeHtml(
                    station.name
                )
                +
                '</div>'
                +

                '<div class="station-meta">'
                +
                escapeHtml(
                    station.country
                )
                +
                " · "
                +
                escapeHtml(
                    station.codec
                )
                +
                " · "
                +
                escapeHtml(
                    station.bitrate
                )
                +
                " kbps"
                +
                '</div>'
                +

                '</div>';


            const play =
                document.createElement(
                    "button"
                );


            play.textContent =
                "▶";


            play.onclick =
                function() {

                    playStation(
                        station
                    );

                };


            const favorite =
                document.createElement(
                    "button"
                );


            favorite.textContent =
                "⭐";


            favorite.onclick =
                function() {

                    saveFavorite(
                        station
                    );

                };


            row.appendChild(
                play
            );


            row.appendChild(
                favorite
            );


            box.appendChild(
                row
            );

        }
    );

}



async function playStation(
    station
) {

    try {

        await api(
            "/api/play",
            {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify(
                        station
                    )

            }
        );


        await refresh();

    }

    catch(error) {

        showError(error);

    }

}



async function saveFavorite(
    station
) {

    try {

        await api(
            "/api/favorite",
            {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify(
                        station
                    )

            }
        );


        loadFavorites();

    }

    catch(error) {

        showError(error);

    }

}



async function loadFavorites() {

    try {

        const data =
            await api(
                "/api/favorites"
            );


        renderStations(
            data.favorites
        );

    }

    catch(error) {

        showError(error);

    }

}



function showError(
    error
) {

    document.getElementById(
        "error"
    ).textContent =
        error.message
        ||
        String(error);

}



initializeTheme();


refresh();


setInterval(
    refresh,
    5000
);


</script>


</body>

</html>
"""


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

                data = HTML.encode(
                        "utf-8"
                    )


                self.send_response(
                    200
                )


                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8"
                )


                self.send_header(
                    "Content-Length",
                    str(len(data))
                )


                self.end_headers()


                self.wfile.write(
                    data
                )


                return


            # ------------------------------------------------
            # STATUS
            # ------------------------------------------------

            if path == "/api/status":

                info = get_info()


                now = get_now_playing()


                volume = get_volume()


                presets = get_presets()


                self.send_json({

                    "ok": True,

                    "device":
                        info,

                    "now":
                        now,

                    "volume":
                        volume,

                    "presets":
                        presets

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

                number = int(
                        path[
                            len("/api/preset/"):
                        ]
                    )


                if number < 1 or number > 6:

                    raise ValueError(
                        "Preset deve essere 1..6"
                    )


                press_key(
                    f"PRESET_{number}"
                )


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


                stream = (
                        station.get(
                            "stream"
                        )
                        or
                        station.get(
                            "url_resolved"
                        )
                        or
                        station.get(
                            "url"
                        )
                    )


                favicon = station.get(
                        "favicon",
                        ""
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


                if not station.get(
                    "stream"
                ):

                    raise ValueError(
                        "Stream mancante."
                    )


                favorites = load_favorites()


                station_id = (
                        station.get(
                            "id"
                        )
                        or
                        station.get(
                            "stream"
                        )
                    )


                favorites = [

                    item

                    for item in favorites

                    if (
                        item.get("id")
                        or
                        item.get("stream")
                    )
                    !=
                    station_id

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

                    "favorites":
                        favorites[:100]

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

            self.send_json(
                {
                    "ok": False,
                    "error":
                        f"HTTP {error.code}: "
                        f"{error.reason}"
                },
                502
            )


        except Exception as error:

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
