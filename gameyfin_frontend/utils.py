import os
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse


def normalize_gameyfin_url(url_str: str) -> Optional[str]:
    """
    Return a usable absolute URL, or None if invalid.
    Adds http:// when no scheme is provided.
    """
    s = (url_str or "").strip()
    if not s:
        return None

    if "://" not in s:
        s = "http://" + s

    parsed = urlparse(s)
    if not parsed.scheme or not parsed.hostname:
        return None

    return urlunparse(parsed)


def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)

    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def get_app_icon_path(custom_path: str = None) -> str:
    """Returns the appropriate icon path."""
    if custom_path and os.path.exists(custom_path):
        return custom_path
    return resource_path(os.path.join("gameyfin_frontend", "icon.png"))


def get_xdg_user_dir(dir_name: str) -> Path:
    """
    Finds a special XDG user directory (like DESKTOP, DOCUMENTS)
    in a language-independent way on Linux.
    """
    key_to_find = f"XDG_{dir_name.upper()}_DIR"

    config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    config_file_path = Path(config_home) / "user-dirs.dirs"

    fallback_dir = Path.home() / dir_name.capitalize()

    if not config_file_path.is_file():
        return fallback_dir

    try:
        with open(config_file_path, "r") as f:
            for line in f:
                line = line.strip()

                if not line or line.startswith("#"):
                    continue

                if line.startswith(key_to_find):
                    try:
                        value = line.split("=", 1)[1]
                        value = value.strip('"')
                        path = os.path.expandvars(value)
                        return Path(path)
                    except Exception:
                        return fallback_dir

    except Exception as e:
        print(f"Error reading {config_file_path}: {e}")
        return fallback_dir

    return fallback_dir


def format_size(nbytes: int) -> str:
    if nbytes >= 1024 ** 3: return f"{nbytes / 1024 ** 3:.2f} GB"
    if nbytes >= 1024 ** 2: return f"{nbytes / 1024 ** 2:.2f} MB"
    if nbytes >= 1024: return f"{nbytes / 1024:.2f} KB"
    return f"{nbytes} B"


def open_path(path: str):
    """Open a file or folder with the system's default handler."""
    import subprocess
    import platform
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
