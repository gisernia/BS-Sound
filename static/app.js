/* ============================================================
   SoundTouch BS – client-side JS
   ============================================================ */

let volumeTimer    = null;
let currentPresetsData = [];
let targetStationForPreset = null;
let favoritesSet   = new Set(); // ID delle stazioni già nei preferiti

const DEBUG = !!(window.APP_DEBUG === true);
const THEME_STORAGE_KEY = "soundtouch-radio-theme";

// ── Theme ────────────────────────────────────────────────────

function setTheme(theme) {
    const valid = ["system", "light", "dark"].includes(theme) ? theme : "system";
    document.documentElement.dataset.theme = valid;
    try { localStorage.setItem(THEME_STORAGE_KEY, valid); } catch (_) {}
}

function initializeTheme() {
    let theme = "system";
    try { theme = localStorage.getItem(THEME_STORAGE_KEY) || theme; } catch (_) {}
    if (!["system", "light", "dark"].includes(theme)) theme = "system";
    document.documentElement.dataset.theme = theme;
    document.getElementById("themeSelect").value = theme;
}

// ── API helper ───────────────────────────────────────────────

async function api(url, options = {}) {
    const response = await fetch(url, options);
    const text = await response.text();
    let data;
    try { data = JSON.parse(text); }
    catch { throw new Error(text || "Risposta non valida"); }
    if (!response.ok || data.ok === false) throw new Error(data.error || "Errore");
    return data;
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
}

// ── Status / refresh ─────────────────────────────────────────

let lastTickerText = "";

function normalizeText(value) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text || "";
}

function isGenericTickerValue(value) {
    const normalized = normalizeText(value).toLowerCase();
    if (!normalized) return true;
    return [
        "song",
        "track",
        "link",
        "unknown",
        "radio",
        "stream",
        "live",
        "now playing",
        "niente in riproduzione"
    ].includes(normalized);
}

function getTickerText(now) {
    const station = normalizeText(now.stationName || now.name);
    const artist = normalizeText(now.artist);
    const track = normalizeText(now.track);
    const icy = normalizeText(now.icyTitle);

    if (artist && track && !isGenericTickerValue(artist) && !isGenericTickerValue(track)) {
        return artist + " - " + track;
    }
    if (artist && !isGenericTickerValue(artist) && artist !== station) {
        return artist;
    }
    if (track && !isGenericTickerValue(track) && track !== station) {
        return track;
    }
    if (icy && !isGenericTickerValue(icy) && icy !== station) {
        return icy;
    }
    return station || "";
}

async function refresh() {
    try {
        const data = await api("/api/status");
        const device = data.device;

        document.getElementById("status").textContent =
            "Bose: " + (device.name || device.type || "SoundTouch") + " · " + device.ip;

        const now = data.now;
        const stationName = normalizeText(now.stationName || now.name || now.track || "");
        const details = [normalizeText(now.artist), normalizeText(now.album)].filter(Boolean).join(" · ");
        const tickerText = getTickerText(now);
        const favicon = now.favicon || "";

        if (DEBUG) {
            const debugPanel = document.getElementById("debugPanel");
            const debugMeta = document.getElementById("debugMeta");
            if (debugPanel && debugMeta) {
                debugPanel.hidden = false;
                debugMeta.textContent = JSON.stringify({
                    timestamp: new Date().toISOString(),
                    device: data.device,
                    now: now,
                    volume: data.volume,
                    presets: data.presets
                }, null, 2);
            }
        } else {
            const debugPanel = document.getElementById("debugPanel");
            if (debugPanel) debugPanel.hidden = true;
        }

        document.getElementById("nowTitle").textContent = stationName || "";
        document.getElementById("nowDetails").textContent = details || "";

        const icyEl = document.getElementById("nowIcy");
        if (tickerText && tickerText !== lastTickerText) {
            const escaped = escapeHtml(tickerText);
            icyEl.innerHTML = '<div class="ticker-wrap"><div class="ticker-track"><span class="ticker-text">' + escaped + '</span></div></div>';
            lastTickerText = tickerText;
        } else if (!tickerText) {
            icyEl.innerHTML = "";
            lastTickerText = "";
        }

        // Favicon radio
        const faviconEl = document.getElementById("nowFavicon");
        if (favicon) {
            faviconEl.src = favicon;
            faviconEl.style.display = "block";
            faviconEl.onerror = () => { faviconEl.style.display = "none"; };
        } else {
            faviconEl.style.display = "none";
        }

        document.getElementById("volume").value = data.volume.actual;
        document.getElementById("volumeText").textContent = data.volume.actual;

        renderPresets(data.presets);
        document.getElementById("error").textContent = "";
    } catch (error) {
        document.getElementById("status").textContent = "❌ Bose non raggiungibile";
        document.getElementById("error").textContent = error.message;
    }
}

