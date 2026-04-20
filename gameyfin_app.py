"""
Gameyfin Desktop — main entry point.
Uses pywebview (EdgeWebView2 on Windows, WebKitGTK on Linux) for a flicker-free,
OS-native web rendering experience.
"""

import os
import sys

import webview
from dotenv import load_dotenv

from gameyfin_frontend.settings import settings_manager
from gameyfin_frontend.utils import resource_path, normalize_gameyfin_url
from gameyfin_frontend.umu_database import UmuDatabase
from gameyfin_frontend.download_engine import DownloadEngine
from gameyfin_frontend.bridge import GFBridge
from gameyfin_frontend.tray import GameyfinTray


load_dotenv()

# pywebview global settings
webview.settings["ALLOW_DOWNLOADS"] = True
webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
# Homelab HTTPS with private CAs / self-signed certs
webview.settings["IGNORE_SSL_ERRORS"] = True

# JS injected into the Gameyfin web UI after each page load to intercept
# download navigations and route them through the Python bridge using fetch().
DOWNLOAD_INTERCEPT_JS = """
(function() {
    if (window._gfInterceptInstalled) return;
    window._gfInterceptInstalled = true;

    function _gfAbsUrl(url) {
        if (!url) return '';
        try {
            if (url.startsWith('/')) return window.location.origin + url;
        } catch (_) {}
        return url;
    }

    function _gfIsDownloadUrl(url) {
        return !!url && String(url).indexOf('/download/') !== -1;
    }

    function _gfParseFilename(contentDisposition) {
        if (!contentDisposition) return '';
        var match = contentDisposition.match(/filename\\*=(?:UTF-8''|utf-8'')([^;]+)/i);
        if (match) {
            try { return decodeURIComponent(match[1]); } catch (_) { return match[1]; }
        }
        match = contentDisposition.match(/filename\\*=[^']*'([^;]+)/i);
        if (match) {
            try { return decodeURIComponent(match[1]); } catch (_) { return match[1]; }
        }
        match = contentDisposition.match(/filename\\s*=\\s*"?([^";]+)"?/i);
        if (match) return match[1].trim();
        return '';
    }

    function _gfSafeFilename(name, fallback) {
        fallback = fallback || 'download.zip';
        if (!name) return fallback;
        name = name.replace(/[\\\\/:*?"<>|]/g, '_').trim();
        return name || fallback;
    }

    async function _gfDownloadWithFetch(url) {
        var api = window.pywebview && window.pywebview.api;
        if (!api) {
            console.error('[GF] pywebview.api not available');
            return;
        }

        var absUrl = _gfAbsUrl(url);
        var dlId = null;

        try {
            var regResult = JSON.parse(await api.register_download(absUrl));
            if (!regResult.ok) {
                console.error('[GF] register_download failed:', regResult.error);
                return;
            }
            dlId = regResult.id;

            api.navigate_main_to_panel('downloads');

            var response = await fetch(absUrl, { credentials: 'include' });

            if (!response.ok) {
                await api.download_error(dlId, 'HTTP ' + response.status + ' ' + response.statusText);
                return;
            }

            var cd = response.headers.get('Content-Disposition') || '';
            var ct = response.headers.get('Content-Type') || '';
            var total = parseInt(response.headers.get('Content-Length') || '0', 10);

            var serverFilename = _gfParseFilename(cd);
            var filename = _gfSafeFilename(serverFilename, 'download.zip');

            if (ct.toLowerCase().startsWith('text/html')) {
                await api.download_error(dlId, 'Server returned HTML instead of a file (authentication may have failed)');
                return;
            }

            var reader = response.body.getReader();
            var chunks = [];
            var received = 0;
            var lastProgress = 0;

            while (true) {
                var result = await reader.read();
                if (result.done) break;

                chunks.push(result.value);
                received += result.value.length;

                var now = Date.now();
                if (now - lastProgress > 250 || result.done) {
                    lastProgress = now;
                    api.download_progress(dlId, received, total);
                }
            }

            var blob = new Blob(chunks);

            var blobUrl = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = blobUrl;
            a.download = filename;
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

            setTimeout(function() { URL.revokeObjectURL(blobUrl); }, 1000);

            await api.download_complete(dlId, filename, received);

        } catch (err) {
            console.error('[GF] Download error:', err);
            if (dlId && api) {
                await api.download_error(dlId, String(err.message || err));
            }
        }
    }

    function _gfStartDownload(url) {
        _gfDownloadWithFetch(url).catch(function(e) {
            console.error('[GF] _gfDownloadWithFetch failed:', e);
        });
    }

    // Top tabs overlay in the main Gameyfin UI.
    (function _gfInstallTabs() {
        if (document.getElementById('gf-desktop-tabs')) return;
        var bar = document.createElement('div');
        bar.id = 'gf-desktop-tabs';
        bar.style.position = 'fixed';
        bar.style.top = '0';
        bar.style.left = '0';
        bar.style.right = '0';
        bar.style.zIndex = '2147483647';
        bar.style.height = '40px';
        bar.style.display = 'flex';
        bar.style.alignItems = 'center';
        bar.style.gap = '8px';
        bar.style.padding = '0 10px';
        bar.style.background = 'rgba(9, 9, 11, 0.88)';
        bar.style.backdropFilter = 'blur(10px)';
        bar.style.borderBottom = '1px solid rgba(63, 63, 70, 0.75)';
        bar.style.fontFamily = 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
        bar.style.userSelect = 'none';

        function mkBtn(label, onClick) {
            var b = document.createElement('button');
            b.type = 'button';
            b.textContent = label;
            b.style.cursor = 'pointer';
            b.style.border = '1px solid rgba(63, 63, 70, 0.9)';
            b.style.borderRadius = '8px';
            b.style.background = 'rgba(39, 39, 42, 0.9)';
            b.style.color = '#fafafa';
            b.style.padding = '5px 10px';
            b.style.fontSize = '12px';
            b.style.fontWeight = '600';
            b.addEventListener('click', function(ev) {
                ev.preventDefault();
                ev.stopPropagation();
                try { onClick(); } catch (_) {}
            }, true);
            return b;
        }

        bar.appendChild(mkBtn('Gameyfin', function() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.navigate_main_to_gameyfin) {
                window.pywebview.api.navigate_main_to_gameyfin();
            }
        }));
        bar.appendChild(mkBtn('Downloads', function() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.navigate_main_to_panel) {
                window.pywebview.api.navigate_main_to_panel('downloads');
            }
        }));
        bar.appendChild(mkBtn('Settings', function() {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.navigate_main_to_panel) {
                window.pywebview.api.navigate_main_to_panel('settings');
            }
        }));

        document.documentElement.appendChild(bar);
        var style = document.createElement('style');
        style.textContent = 'html, body { padding-top: 40px !important; }';
        document.documentElement.appendChild(style);
    })();

    // Intercept window.open (Gameyfin uses window.open('/download/...', '_top'))
    var _origOpen = window.open;
    window.open = function(url, target, features) {
        if (_gfIsDownloadUrl(url)) {
            _gfStartDownload(url);
            return null;
        }
        return _origOpen.call(window, url, target, features);
    };

    // Also intercept direct link clicks to /download/ paths
    document.addEventListener('click', function(e) {
        var link = e.target.closest('a[href]');
        if (!link) return;
        var href = link.getAttribute('href') || '';
        if (_gfIsDownloadUrl(href)) {
            e.preventDefault();
            e.stopPropagation();
            _gfStartDownload(href);
        }
    }, true);

    // Intercept programmatic navigation.
    try {
        var _origAssign = window.location.assign.bind(window.location);
        window.location.assign = function(url) {
            if (_gfIsDownloadUrl(url)) { _gfStartDownload(url); return; }
            return _origAssign(url);
        };
    } catch (_) {}

    try {
        var _origReplace = window.location.replace.bind(window.location);
        window.location.replace = function(url) {
            if (_gfIsDownloadUrl(url)) { _gfStartDownload(url); return; }
            return _origReplace(url);
        };
    } catch (_) {}

    // If Gameyfin navigates directly to /download/ (location.href = ...), catch it on load.
    try {
        if (_gfIsDownloadUrl(window.location.pathname || window.location.href)) {
            _gfStartDownload(window.location.href);
        }
    } catch (_) {}

    // Intercept form submits that point at /download/.
    document.addEventListener('submit', function(e) {
        try {
            var form = e.target;
            if (!form) return;
            var action = form.getAttribute('action') || '';
            if (_gfIsDownloadUrl(action)) {
                e.preventDefault();
                e.stopPropagation();
                _gfStartDownload(action);
            }
        } catch (_) {}
    }, true);

    // Hide horizontal overflow
    document.documentElement.style.overflowX = 'hidden';
    document.body.style.overflowX = 'hidden';
})();
"""


