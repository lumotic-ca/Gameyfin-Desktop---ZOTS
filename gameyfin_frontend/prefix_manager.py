"""
Pure-Python prefix management logic (no Qt).
Called from the bridge to serve data to the HTML panel.
"""

import configparser
import glob
import json
import os
import re
import shlex
import shutil
import subprocess

from .settings import settings_manager
from .utils import get_xdg_user_dir


PREFIXES_DIR = os.path.join(os.path.expanduser("~"), ".config", "gameyfin", "prefixes")
SHORTCUTS_BASE_DIR = os.path.join(os.path.expanduser("~"), ".config", "gameyfin", "shortcut_scripts")


def list_prefixes() -> list[dict]:
    """Return a list of prefix dicts with name, path, scripts."""
    os.makedirs(PREFIXES_DIR, exist_ok=True)
    results = []
    try:
        items = sorted(os.listdir(PREFIXES_DIR))
        for item in items:
            prefix_path = os.path.join(PREFIXES_DIR, item)
            if not os.path.isdir(prefix_path):
                continue
            game_name = item.removesuffix("_pfx")
            scripts_dir = os.path.join(SHORTCUTS_BASE_DIR, game_name)
            scripts = []
            if os.path.isdir(scripts_dir):
                for s in sorted(glob.glob(os.path.join(scripts_dir, "*.sh"))):
                    scripts.append({"name": os.path.basename(s), "path": s})
            results.append({
                "name": item,
                "game_name": game_name,
                "path": prefix_path,
                "scripts_dir": scripts_dir,
                "scripts": scripts,
            })
    except Exception as e:
        print(f"Error reading prefixes: {e}")
    return results