// ── Presets ──────────────────────────────────────────────────

function renderPresets(presets) {
    currentPresetsData = presets || [];
    const box = document.getElementById("presets");
    box.innerHTML = "";

    for (let i = 1; i <= 6; i++) {
        const preset = (presets || []).find(p => p.id === i);
        const btn = document.createElement("button");
        btn.className = "preset";
        btn.textContent = i + ": " + (preset?.name || "vuoto");
        btn.onclick = () => callPreset(i);
        box.appendChild(btn);
    }
}

async function callPreset(number) {
    try {
        await api("/api/preset/" + number, { method: "POST" });
        await refresh();
    } catch (error) { showError(error); }
}

// ── Playback controls ────────────────────────────────────────

async function sendKey(key) {
    try {
        await api("/api/key/" + encodeURIComponent(key), { method: "POST" });
        await refresh();
    } catch (error) { showError(error); }
}

function changeVolume(value) {
    document.getElementById("volumeText").textContent = value;
    clearTimeout(volumeTimer);
    volumeTimer = setTimeout(async () => {
        try {
            await api("/api/volume/" + value, { method: "POST" });
        } catch (error) { showError(error); }
    }, 150);
}

// ── Search ───────────────────────────────────────────────────

async function searchRadio() {
    const query = document.getElementById("query").value.trim();
    if (!query) return;
    const country = document.getElementById("country").value.trim();
    try {
        const data = await api(
            "/api/search?q=" + encodeURIComponent(query) +
            "&country=" + encodeURIComponent(country)
        );
        renderStations(data.stations);
    } catch (error) { showError(error); }
}

// ── Station list (risultati ricerca) ─────────────────────────

function renderStations(stations) {
    const box = document.getElementById("results");
    box.innerHTML = "";

    if (!stations || stations.length === 0) {
        box.innerHTML = '<div style="color:var(--muted)">Nessuna stazione trovata.</div>';
        return;
    }

    stations.forEach(station => {
        const row = document.createElement("div");
        row.className = "station";

        row.innerHTML =
            '<img src="' + escapeHtml(station.favicon || "") +
            '" onerror="this.style.visibility=\'hidden\'">' +
            '<div class="station-main">' +
              '<div class="station-name">' + escapeHtml(station.name) + '</div>' +
              '<div class="station-meta">' +
                escapeHtml(station.country) + " · " +
                escapeHtml(station.codec) + " · " +
                escapeHtml(station.bitrate) + " kbps" +
              '</div>' +
            '</div>';

        const btnPlay = document.createElement("button");
        btnPlay.textContent = "▶";
        btnPlay.onclick = () => playStation(station);
        row.appendChild(btnPlay);

        const stationId = station.id || station.stream || "";
        const isFav = favoritesSet.has(stationId);
        const btnFav = document.createElement("button");
        btnFav.className = "btn-star" + (isFav ? " btn-star--fav" : "");
        btnFav.title = isFav ? "Rimuovi dai preferiti" : "Aggiungi ai preferiti";
        btnFav.innerHTML = isFav ? '<span class="star-cancel">★</span>' : "☆";
        btnFav.onclick = () => isFav ? confirmRemoveFavorite(station) : saveFavorite(station);
        row.appendChild(btnFav);

        const btnPreset = document.createElement("button");
        btnPreset.textContent = "＋";
        btnPreset.title = "Salva in un preset Bose";
        btnPreset.onclick = () => savePreset(station);
        row.appendChild(btnPreset);

        box.appendChild(row);
    });
}

// ── Play ─────────────────────────────────────────────────────

async function playStation(station) {
    try {
        await api("/api/play", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(station)
        });
        await refresh();
    } catch (error) { showError(error); }
}

// ── Preset modal ─────────────────────────────────────────────

function openPresetModal(station) {
    targetStationForPreset = station;
    const nameEl = document.getElementById("modalStationName");
    if (nameEl) nameEl.textContent = station.name || "Radio";
    renderPresetModalGrid();
    document.getElementById("presetModal").style.display = "flex";
}

function closePresetModal() {
    document.getElementById("presetModal").style.display = "none";
    targetStationForPreset = null;
}

