"""
Download record manager for Gameyfin Desktop.

JS handles the actual file download via fetch(). This module only manages
the download records (status, progress, history) persisted to downloads.json.
"""

import json
import os
import threading
import uuid


class DownloadEngine:
    """Manages download records (no HTTP logic — JS does the actual fetch)."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.json_path = os.path.join(data_dir, "downloads.json")
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
                self._save_history()
        except Exception as e:
            print(f"[download_engine] Error loading history: {e}")
            self.records = []

    def _save_history(self):
        with self._lock:
            try:
                os.makedirs(self.data_dir, exist_ok=True)
                with open(self.json_path, "w") as f:
                    json.dump(self.records, f, indent=2)
            except Exception as e:
                print(f"[download_engine] Error saving history: {e}")

    def register_download(self, url: str) -> str:
        """Create a new download record. Returns the download ID."""
        dl_id = str(uuid.uuid4())[:8]

        record = {
            "id": dl_id,
            "url": url,
            "path": "",
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
        print(f"[download_engine] Registered download {dl_id} for {url}")
        return dl_id

    def update_progress(self, dl_id: str, received: int, total: int):
        """Update progress for an active download."""
        for r in self.records:
            if r.get("id") == dl_id:
                r["received_bytes"] = received
                r["total_bytes"] = total
                break

    def mark_complete(self, dl_id: str, path: str, size: int):
        """Mark a download as completed."""
        for r in self.records:
            if r.get("id") == dl_id:
                r["status"] = "Completed"
                r["path"] = path
                r["total_bytes"] = size
                r["received_bytes"] = size
                break
        self._save_history()
        print(f"[download_engine] Download {dl_id} completed: {path}")

    def mark_failed(self, dl_id: str, error: str):
        """Mark a download as failed."""
        for r in self.records:
            if r.get("id") == dl_id:
                r["status"] = "Failed"
                r["error"] = error
                break
        self._save_history()
        print(f"[download_engine] Download {dl_id} failed: {error}")

    def cancel_download(self, dl_id: str):
        """Mark a download as cancelled."""
        for r in self.records:
            if r.get("id") == dl_id:
                r["status"] = "Cancelled"
                break
        self._save_history()

    def remove_record(self, dl_id: str):
        """Remove a download record from history."""
        with self._lock:
            self.records = [r for r in self.records if r.get("id") != dl_id]
        self._save_history()

    def get_records(self) -> list[dict]:
        """Return all download records."""
        return list(self.records)
