"use strict";

const api = () => window.pywebview ? window.pywebview.api : null;

/* ── Helpers ──────────────────────────────────────────────────────── */

function formatSize(bytes) {
  if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + " GB";
  if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + " MB";
  if (bytes >= 1024) return (bytes / 1024).toFixed(2) + " KB";
  return bytes + " B";
}

function toast(msg, duration) {
  duration = duration || 3000;
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), duration);
}

/* ── Tab switching ────────────────────────────────────────────────── */

function activateTab(tabId, updateHash) {
  if (!tabId) return;
  if (tabId === "gameyfin") return;

  const btn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
  const panel = document.getElementById(tabId);
  if (!btn || !panel) return;

  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
  btn.classList.add("active");
  panel.classList.add("active");
  if (updateHash) {
    try { window.location.hash = "#" + tabId; } catch (_) {}
  }
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    activateTab(btn.dataset.tab, true);
  });
});

window.addEventListener("hashchange", () => {
  const h = (window.location.hash || "").replace("#", "").trim().toLowerCase();
  if (h) activateTab(h, false);
});

async function goGameyfin() {
  const a = api();
  if (!a || !a.navigate_main_to_gameyfin) return;
  await a.navigate_main_to_gameyfin();
  if (a.show_main) await a.show_main();
}

/* ── Downloads ────────────────────────────────────────────────────── */

function renderDownloads(records) {
  const container = document.getElementById("downloads-list");
  const empty = document.getElementById("downloads-empty");

  if (!records || records.length === 0) {
    container.innerHTML = "";
    empty.style.display = "";
    return;
  }
  empty.style.display = "none";

  container.innerHTML = records.map(r => {
    const fname = r.last_seen_filename
      ? r.last_seen_filename
      : (r.path ? r.path.split(/[\\/]/).pop() : "unknown");
    const status = r.status || "Unknown";
    const pct = status === "Completed"
      ? 100
      : (r.total_bytes > 0 ? Math.floor((r.received_bytes || 0) / r.total_bytes * 100) : 0);
    const isZip = fname.toLowerCase().endsWith(".zip");

    let badgeClass = "badge-info";
    if (status === "Completed") badgeClass = "badge-success";
    else if (status === "Failed" || status === "Cancelled") badgeClass = "badge-error";
    else if (status === "Downloading") badgeClass = "badge-info";

    let sizeText = "";
    if (status === "Downloading") {
      const got = r.received_bytes ? formatSize(r.received_bytes) : "0 B";
      sizeText = r.total_bytes > 0 ? `${got} / ${formatSize(r.total_bytes)}` : `${got}`;
    } else if (r.total_bytes > 0) {
      sizeText = formatSize(r.total_bytes);
    }

    let buttons = "";
    if (status === "Downloading") {
      buttons = `<button class="btn btn-sm btn-danger" onclick="cancelDl('${r.id}')">Cancel</button>`;
    } else if (status === "Completed") {
      buttons = `<button class="btn btn-sm" onclick="openFile('${esc(r.path)}')">Open</button>
                 <button class="btn btn-sm" onclick="openFolder('${esc(r.path)}')">Folder</button>`;
      if (isZip) {
        buttons += `<button class="btn btn-sm btn-accent" onclick="unzipDl('${esc(r.path)}')">Unzip</button>
                    <button class="btn btn-sm btn-danger" onclick="removeZip('${esc(r.path)}','${r.id}')">Remove ZIP</button>`;
      }
    }
    buttons += `<button class="btn btn-sm" onclick="removeDl('${r.id}')">Remove</button>`;

    const indeterminate = (status === "Downloading" && (!r.total_bytes || r.total_bytes <= 0));
    return `<div class="card" id="dl-${r.id}">
      <div class="card-header">
        <span class="card-title">${esc(fname)}</span>
        <span class="badge ${badgeClass} ${status === "Downloading" ? "badge-pulse" : ""}">${esc(status)}</span>
      </div>
      ${sizeText ? `<div class="card-subtitle">${sizeText}</div>` : ""}
      <div class="progress-outer ${indeterminate ? "progress-indeterminate" : ""}">
        <div class="progress-inner" id="prog-${r.id}" style="width:${pct}%"></div>
      </div>
      <div class="btn-row">${buttons}</div>
    </div>`;
  }).join("");
}