function renderPresetModalGrid() {
    const grid = document.getElementById("presetModalGrid");
    if (!grid) return;
    grid.innerHTML = "";

    for (let i = 1; i <= 6; i++) {
        const preset = (currentPresetsData || []).find(p => p.id === i);
        const occupied = preset && preset.name;

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "preset-slot-btn";
        btn.innerHTML =
            '<div class="preset-slot-num">Preset ' + i + '</div>' +
            '<div class="preset-slot-title">' + escapeHtml(occupied ? preset.name : "Vuoto") + '</div>' +
            '<span class="' + (occupied ? "badge-occupied" : "badge-free") + '">' +
              (occupied ? "⚠️ Sostituisci" : "✓ Libero") +
            '</span>';
        btn.onclick = () => confirmSavePreset(i);
        grid.appendChild(btn);
    }
}

async function confirmSavePreset(presetNumber) {
    if (!targetStationForPreset) return;
    const station = targetStationForPreset;
    closePresetModal();
    try {
        await api("/api/preset/" + presetNumber + "/store", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(station)
        });
        await refresh();
    } catch (err) { showError(err); }
}

async function savePreset(station) {
    openPresetModal(station);
}

// ── Favorites ────────────────────────────────────────────────

async function loadFavorites() {
    const box = document.getElementById("favorites");
    try {
        const response = await fetch("/api/favorites");
        const text = await response.text();
        let data;
        try { data = JSON.parse(text); } catch(e) {
            box.innerHTML = '<div style="color:red">JSON parse error: ' + escapeHtml(text.slice(0,200)) + '</div>';
            return;
        }
        if (!data.ok) {
            box.innerHTML = '<div style="color:red">API error: ' + escapeHtml(data.error || '?') + '</div>';
            return;
        }
        const favs = data.favorites || [];

        // aggiorna il set
        favoritesSet = new Set(favs.map(f => f.id || f.stream || ""));

        if (favs.length === 0) {
            box.innerHTML = '<div style="color:var(--muted); font-size:13px; padding:8px 0;">Nessun preferito salvato.</div>';
            return;
        }

        box.innerHTML = "";
        favs.forEach(station => {
            const row = document.createElement("div");
            row.className = "station";
            row.innerHTML =
                '<img src="' + escapeHtml(station.favicon || "") +
                '" onerror="this.style.visibility=\'hidden\'">' +
                '<div class="station-main">' +
                  '<div class="station-name">' + escapeHtml(station.name) + '</div>' +
                  '<div class="station-meta">' + escapeHtml(station.country || "") + '</div>' +
                '</div>';

            const btnPlay = document.createElement("button");
            btnPlay.textContent = "▶";
            btnPlay.onclick = () => playStation(station);
            row.appendChild(btnPlay);

            const btnDel = document.createElement("button");
            btnDel.className = "btn-star btn-star--fav";
            btnDel.title = "Rimuovi dai preferiti";
            btnDel.innerHTML = '<span class="star-cancel">★</span>';
            btnDel.onclick = () => confirmRemoveFavorite(station);
            row.appendChild(btnDel);

            const btnPreset = document.createElement("button");
            btnPreset.textContent = "＋";
            btnPreset.title = "Salva in un preset Bose";
            btnPreset.onclick = () => savePreset(station);
            row.appendChild(btnPreset);

            box.appendChild(row);
        });
    } catch (error) {
        box.innerHTML = '<div style="color:red">Fetch error: ' + escapeHtml(String(error)) + '</div>';
    }
}

async function saveFavorite(station) {
    try {
        const payload = Object.assign({}, station);
        payload.stream = payload.stream || payload.url_resolved || payload.url;
        await api("/api/favorite", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        await loadFavorites();
        // ridisegna la lista risultati per aggiornare le stelle
        const lastQuery = document.getElementById("query").value.trim();
        if (lastQuery) searchRadio();
    } catch (error) { showError(error); }
}

function confirmRemoveFavorite(station) {
    document.getElementById("removeFavName").textContent = station.name || "questa stazione";
    document.getElementById("removeFavModal").style.display = "flex";
    document.getElementById("removeFavConfirm").onclick = async () => {
        document.getElementById("removeFavModal").style.display = "none";
        try {
            await api("/api/favorite/remove", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ id: station.id, stream: station.stream || station.url_resolved || station.url })
            });
            await loadFavorites();
            const lastQuery = document.getElementById("query").value.trim();
            if (lastQuery) searchRadio();
        } catch (error) { showError(error); }
    };
}

// ── Utils ─────────────────────────────────────────────────────

function showError(error) {
    document.getElementById("error").textContent = error.message || String(error);
}

// ── Init ──────────────────────────────────────────────────────

initializeTheme();
loadFavorites();
refresh();
setInterval(refresh, 5000);
