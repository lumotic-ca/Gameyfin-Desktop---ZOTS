"""
pystray-based system tray for Gameyfin Desktop.
Runs on a background thread so it does not block the pywebview main loop.
"""

import sys
import threading
from typing import Optional

import pystray
from PIL import Image

from .utils import get_app_icon_path
from .settings import settings_manager


class GameyfinTray:
    def __init__(self, main_window, panel_window, quit_callback):
        self._main_window = main_window
        self._panel_window = panel_window
        self._quit_callback = quit_callback
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        icon_path = get_app_icon_path(settings_manager.get("GF_ICON_PATH"))
        try:
            image = Image.open(icon_path)
        except Exception:
            image = Image.new("RGB", (64, 64), color=(30, 30, 30))

        menu = pystray.Menu(
            pystray.MenuItem("Gameyfin", self._show_main, default=True),
            pystray.MenuItem("Downloads / Settings", self._show_panel),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

        self._icon = pystray.Icon("gameyfin", image, "Gameyfin", menu)
        self._icon.run()

    def _show_main(self, _icon=None, _item=None):
        if self._main_window:
            self._main_window.show()

    def _show_panel(self, _icon=None, _item=None):
        if self._panel_window:
            self._panel_window.show()

    def _quit(self, _icon=None, _item=None):
        if self._icon:
            self._icon.stop()
        if self._quit_callback:
            self._quit_callback()

    def stop(self):
        if self._icon:
            self._icon.stop()
