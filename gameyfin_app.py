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
webview.settings["ALLOW_DOWNLOADS"] = False
webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
# Homelab HTTPS with private CAs / self-signed certs
webview.settings["IGNORE_SSL_ERRORS"] = True

# JS injected into the Gameyfin web UI after each page load to intercept
# download navigations and route them through the Python bridge.
DOWNLOAD_INTERCEPT_JS = """
(function() {
    if (window._gfInterceptInstalled) return;
    window._gfInterceptInstalled = true;

    // Intercept window.open (Gameyfin uses window.open('/download/...', '_top'))
    var _origOpen = window.open;
    window.open = function(url, target, features) {
        if (url && url.indexOf('/download/') !== -1) {
            // Extract a reasonable filename from the URL
            var parts = url.split('/');
            var fname = parts[parts.length - 1] || 'download';
            if (fname.indexOf('?') !== -1) fname = fname.split('?')[0];

            // Build absolute URL from relative
            var absUrl = url;
            if (url.startsWith('/')) {
                absUrl = window.location.origin + url;
            }

            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.start_download(absUrl, fname);
            }
            return null;
        }
        return _origOpen.call(window, url, target, features);
    };

    // Also intercept direct link clicks to /download/ paths
    document.addEventListener('click', function(e) {
        var link = e.target.closest('a[href]');
        if (!link) return;
        var href = link.getAttribute('href') || '';
        if (href.indexOf('/download/') !== -1) {
            e.preventDefault();
            e.stopPropagation();
            var parts = href.split('/');
            var fname = parts[parts.length - 1] || 'download';
            if (fname.indexOf('?') !== -1) fname = fname.split('?')[0];

            var absUrl = href;
            if (href.startsWith('/')) {
                absUrl = window.location.origin + href;
            }

            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.start_download(absUrl, fname);
            }
        }
    }, true);

    // Hide horizontal overflow (matches previous QWebEngineScript behaviour)
    document.documentElement.style.overflowX = 'hidden';
    document.body.style.overflowX = 'hidden';
})();
"""


def get_cookies_from_main():
    """Cookie extractor passed to the download engine."""
    try:
        if main_window:
            cookies = main_window.get_cookies()
            result = []
            if cookies:
                for c in cookies:
                    result.append({
                        "name": getattr(c, "name", "") or c.get("name", ""),
                        "value": getattr(c, "value", "") or c.get("value", ""),
                        "domain": getattr(c, "domain", "") or c.get("domain", ""),
                    })
            return result
    except Exception as e:
        print(f"Cookie extraction error: {e}")
    return []


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
    download_engine = DownloadEngine(data_dir, get_cookies_fn=get_cookies_from_main)

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
