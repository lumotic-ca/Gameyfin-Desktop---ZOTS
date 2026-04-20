"""
Pure-Python dialog logic (no Qt).
These functions are called from the bridge / panel JS and return data dicts.
Shell commands for wine tools use subprocess directly.
"""

import configparser
import os
import subprocess
from os.path import relpath

from .settings import settings_manager


def run_winecfg(wine_prefix_path: str):
    """Runs winecfg in the given prefix using umu-run."""
    if not wine_prefix_path:
        return
    os.makedirs(wine_prefix_path, exist_ok=True)
    proton_path = settings_manager.get("PROTONPATH", "GE-Proton")
    cmd = f'PROTONPATH="{proton_path}" WINEPREFIX="{wine_prefix_path}" umu-run winecfg'
    subprocess.Popen(["/bin/sh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_winetricks(wine_prefix_path: str):
    """Runs winetricks in the given prefix using umu-run."""
    if not wine_prefix_path:
        return
    os.makedirs(wine_prefix_path, exist_ok=True)
    proton_path = settings_manager.get("PROTONPATH", "GE-Proton")
    cmd = f'PROTONPATH="{proton_path}" WINEPREFIX="{wine_prefix_path}" umu-run winetricks --gui'
    subprocess.Popen(["/bin/sh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def parse_desktop_name(file_path: str) -> str:
    """Reads a .desktop file and returns its Name entry."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        if not content.strip().startswith('[Desktop Entry]'):
            content = '[Desktop Entry]\n' + content
        cp = configparser.ConfigParser(strict=False)
        cp.optionxform = str
        cp.read_string(content)
        if 'Desktop Entry' in cp:
            return cp['Desktop Entry'].get('Name', os.path.basename(file_path))
    except Exception as e:
        print(f"Error parsing {file_path} for name: {e}")
    return os.path.basename(file_path)


def get_exe_list(target_dir: str) -> list[dict]:
    """Walk target_dir for .exe files and return list of {relative, full} paths."""
    results = []
    try:
        for root, _dirs, files in os.walk(target_dir):
            for f in files:
                if f.lower().endswith(".exe"):
                    full = os.path.join(root, f)
                    results.append({
                        "relative": relpath(full, target_dir),
                        "full": full,
                    })
    except Exception as e:
        print(f"Error searching for executables: {e}")
    return results


def build_install_env(config: dict, wine_prefix_path: str) -> tuple[str, str]:
    """
    Build the shell env prefix and umu command from an install config dict.
    Returns (env_prefix_str, umu_command_str).
    """
    proton_path = settings_manager.get("PROTONPATH", "GE-Proton")
    env_prefix = f'PROTONPATH="{proton_path}" WINEPREFIX="{wine_prefix_path}" '
    umu_command = "umu-run"

    for key, value in config.items():
        if key == "MANGOHUD" and value == "1":
            umu_command = f"mangohud {umu_command}"
            continue
        env_prefix += f'{key}="{value}" '

    return env_prefix, umu_command


def launch_linux_installer(launcher_path: str, wine_prefix_path: str, config: dict) -> int:
    """
    Launch a Windows exe via umu-run, block until complete, return the exit code.
    For non-blocking use, run on a thread.
    """
    env_prefix, umu_command = build_install_env(config, wine_prefix_path)
    cmd = f'{env_prefix} exec {umu_command} "{launcher_path}"'
    launcher_dir = os.path.dirname(launcher_path)
    print(f"Executing: /bin/sh -c \"{cmd}\"")
    proc = subprocess.Popen(["/bin/sh", "-c", cmd], cwd=launcher_dir)
    proc.wait()
    return proc.returncode


def launch_windows_installer(launcher_path: str) -> int:
    """Launch an exe on Windows, block until complete."""
    launcher_dir = os.path.dirname(launcher_path)
    print(f"Executing (Windows): {launcher_path}")
    proc = subprocess.Popen([launcher_path], cwd=launcher_dir)
    proc.wait()
    return proc.returncode
