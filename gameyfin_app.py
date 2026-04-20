"""
Gameyfin Desktop — main entry point.
Uses pywebview (EdgeWebView2 on Windows, WebKitGTK on Linux) for a flicker-free,
OS-native web rendering experience.
"""

import os
import sys
import threading

import webview
from dotenv import load_dotenv

from gameyfin_frontend.settings import settings_manager
from gameyfin_frontend.utils import resource_path, normalize_gameyfin_url, get_app_icon_path
from gameyfin_frontend.umu_database import UmuDatabase
from gameyfin_frontend.download_engine import DownloadEngine
from gameyfin_frontend.bridge import GFBridge
from gameyfin_frontend.tray import GameyfinTray


load_dotenv()

# pywebview global settings
webview.settings["ALLOW_DOWNLOADS"] = False
webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False

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


def on_main_loaded():
    """Inject the download intercept script after each page load."""
    if main_window:
        main_window.evaluate_js(DOWNLOAD_INTERCEPT_JS)


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

    # Resolve the Gameyfin server URL
    url_raw = settings_manager.get("GF_URL")
    gameyfin_url = normalize_gameyfin_url(url_raw) or url_raw or "http://localhost:8080"

    # Window dimensions
    width = settings_manager.get("GF_WINDOW_WIDTH") or 1420
    height = settings_manager.get("GF_WINDOW_HEIGHT") or 940

    # Panel HTML path
    panel_html = resource_path(os.path.join("gameyfin_frontend", "panel", "index.html"))
    panel_url = f"file:///{panel_html}" if sys.platform == "win32" else f"file://{panel_html}"

    # Initialize backend components
    data_dir = settings_manager.settings_dir
    umu_db = UmuDatabase()

    download_engine = DownloadEngine(data_dir, get_cookies_fn=get_cookies_from_main)

    # Create main window (Gameyfin web UI)
    main_window = webview.create_window(
        "Gameyfin",
        url=gameyfin_url,
        width=width,
        height=height,
        min_size=(800, 600),
        text_select=True,
    )

    # Create panel window (Downloads / Prefixes / Settings)
    bridge = GFBridge(main_window, None, download_engine, umu_db)

    panel_window = webview.create_window(
        "Gameyfin - Panel",
        url=panel_url,
        width=700,
        height=600,
        min_size=(500, 400),
        hidden=True,
        js_api=bridge,
    )

    # Wire the bridge to both windows now that panel exists
    bridge._panel_window = panel_window
    bridge._main_window = main_window

    # Register the loaded event for download interception
    main_window.events.loaded += on_main_loaded

    # Start system tray on a background thread
    tray = GameyfinTray(main_window, panel_window, quit_app)
    tray.start()

    # Determine if we should start hidden
    start_minimized = int(settings_manager.get("GF_START_MINIMIZED", 0))

    # Run the pywebview event loop (blocks until all windows are closed)
    webview.start(
        private_mode=False,
        storage_path=data_dir,
    )


if __name__ == "__main__":
    main()
