/* ============================================================
   SoundTouch Radio – client-side JS
   ============================================================ */

let volumeTimer = null;
let currentPresetsData = [];
let targetStationForPreset = null;

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

async function refresh() {
    try {
        const data = await api("/api/status");
        const device = data.device;

        document.getElementById("status").textContent =
            "Bose: " + (device.name || device.type || "SoundTouch") + " · " + device.ip;

        const now = data.now;
        document.getElementById("nowTitle").textContent =
            now.stationName || now.name || now.track || "Niente in riproduzione";

        document.getElementById("nowDetails").textContent =
            [now.artist, now.track, now.album, now.playStatus].filter(Boolean).join(" · ");

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

// ── Station list ─────────────────────────────────────────────

function renderStations(stations) {
    const box = document.getElementById("results");
    box.innerHTML = "";

    if (!stations || stations.length === 0) {
        box.textContent = "Nessuna stazione trovata.";
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

        const btnFav = document.createElement("button");
        btnFav.textContent = "⭐";
        btnFav.onclick = () => saveFavorite(station);

        const btnPreset = document.createElement("button");
        btnPreset.textContent = "＋";
        btnPreset.title = "Salva in un preset Bose";
        btnPreset.onclick = () => savePreset(station);

        row.appendChild(btnPlay);
        row.appendChild(btnFav);
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

async function saveFavorite(station) {
    try {
        const payload = Object.assign({}, station);
        payload.stream = payload.stream || payload.url_resolved || payload.url;
        await api("/api/favorite", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        loadFavorites();
    } catch (error) { showError(error); }
}

async function loadFavorites() {
    try {
        const data = await api("/api/favorites");
        renderStations(data.favorites);
    } catch (error) { showError(error); }
}

// ── Utils ─────────────────────────────────────────────────────

function showError(error) {
    document.getElementById("error").textContent = error.message || String(error);
}

// ── Init ──────────────────────────────────────────────────────

initializeTheme();
refresh();
setInterval(refresh, 5000);