# When False, the main window is showing local setup HTML — do not inject Gameyfin download hooks.
_inject_download_hooks = False


def set_gameyfin_mode(active: bool):
    """True when the main window is (or will be) on the remote Gameyfin app."""
    global _inject_download_hooks
    _inject_download_hooks = bool(active)


def on_main_loaded():
    """Inject the download intercept script after each remote Gameyfin page load."""
    if main_window and _inject_download_hooks:
        main_window.evaluate_js(DOWNLOAD_INTERCEPT_JS)


def open_server_setup_page():
    """Tray / bridge: load the local server URL form in the main window."""
    set_gameyfin_mode(False)
    if main_window:
        p = resource_path(os.path.join("gameyfin_frontend", "panel", "setup.html"))
        su = f"file:///{p}" if sys.platform == "win32" else f"file://{p}"
        main_window.load_url(su)


def quit_app():
    """Clean shutdown from tray or other."""
    for w in webview.windows[:]:
        try:
            w.destroy()
        except Exception:
            pass


# ── Globals (set before webview.start) ────────────────────────────

main_window = None
panel_window = None


def main():
    global main_window, panel_window

    url_raw = settings_manager.get("GF_URL")
    gameyfin_url = normalize_gameyfin_url(url_raw) or url_raw or "http://localhost:8080"

    setup_path = resource_path(os.path.join("gameyfin_frontend", "panel", "setup.html"))
    setup_url = f"file:///{setup_path}" if sys.platform == "win32" else f"file://{setup_path}"

    configured = int(settings_manager.get("GF_SERVER_CONFIGURED", 0)) == 1
    if configured:
        set_gameyfin_mode(True)
        initial_main_url = gameyfin_url
    else:
        set_gameyfin_mode(False)
        initial_main_url = setup_url

    width = settings_manager.get("GF_WINDOW_WIDTH") or 1420
    height = settings_manager.get("GF_WINDOW_HEIGHT") or 940

    panel_html = resource_path(os.path.join("gameyfin_frontend", "panel", "index.html"))
    panel_url = f"file:///{panel_html}" if sys.platform == "win32" else f"file://{panel_html}"

    data_dir = settings_manager.settings_dir
    umu_db = UmuDatabase()
    download_engine = DownloadEngine(data_dir)

    bridge = GFBridge(None, None, download_engine, umu_db, on_gameyfin_navigation=set_gameyfin_mode)

    main_window = webview.create_window(
        "Gameyfin",
        url=initial_main_url,
        width=width,
        height=height,
        min_size=(800, 600),
        text_select=True,
        js_api=bridge,
    )
    bridge._main_window = main_window

    panel_window = webview.create_window(
        "Gameyfin - Panel",
        url=panel_url,
        width=700,
        height=600,
        min_size=(500, 400),
        hidden=True,
        js_api=bridge,
    )
    bridge._panel_window = panel_window

    main_window.events.loaded += on_main_loaded

    tray = GameyfinTray(main_window, panel_window, quit_app, on_change_server=open_server_setup_page)
    tray.start()

    # Run the pywebview event loop (blocks until all windows are closed)
    webview.start(
        private_mode=False,
        storage_path=data_dir,
    )


if __name__ == "__main__":
    main()
