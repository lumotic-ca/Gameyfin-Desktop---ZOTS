import json
import os
import threading
import time
import uuid
from typing import Optional, Callable

import requests

from .settings import settings_manager
from .utils import format_size


class DownloadEngine:
    """Manages file downloads using requests, persists history to JSON."""

    def __init__(self, data_dir: str, get_cookies_fn: Optional[Callable] = None):
        self.data_dir = data_dir
        self.json_path = os.path.join(data_dir, "downloads.json")
        self._get_cookies = get_cookies_fn
        self._active_downloads: dict[str, "_ActiveDownload"] = {}
        self.records: list[dict] = []
        self._lock = threading.Lock()
        self._load_history()

    def _load_history(self):
        try:
            if os.path.exists(self.json_path):
                with open(self.json_path, "r") as f:
                    self.records = json.load(f)
                for r in self.records:
                    if r.get("status") == "Downloading":
                        r["status"] = "Failed"
        except Exception as e:
            print(f"Error loading download history: {e}")
            self.records = []

    def _save_history(self):
        with self._lock:
            try:
                with open(self.json_path, "w") as f:
                    json.dump(self.records, f, indent=4)
            except Exception as e:
                print(f"Error saving download history: {e}")

    def start_download(self, url: str, save_path: str,
                       on_progress: Optional[Callable] = None,
                       on_complete: Optional[Callable] = None,
                       on_error: Optional[Callable] = None) -> str:
        """Start a file download. Returns a unique download ID."""
        dl_id = str(uuid.uuid4())[:8]

        record = {
            "id": dl_id,
            "url": url,
            "path": save_path,
            "status": "Downloading",
            "total_bytes": 0,
            "received_bytes": 0,
        }

        with self._lock:
            existing = [i for i, r in enumerate(self.records) if r.get("url") == url]
            for idx in reversed(existing):
                self.records.pop(idx)
            self.records.insert(0, record)

        self._save_history()

        active = _ActiveDownload(
            dl_id=dl_id,
            record=record,
            engine=self,
            get_cookies_fn=self._get_cookies,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )
        self._active_downloads[dl_id] = active
        active.start()
        return dl_id

    def cancel_download(self, dl_id: str):
        active = self._active_downloads.get(dl_id)
        if active:
            active.cancel()

    def remove_record(self, dl_id: str):
        with self._lock:
            self.records = [r for r in self.records if r.get("id") != dl_id]
        self._save_history()

    def get_records(self) -> list[dict]:
        return list(self.records)

    def get_active_download(self, dl_id: str):
        return self._active_downloads.get(dl_id)


class _ActiveDownload:
    def __init__(self, dl_id: str, record: dict, engine: DownloadEngine,
                 get_cookies_fn, on_progress, on_complete, on_error):
        self.dl_id = dl_id
        self.record = record
        self.engine = engine
        self._get_cookies = get_cookies_fn
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._on_error = on_error
        self._cancelled = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancelled = True
        self.record["status"] = "Cancelled"
        self.engine._save_history()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        if self._get_cookies:
            try:
                cookies = self._get_cookies()
                if cookies:
                    for c in cookies:
                        name = c.get("name", "")
                        value = c.get("value", "")
                        domain = c.get("domain", "")
                        if name and value:
                            session.cookies.set(name, value, domain=domain)
            except Exception as e:
                print(f"Warning: could not extract cookies: {e}")
        return session

    def _run(self):
        save_path = self.record["path"]
        url = self.record["url"]

        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            session = self._build_session()
            resp = session.get(url, stream=True, timeout=30, verify=False)
            resp.raise_for_status()

            total = int(resp.headers.get("Content-Length", 0))
            self.record["total_bytes"] = total

            received = 0
            last_progress_time = 0.0
            chunk_size = 1024 * 256

            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if self._cancelled:
                        return

                    f.write(chunk)
                    received += len(chunk)
                    self.record["received_bytes"] = received

                    now = time.time()
                    if now - last_progress_time > 0.3:
                        last_progress_time = now
                        if self._on_progress:
                            self._on_progress(self.dl_id, received, total)

            self.record["status"] = "Completed"
            self.record["total_bytes"] = received if total == 0 else total
            self.record["received_bytes"] = received
            self.engine._save_history()

            if self._on_complete:
                self._on_complete(self.dl_id)

        except Exception as e:
            if not self._cancelled:
                self.record["status"] = "Failed"
                self.engine._save_history()
                if self._on_error:
                    self._on_error(self.dl_id, str(e))
