"""
Python-JS bridge (pywebview js_api) for the Gameyfin panel window.
All public methods are callable from JS via window.pywebview.api.<method>().
"""

import json
import os
import sys

import webview

from .settings import settings_manager
from .download_engine import DownloadEngine
from .workers import UnzipWorker
from .umu_database import UmuDatabase
from . import prefix_manager
from . import dialogs
from .utils import normalize_gameyfin_url, open_path, resource_path


class GFBridge:
    """Exposed to JS as window.pywebview.api."""

    def __init__(
        self,
        main_window,
        panel_window,
        download_engine: DownloadEngine,
        umu_database: UmuDatabase,
        on_gameyfin_navigation=None,
    ):
        self._main_window = main_window
        self._panel_window = panel_window
        self._download_engine = download_engine
        self._umu_database = umu_database
        self._on_gameyfin_navigation = on_gameyfin_navigation
        self._unzip_workers: dict[str, UnzipWorker] = {}

    # ── Platform ──────────────────────────────────────────────────────

    def get_platform(self) -> str:
        return sys.platform

    # ── Main window navigation (tabs) ─────────────────────────────────

    def navigate_main_to_gameyfin(self) -> str:
        """Load the configured Gameyfin URL in the main window."""
        url_raw = settings_manager.get("GF_URL") or ""
        normalized = normalize_gameyfin_url(url_raw) or url_raw
        if not normalized:
            return json.dumps({"ok": False, "error": "Gameyfin URL is not configured."})

        if self._on_gameyfin_navigation:
            self._on_gameyfin_navigation(True)
        if self._main_window:
            self._main_window.load_url(normalized)
            self._main_window.show()
        return json.dumps({"ok": True})

    def navigate_main_to_panel(self, tab: str = "downloads") -> str:
        """Load the local panel UI in the main window, optionally selecting a tab via hash."""
        tab_norm = (tab or "").strip().lower() or "downloads"
        if tab_norm not in ("downloads", "settings", "prefixes"):
            tab_norm = "downloads"

        path = resource_path(os.path.join("gameyfin_frontend", "panel", "index.html"))
        base = f"file:///{path}" if sys.platform == "win32" else f"file://{path}"
        url = f"{base}#{tab_norm}"

        if self._on_gameyfin_navigation:
            self._on_gameyfin_navigation(False)
        if self._main_window:
            self._main_window.load_url(url)
            self._main_window.show()
        return json.dumps({"ok": True})

    # ── Settings ──────────────────────────────────────────────────────

    def get_settings(self) -> str:
        return json.dumps(settings_manager.get_all())

    def save_settings(self, data_json: str) -> str:
        try:
            data = json.loads(data_json)
            url = data.get("GF_URL")
            if url:
                normalized = normalize_gameyfin_url(url)
                if not normalized:
                    return json.dumps({"ok": False, "error": "Invalid URL"})
                data["GF_URL"] = normalized
                data["GF_SERVER_CONFIGURED"] = 1
            settings_manager.set_many(data)
            if self._main_window:
                new_url = settings_manager.get("GF_URL")
                if self._on_gameyfin_navigation and new_url:
                    self._on_gameyfin_navigation(True)
                self._main_window.load_url(new_url)
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def complete_server_setup(self, url: str) -> str:
        """Validate URL, save, mark onboarding done, load Gameyfin in the main window."""
        normalized = normalize_gameyfin_url((url or "").strip())
        if not normalized:
            return json.dumps({
                "ok": False,
                "error": "Enter a valid URL with a host, e.g. https://gameyfin.home or http://192.168.1.10:8080",
            })
        settings_manager.set("GF_URL", normalized)
        settings_manager.set("GF_SERVER_CONFIGURED", 1)
        if self._on_gameyfin_navigation:
            self._on_gameyfin_navigation(True)
        if self._main_window:
            self._main_window.load_url(normalized)
        return json.dumps({"ok": True, "url": normalized})

    def show_server_setup(self) -> str:
        """Open the local setup page in the main window (change server / fix connection)."""
        path = resource_path(os.path.join("gameyfin_frontend", "panel", "setup.html"))
        setup_url = f"file:///{path}" if sys.platform == "win32" else f"file://{path}"
        if self._on_gameyfin_navigation:
            self._on_gameyfin_navigation(False)
        if self._main_window:
            self._main_window.load_url(setup_url)
        return json.dumps({"ok": True})

    # ── Downloads ─────────────────────────────────────────────────────
    # JS handles the actual HTTP fetch (with browser auth), these methods
    # just manage download records and UI notifications.

    def get_downloads(self) -> str:
        records = self._download_engine.get_records()
        return json.dumps(records)

    def register_download(self, url: str) -> str:
        """Called by JS before starting a fetch(). Creates a download record."""
        try:
            dl_id = self._download_engine.register_download(url)
            return json.dumps({"ok": True, "id": dl_id})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def download_progress(self, dl_id: str, received: int, total: int) -> str:
        """Called by JS periodically during fetch() streaming."""
        self._download_engine.update_progress(dl_id, received, total)
        pct = int((received / total) * 100) if total > 0 else 0
        if self._main_window:
            self._main_window.evaluate_js(
                f'if(window._onDownloadProgress) window._onDownloadProgress("{dl_id}",{received},{total},{pct})'
            )
        return json.dumps({"ok": True})

    def download_complete(self, dl_id: str, filename: str, size: int) -> str:
        """Called by JS after blob download is triggered."""
        download_dir = settings_manager.get("GF_DEFAULT_DOWNLOAD_DIR") or os.path.expanduser("~/Downloads")
        final_path = os.path.join(download_dir, filename)
        self._download_engine.mark_complete(dl_id, final_path, size)
        if self._main_window:
            self._main_window.evaluate_js(
                f'if(window._onDownloadComplete) window._onDownloadComplete("{dl_id}")'
            )
        return json.dumps({"ok": True})

    def download_error(self, dl_id: str, error: str) -> str:
        """Called by JS when fetch() fails."""
        self._download_engine.mark_failed(dl_id, error)
        if self._main_window:
            safe_msg = error.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
            self._main_window.evaluate_js(
                f'if(window._onDownloadError) window._onDownloadError("{dl_id}","{safe_msg}")'
            )
        return json.dumps({"ok": True})

    def cancel_download(self, dl_id: str):
        self._download_engine.cancel_download(dl_id)

    def remove_download(self, dl_id: str):
        self._download_engine.remove_record(dl_id)

    def remove_zip(self, path: str) -> str:
        try:
            if os.path.exists(path):
                os.remove(path)
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def open_file(self, path: str):
        open_path(path)

    def open_folder(self, path: str):
        open_path(os.path.dirname(path))

    # ── Unzip / Install ───────────────────────────────────────────────

    def unzip_file(self, zip_path: str, target_dir: str = "") -> str:
        """Start an extraction. Returns immediately, progress via JS callbacks."""
        if not target_dir:
            default_unzip_dir = settings_manager.get("GF_DEFAULT_UNZIP_DIR")
            download_dir = settings_manager.get("GF_DEFAULT_DOWNLOAD_DIR")
            base = default_unzip_dir or download_dir or os.path.expanduser("~/Downloads")
            basename = os.path.splitext(os.path.basename(zip_path))[0]
            target_dir = os.path.join(base, basename)

        os.makedirs(target_dir, exist_ok=True)
        unzip_id = os.path.basename(zip_path)

        def on_progress(pct):
            if self._panel_window:
                self._panel_window.evaluate_js(
                    f'if(window._onUnzipProgress) window._onUnzipProgress("{unzip_id}",{pct})'
                )

        def on_finished():
            if self._panel_window:
                self._panel_window.evaluate_js(
                    f'if(window._onUnzipFinished) window._onUnzipFinished("{unzip_id}")'
                )
            self._unzip_workers.pop(unzip_id, None)

        def on_error(msg):
            if self._panel_window:
                safe = msg.replace("\\", "\\\\").replace('"', '\\"')
                self._panel_window.evaluate_js(
                    f'if(window._onUnzipError) window._onUnzipError("{unzip_id}","{safe}")'
                )
            self._unzip_workers.pop(unzip_id, None)

        worker = UnzipWorker(zip_path, target_dir, on_progress, None, on_finished, on_error)
        self._unzip_workers[unzip_id] = worker
        worker.start()
        return json.dumps({"ok": True, "target_dir": target_dir})

    def get_exe_list(self, target_dir: str) -> str:
        return json.dumps(dialogs.get_exe_list(target_dir))

    def run_installer(self, launcher_path: str, wine_prefix: str = "", config_json: str = "{}") -> str:
        """Run an installer (blocking). Call from JS in a non-blocking manner."""
        config = json.loads(config_json)
        if sys.platform == "win32":
            code = dialogs.launch_windows_installer(launcher_path)
        else:
            if not wine_prefix:
                folder = os.path.basename(os.path.dirname(launcher_path))
                pfx = f"{folder.lower()}_pfx"
                wine_prefix = os.path.join(os.path.expanduser("~"), ".config", "gameyfin", "prefixes", pfx)
            code = dialogs.launch_linux_installer(launcher_path, wine_prefix, config)
        return json.dumps({"ok": True, "exit_code": code})

    # ── Wine tools (Linux) ────────────────────────────────────────────

    def run_winecfg(self, prefix_path: str):
        dialogs.run_winecfg(prefix_path)

    def run_winetricks(self, prefix_path: str):
        dialogs.run_winetricks(prefix_path)

    # ── Prefixes (Linux) ──────────────────────────────────────────────

    def get_prefixes(self) -> str:
        return json.dumps(prefix_manager.list_prefixes())

    def get_prefix_config(self, prefix_name: str) -> str:
        return json.dumps(prefix_manager.get_prefix_config(prefix_name))

    def save_prefix_config(self, prefix_name: str, config_json: str) -> str:
        try:
            config = json.loads(config_json)
            prefix_manager.save_prefix_config(prefix_name, config)
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def delete_prefix(self, prefix_name: str) -> str:
        ok = prefix_manager.delete_prefix(prefix_name)
        return json.dumps({"ok": ok})

    def launch_script(self, script_path: str):
        prefix_manager.launch_script(script_path)

    def get_shortcut_files(self, prefix_name: str) -> str:
        return json.dumps(prefix_manager.get_shortcut_desktop_files(prefix_name))

    def apply_shortcuts(self, prefix_name: str, desktop_json: str, apps_json: str) -> str:
        try:
            desktop = json.loads(desktop_json)
            apps = json.loads(apps_json)
            prefix_manager.apply_shortcuts(prefix_name, desktop, apps)
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    # ── UMU (Linux) ───────────────────────────────────────────────────

    def search_umu(self, query: str) -> str:
        results = self._umu_database.search_by_partial_title(query)
        return json.dumps(results)

    def get_umu_stores(self) -> str:
        return json.dumps(settings_manager.get("GF_UMU_DB_STORES"))

    # ── File dialogs ──────────────────────────────────────────────────

    def pick_directory(self, title: str = "Select Directory") -> str:
        result = self._panel_window.create_file_dialog(
            webview.FOLDER_DIALOG, directory="", allow_multiple=False
        )
        if result and len(result) > 0:
            return result[0]
        return ""

    def pick_file(self, title: str = "Select File", file_types: str = "") -> str:
        ft = tuple(file_types.split(";")) if file_types else ()
        result = self._panel_window.create_file_dialog(
            webview.OPEN_DIALOG, directory="", allow_multiple=False, file_types=ft
        )
        if result and len(result) > 0:
            return result[0]
        return ""

    # ── Window control ────────────────────────────────────────────────

    def show_main(self):
        if self._main_window:
            self._main_window.show()

    def show_panel(self):
        if self._panel_window:
            self._panel_window.show()