function esc(s) {
  if (!s) return "";
  return s.replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

async function loadDownloads() {
  const a = api(); if (!a) return;
  try {
    const raw = await a.get_downloads();
    const records = JSON.parse(raw);
    renderDownloads(records);
  } catch (e) { console.error("loadDownloads", e); }
}

async function cancelDl(id) { const a = api(); if(a) { await a.cancel_download(id); loadDownloads(); } }
async function removeDl(id) { const a = api(); if(a) { await a.remove_download(id); loadDownloads(); } }
async function openFile(path) { const a = api(); if(a) await a.open_file(path); }
async function openFolder(path) { const a = api(); if(a) await a.open_folder(path); }

async function removeZip(path, id) {
  if (!confirm("Delete the ZIP file?")) return;
  const a = api(); if (!a) return;
  const res = JSON.parse(await a.remove_zip(path));
  if (res.ok) { toast("ZIP removed"); loadDownloads(); }
  else toast("Error: " + res.error);
}

async function unzipDl(path) {
  const a = api(); if (!a) return;
  toast("Starting extraction...");
  const res = JSON.parse(await a.unzip_file(path, ""));
  if (!res.ok) toast("Unzip failed: " + res.error);
}

window._onDownloadProgress = function(id, received, total, pct) {
  const bar = document.getElementById("prog-" + id);
  if (bar) bar.style.width = pct + "%";
};

window._onDownloadComplete = function(id) { loadDownloads(); toast("Download complete!"); };
window._onDownloadError = function(id, msg) { loadDownloads(); toast("Download failed: " + msg); };
window._onUnzipProgress = function(id, pct) { /* could show modal */ };
window._onUnzipFinished = function(id) { toast("Extraction complete!"); loadDownloads(); };
window._onUnzipError = function(id, msg) { toast("Extraction failed: " + msg); };

/* ── Prefixes ─────────────────────────────────────────────────────── */

async function loadPrefixes() {
  const a = api(); if (!a) return;
  try {
    const raw = await a.get_prefixes();
    const list = JSON.parse(raw);
    const container = document.getElementById("prefixes-list");
    const empty = document.getElementById("prefixes-empty");

    if (!list || list.length === 0) {
      container.innerHTML = "";
      empty.style.display = "";
      return;
    }
    empty.style.display = "none";

    container.innerHTML = list.map(p => {
      let scriptOptions = `<option value="">Select script...</option>`;
      (p.scripts || []).forEach(s => {
        scriptOptions += `<option value="${esc(s.path)}">${esc(s.name)}</option>`;
      });

      return `<div class="list-item">
        <span class="list-item-name" title="${esc(p.path)}">${esc(p.name)}</span>
        <div class="list-item-actions">
          <button class="btn btn-sm" onclick="manageShortcuts('${esc(p.name)}')">Shortcuts</button>
          <button class="btn btn-sm" onclick="configPrefix('${esc(p.name)}')">Configure</button>
          <select class="script-select" onchange="launchScript(this)">${scriptOptions}</select>
          <button class="btn btn-sm btn-danger" onclick="deletePrefix('${esc(p.name)}')">Delete</button>
        </div>
      </div>`;
    }).join("");
  } catch (e) { console.error("loadPrefixes", e); }
}

async function launchScript(sel) {
  if (!sel.value) return;
  const a = api(); if (!a) return;
  await a.launch_script(sel.value);
  sel.selectedIndex = 0;
  toast("Launched!");
}

async function configPrefix(name) {
  const a = api(); if (!a) return;
  const raw = await a.get_prefix_config(name);
  const config = JSON.parse(raw);
  const newJson = prompt("Edit config JSON:\n(GAMEID, STORE, MANGOHUD, PROTON_ENABLE_WAYLAND, etc.)",
                         JSON.stringify(config, null, 2));
  if (newJson === null) return;
  try {
    JSON.parse(newJson);
    const res = JSON.parse(await a.save_prefix_config(name, newJson));
    if (res.ok) { toast("Config saved!"); loadPrefixes(); }
    else toast("Error: " + res.error);
  } catch (e) { toast("Invalid JSON"); }
}

async function deletePrefix(name) {
  if (!confirm("Delete prefix '" + name + "'?\n\nThis will PERMANENTLY delete all save data in this prefix!")) return;
  const a = api(); if (!a) return;
  const res = JSON.parse(await a.delete_prefix(name));
  if (res.ok) { toast("Prefix deleted"); loadPrefixes(); }
  else toast("Delete failed");
}

async function manageShortcuts(name) {
  const a = api(); if (!a) return;
  const raw = await a.get_shortcut_files(name);
  const files = JSON.parse(raw);
  if (!files.length) { toast("No shortcuts found for this prefix."); return; }
  const msg = files.map(f => `${f.name} [Desktop: ${f.on_desktop ? "Y" : "N"}, Menu: ${f.on_apps_menu ? "Y" : "N"}]`).join("\n");
  const desktop = [], apps = [];
  for (const f of files) {
    const choice = prompt(f.name + "\n\nType: D=Desktop, M=Menu, B=Both, N=None",
                          (f.on_desktop && f.on_apps_menu) ? "B" : f.on_desktop ? "D" : f.on_apps_menu ? "M" : "N");
    if (choice === null) return;
    const c = (choice || "").toUpperCase();
    if (c === "D" || c === "B") desktop.push(f.basename);
    if (c === "M" || c === "B") apps.push(f.basename);
  }
  const res = JSON.parse(await a.apply_shortcuts(name, JSON.stringify(desktop), JSON.stringify(apps)));
  if (res.ok) toast("Shortcuts updated!");
  else toast("Error: " + res.error);
}

/* ── Settings ─────────────────────────────────────────────────────── */

async function loadSettings() {
  const a = api(); if (!a) return;
  try {
    const raw = await a.get_settings();
    const s = JSON.parse(raw);
    document.getElementById("s-url").value = s.GF_URL || "";
    document.getElementById("s-width").value = s.GF_WINDOW_WIDTH || 1420;
    document.getElementById("s-height").value = s.GF_WINDOW_HEIGHT || 940;
    document.getElementById("s-download-dir").value = s.GF_DEFAULT_DOWNLOAD_DIR || "";
    document.getElementById("s-unzip-dir").value = s.GF_DEFAULT_UNZIP_DIR || "";
    document.getElementById("s-proton").value = s.PROTONPATH || "GE-Proton";
    document.getElementById("s-umu-api").value = s.GF_UMU_API_URL || "";
    document.getElementById("s-minimized").checked = !!s.GF_START_MINIMIZED;
    document.getElementById("s-prompt-unzip").checked = !!s.GF_PROMPT_UNZIP_DIR;
  } catch (e) { console.error("loadSettings", e); }
}

async function openServerSetup() {
  const a = api();
  if (!a || !a.show_server_setup) return;
  await a.show_server_setup();
  if (a.show_main) await a.show_main();
}

async function saveSettings() {
  const a = api(); if (!a) return;
  const data = {
    GF_URL: document.getElementById("s-url").value,
    GF_WINDOW_WIDTH: parseInt(document.getElementById("s-width").value) || 1420,
    GF_WINDOW_HEIGHT: parseInt(document.getElementById("s-height").value) || 940,
    GF_DEFAULT_DOWNLOAD_DIR: document.getElementById("s-download-dir").value,
    GF_DEFAULT_UNZIP_DIR: document.getElementById("s-unzip-dir").value,
    PROTONPATH: document.getElementById("s-proton").value,
    GF_UMU_API_URL: document.getElementById("s-umu-api").value,
    GF_START_MINIMIZED: document.getElementById("s-minimized").checked ? 1 : 0,
    GF_PROMPT_UNZIP_DIR: document.getElementById("s-prompt-unzip").checked ? 1 : 0,
  };
  const res = JSON.parse(await a.save_settings(JSON.stringify(data)));
  if (res.ok) toast("Settings saved!");
  else toast("Error: " + (res.error || "Unknown"));
}

async function browseDir(inputId) {
  const a = api(); if (!a) return;
  const dir = await a.pick_directory("Select Directory");
  if (dir) document.getElementById(inputId).value = dir;
}

/* ── Init ─────────────────────────────────────────────────────────── */

async function init() {
  const a = api();
  if (!a) { setTimeout(init, 100); return; }

  const platform = await a.get_platform();
  if (platform === "linux") {
    document.body.classList.add("is-linux");
  }

  loadDownloads();
  loadPrefixes();
  loadSettings();

  const h = (window.location.hash || "").replace("#", "").trim().toLowerCase();
  if (h) activateTab(h, false);

  setInterval(loadDownloads, 5000);
}

window.addEventListener("pywebviewready", init);
if (window.pywebview) init();
