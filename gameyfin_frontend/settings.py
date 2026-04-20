import os
import json
from platformdirs import user_data_dir


class SettingsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.settings_dir = user_data_dir("Gameyfin", "Gameyfin")
        os.makedirs(self.settings_dir, exist_ok=True)
        self.settings_file = os.path.join(self.settings_dir, "settings.json")

        default_download_dir = os.path.join(os.path.expanduser("~"), "Downloads")

        self.defaults = {
            "GF_URL": "http://localhost:8080",
            # 0 = show server setup in main window before loading Gameyfin; 1 = open GF_URL directly.
            "GF_SERVER_CONFIGURED": 0,
            "GF_WINDOW_WIDTH": 1420,
            "GF_WINDOW_HEIGHT": 940,
            "GF_START_MINIMIZED": 0,
            "GF_ICON_PATH": "",
            "PROTONPATH": "GE-Proton",
            "GF_UMU_API_URL": "https://umu.openwinecomponents.org/umu_api.php",
            "GF_UMU_DB_STORES": ["none", "gog", "amazon", "battlenet", "ea", "egs", "epic", "humble", "itchio", "origin", "steam", "uplay", "ubisoft"],
            "GF_THEME": "auto",
            "GF_DEFAULT_DOWNLOAD_DIR": default_download_dir,
            "GF_DEFAULT_UNZIP_DIR": "",
            "GF_PROMPT_UNZIP_DIR": 0
        }

        self.settings = self.defaults.copy()
        self.load()
        self._initialized = True

    def load(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    loaded_settings = json.load(f)
                    had_server_flag = "GF_SERVER_CONFIGURED" in loaded_settings
                    self.settings.update(loaded_settings)
                    # Older installs had no flag: if they already set a non-default URL, skip onboarding once.
                    if not had_server_flag:
                        url = (self.settings.get("GF_URL") or "").strip().rstrip("/").lower()
                        default_urls = {
                            "http://localhost:8080",
                            "http://127.0.0.1:8080",
                        }
                        if url and url not in default_urls:
                            self.settings["GF_SERVER_CONFIGURED"] = 1
                            self.save()
            except Exception as e:
                print(f"Error loading settings: {e}")

    def save(self):
        try:
            with open(self.settings_file, "w") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def get(self, key, fallback=None):
        env_val = os.getenv(key)
        if env_val is not None:
            if isinstance(self.defaults.get(key), int):
                try: return int(env_val)
                except: pass
            return env_val

        val = self.settings.get(key)
        if (val is None or val == "") and fallback:
            return fallback

        return val if val is not None else self.defaults.get(key)

    def set(self, key, value):
        self.settings[key] = value
        self.save()

    def get_all(self) -> dict:
        return {k: self.get(k) for k in self.defaults}

    def set_many(self, data: dict):
        for k, v in data.items():
            if k in self.defaults:
                self.settings[k] = v
        self.save()


settings_manager = SettingsManager()