def launch_script(script_path: str):
    """Launch a .sh script in the background."""
    subprocess.Popen(
        [script_path],
        cwd=os.path.dirname(script_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def get_prefix_config(prefix_name: str) -> dict:
    """Load config.json or extract config from .sh for a prefix."""
    game_name = prefix_name.removesuffix("_pfx")
    scripts_dir = os.path.join(SHORTCUTS_BASE_DIR, game_name)
    config_path = os.path.join(scripts_dir, "config.json")

    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config for {game_name}: {e}")

    if os.path.exists(scripts_dir):
        sh_files = glob.glob(os.path.join(scripts_dir, "*.sh"))
        if sh_files:
            return _extract_config_from_sh(sh_files[0])

    return {}


def save_prefix_config(prefix_name: str, config: dict):
    """Save config.json and update all .sh scripts for a prefix."""
    game_name = prefix_name.removesuffix("_pfx")
    scripts_dir = os.path.join(SHORTCUTS_BASE_DIR, game_name)
    prefix_path = os.path.join(PREFIXES_DIR, prefix_name)

    os.makedirs(scripts_dir, exist_ok=True)
    config_path = os.path.join(scripts_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)

    _update_scripts(scripts_dir, prefix_path, config)


def delete_prefix(prefix_name: str) -> bool:
    """Delete a prefix directory and its shortcut scripts. Returns True on success."""
    prefix_path = os.path.join(PREFIXES_DIR, prefix_name)
    if not os.path.isdir(prefix_path):
        return False
    try:
        shutil.rmtree(prefix_path)
        game_name = prefix_name.removesuffix("_pfx")
        scripts_dir = os.path.join(SHORTCUTS_BASE_DIR, game_name)
        if os.path.exists(scripts_dir):
            shutil.rmtree(scripts_dir)
        return True
    except Exception as e:
        print(f"Failed to delete prefix: {e}")
        return False


def get_shortcut_desktop_files(prefix_name: str) -> list[dict]:
    """Get .desktop files from the proton_shortcuts dir of a prefix."""
    prefix_path = os.path.join(PREFIXES_DIR, prefix_name)
    shortcuts_dir = os.path.join(prefix_path, "drive_c", "proton_shortcuts")
    if not os.path.isdir(shortcuts_dir):
        return []

    results = []
    from .dialogs import parse_desktop_name
    for fp in sorted(glob.glob(os.path.join(shortcuts_dir, "*.desktop"))):
        name = parse_desktop_name(fp)
        bn = os.path.basename(fp)

        home_dir = os.path.expanduser("~")
        desktop_dir = str(get_xdg_user_dir("DESKTOP"))
        apps_dir = os.path.join(home_dir, ".local", "share", "applications")

        results.append({
            "path": fp,
            "basename": bn,
            "name": name,
            "on_desktop": os.path.exists(os.path.join(desktop_dir, bn)),
            "on_apps_menu": os.path.exists(os.path.join(apps_dir, bn)),
        })
    return results


def apply_shortcuts(prefix_name: str, desktop_selected: list[str], apps_selected: list[str]):
    """
    Create / remove system shortcuts.
    desktop_selected / apps_selected are lists of .desktop file basenames.
    """
    prefix_path = os.path.join(PREFIXES_DIR, prefix_name)
    shortcuts_dir = os.path.join(prefix_path, "drive_c", "proton_shortcuts")
    if not os.path.isdir(shortcuts_dir):
        return

    game_name = prefix_name.removesuffix("_pfx")
    scripts_dir = os.path.join(SHORTCUTS_BASE_DIR, game_name)
    all_desktop_files = glob.glob(os.path.join(shortcuts_dir, "*.desktop"))

    config_path = os.path.join(scripts_dir, "config.json")
    install_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                install_config = json.load(f)
        except Exception:
            pass

    _create_helper_scripts(all_desktop_files, prefix_path, scripts_dir, install_config)

    home_dir = os.path.expanduser("~")
    desktop_dir = str(get_xdg_user_dir("DESKTOP"))
    apps_dir = os.path.join(home_dir, ".local", "share", "applications")

    selected_desktop_paths = [fp for fp in all_desktop_files if os.path.basename(fp) in desktop_selected]
    selected_apps_paths = [fp for fp in all_desktop_files if os.path.basename(fp) in apps_selected]

    _manage_system_shortcuts(all_desktop_files, selected_desktop_paths, desktop_dir, scripts_dir)
    _manage_system_shortcuts(all_desktop_files, selected_apps_paths, apps_dir, scripts_dir)


def _extract_config_from_sh(script_path: str) -> dict:
    config = {}
    try:
        with open(script_path, "r") as f:
            content = f.read()
        for line in reversed(content.splitlines()):
            if "umu-run" in line:
                env_part = line.split("umu-run")[0]
                if "mangohud" in env_part.lower():
                    config["MANGOHUD"] = "1"
                    env_part = env_part.replace("mangohud", "").strip()
                for key, value in re.findall(r'(\w+)="(.*?)"', env_part):
                    if key not in ("PROTONPATH", "WINEPREFIX"):
                        config[key] = value
                break
    except Exception as e:
        print(f"Error extracting config from {script_path}: {e}")
    return config


def _update_scripts(scripts_dir: str, prefix_path: str, config: dict):
    if not os.path.exists(scripts_dir):
        return
    sh_files = glob.glob(os.path.join(scripts_dir, "*.sh"))
    proton_path = settings_manager.get("PROTONPATH", "GE-Proton")
    env_part = f'PROTONPATH="{proton_path}" WINEPREFIX="{prefix_path}" '
    umu_command = "umu-run"
    for key, value in config.items():
        if key == "MANGOHUD" and value == "1":
            umu_command = f"mangohud {umu_command}"
            continue
        env_part += f'{key}="{value}" '

    for sp in sh_files:
        try:
            with open(sp, "r") as f:
                content = f.read()
            for line in reversed(content.splitlines()):
                if "umu-run" in line:
                    parts = line.split("umu-run")
                    if len(parts) > 1:
                        exe_args = parts[1].strip()
                        new_content = f"#!/bin/sh\n\n# Auto-generated by Gameyfin\n{env_part}{umu_command} {exe_args}\n"
                        with open(sp, "w") as f:
                            f.write(new_content)
                        os.chmod(sp, 0o755)
                    break
        except Exception as e:
            print(f"Failed to update script {sp}: {e}")


def _create_helper_scripts(all_desktop_files, prefix_path, scripts_dir, install_config):
    os.makedirs(scripts_dir, exist_ok=True)
    proton_path = settings_manager.get("PROTONPATH", "GE-Proton")

    for original_path in all_desktop_files:
        try:
            with open(original_path, "r") as f:
                content = f.read()
            if not content.strip().startswith("[Desktop Entry]"):
                content = "[Desktop Entry]\n" + content
            cp = configparser.ConfigParser(strict=False)
            cp.optionxform = str
            cp.read_string(content)
            if "Desktop Entry" not in cp:
                continue
            entry = cp["Desktop Entry"]
            working_dir = entry.get("Path")
            exe_name = entry.get("StartupWMClass") or (entry.get("Name", "game") + ".exe")
            if not working_dir:
                continue
            exe_path = os.path.join(working_dir, exe_name)

            env_prefix = f'PROTONPATH="{proton_path}" WINEPREFIX="{prefix_path}" '
            umu_command = "umu-run"
            for key, value in install_config.items():
                if key == "MANGOHUD" and value == "1":
                    umu_command = f"mangohud {umu_command}"
                    continue
                env_prefix += f'{key}="{value}" '

            script_name = os.path.splitext(os.path.basename(original_path))[0] + ".sh"
            script_path = os.path.join(scripts_dir, script_name)
            with open(script_path, "w") as f:
                f.write(f"#!/bin/sh\n\n# Auto-generated by Gameyfin\n{env_prefix}{umu_command} \"{exe_path}\"\n")
            os.chmod(script_path, 0o755)
        except Exception as e:
            print(f"Failed to create helper script for {original_path}: {e}")


def _manage_system_shortcuts(all_desktop_files, selected_list, target_dir, scripts_dir):
    os.makedirs(target_dir, exist_ok=True)
    to_remove = [f for f in all_desktop_files if f not in selected_list]
    for fp in to_remove:
        target_path = os.path.join(target_dir, os.path.basename(fp))
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except Exception as e:
                print(f"Failed to remove shortcut {target_path}: {e}")

    for original_path in selected_list:
        try:
            with open(original_path, "r") as f:
                content = f.read()
            if not content.strip().startswith("[Desktop Entry]"):
                content = "[Desktop Entry]\n" + content
            cp = configparser.ConfigParser(strict=False)
            cp.optionxform = str
            cp.read_string(content)
            if "Desktop Entry" not in cp:
                continue

            entry = cp["Desktop Entry"]
            icon_name = entry.get("Icon")
            if icon_name:
                icons_base = os.path.join(os.path.dirname(original_path), "icons")
                for size in ("256x256", "128x128", "64x64", "48x48", "32x32"):
                    for suffix in (f"{icon_name}.png", icon_name):
                        p = os.path.join(icons_base, size, "apps", suffix)
                        if os.path.exists(p):
                            cp.set("Desktop Entry", "Icon", p)
                            break
                    else:
                        continue
                    break

            script_name = os.path.splitext(os.path.basename(original_path))[0] + ".sh"
            script_path = os.path.join(scripts_dir, script_name)

            if os.path.exists("/.flatpak-info"):
                inner_cmd = shlex.quote(script_path)
                for char in ("\\", '"', "$", "`"):
                    inner_cmd = inner_cmd.replace(char, f"\\{char}")
                cp.set("Desktop Entry", "Exec",
                        f'flatpak run --command=sh org.gameyfin.Gameyfin-Desktop -c "{inner_cmd}"')
            else:
                cp.set("Desktop Entry", "Exec", f'"{script_path}"')

            cp.set("Desktop Entry", "Type", "Application")
            cp.set("Desktop Entry", "Categories", "Application;Game;")

            dest = os.path.join(target_dir, os.path.basename(original_path))
            with open(dest, "w") as f:
                cp.write(f)
            os.chmod(dest, 0o755)
        except Exception as e:
            print(f"Failed to create shortcut {original_path}: {e}")
