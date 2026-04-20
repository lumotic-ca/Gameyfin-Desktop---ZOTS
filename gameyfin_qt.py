import sys
import os

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from gameyfin_frontend import GameyfinTray
from gameyfin_frontend import GameyfinWindow
from dotenv import load_dotenv

from gameyfin_frontend.umu_database import UmuDatabase
from gameyfin_frontend.utils import resource_path, get_app_icon_path

from gameyfin_frontend.settings import settings_manager



load_dotenv()

# Chromium flags for the embedded WebEngine renderer.
# --disable-web-security     : bypasses CORS for Authentik / SSO redirects.
# --disable-gpu-vsync        : prevents stutter caused by the WebEngine vsync
#                              cycle drifting out of sync with the OS compositor,
#                              which manifests as periodic flickering on Windows.
# --enable-smooth-scrolling  : smoother scroll frame pacing inside the webview.
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-web-security "
    "--disable-gpu-vsync "
    "--enable-smooth-scrolling"
)

if __name__ == "__main__":

    app = QApplication(sys.argv)

    # Store default palette and font for "auto" theme fallback
    app.default_palette = app.palette()
    app.default_font = app.font()
    app.default_style_name = app.style().objectName()

    # Apply theme
    theme = settings_manager.get("GF_THEME")
    if theme and theme != "auto":
        from qt_material import apply_stylesheet
        apply_stylesheet(app, theme=theme)

    umu_database = UmuDatabase()

    app.setApplicationName("Gameyfin")
    app.setOrganizationName("Gameyfin")
    app.setDesktopFileName("org.gameyfin.Gameyfin-Desktop")

    # Set window icon
    custom_icon_path = settings_manager.get("GF_ICON_PATH")
    internal_icon_path = get_app_icon_path(custom_icon_path, theme=theme)

    is_light_variant = "icon_light.png" in internal_icon_path
    has_custom_path = custom_icon_path is not None and custom_icon_path != ""

    if has_custom_path or is_light_variant:
        app_icon = QIcon(internal_icon_path)
    else:
        app_icon = QIcon.fromTheme("org.gameyfin.Gameyfin-Desktop")
        if app_icon.isNull():
            app_icon = QIcon(internal_icon_path)
            
    app.setWindowIcon(app_icon)

    window = GameyfinWindow(umu_database)

    tray_app = GameyfinTray(app, window)

    if int(settings_manager.get("GF_START_MINIMIZED", 0)) == 0:

        window.show()

    sys.exit(app.exec())
