"""
Download record manager with filesystem watcher for Gameyfin Desktop.

The browser handles the actual HTTP download (via hidden iframe with full
auth). This module manages download records and polls the download folder
to detect new files and track progress.
"""

import json
import os
import threading
import time
import uuid
from typing import Callable, Optional


class DownloadEngine:
    """Manages download records and watches the filesystem for progress."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.json_path = os.path.join(data_dir, "downloads.json")
        self.records: list[dict] = []
        self._lock = threading.Lock()
        self._watchers: dict[str, threading.Thread] = {}
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
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.json_path, "w") as f:
                json.dump(self.records, f, indent=2)
        except Exception as e:
            print(f"[download_engine] Error saving history: {e}")

    def register_download(
        self,
        url: str,
        download_dir: str,
        on_progress: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ) -> str:
        """Create a new download record and start watching the download folder."""
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

        watcher = threading.Thread(
            target=self._watch_folder,
            args=(dl_id, download_dir, on_progress, on_complete, on_error),
            daemon=True,
        )
        self._watchers[dl_id] = watcher
        watcher.start()

        return dl_id

    def _watch_folder(
        self,
        dl_id: str,
        download_dir: str,
        on_progress: Optional[Callable],
        on_complete: Optional[Callable],
        on_error: Optional[Callable],
    ):
        """Poll the download folder for new/growing files matching this download."""
        os.makedirs(download_dir, exist_ok=True)
        start_time = time.time()

        existing_files: dict[str, float] = {}
        try:
            for f in os.listdir(download_dir):
                fp = os.path.join(download_dir, f)
                if os.path.isfile(fp):
                    existing_files[f] = os.path.getmtime(fp)
        except OSError:
            pass

        matched_file: Optional[str] = None
        last_size = 0
        stable_count = 0
        timeout = 30 * 60

        while time.time() - start_time < timeout:
            rec = self._find_record(dl_id)
            if not rec or rec.get("status") not in ("Downloading",):
                break

            time.sleep(2)

            if matched_file:
                fp = os.path.join(download_dir, matched_file)
                if not os.path.exists(fp):
                    matched_file = None
                    last_size = 0
                    stable_count = 0
                    continue
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    continue

                rec["received_bytes"] = size
                rec["path"] = fp
                if on_progress:
                    on_progress(dl_id, size, rec.get("total_bytes", 0))

                if size == last_size and size > 0:
                    stable_count += 1
                else:
                    stable_count = 0
                last_size = size

                # File hasn't grown for ~6 seconds and isn't a tiny stub
                if stable_count >= 3 and size > 1024:
                    self._complete_download(dl_id, fp, size)
                    if on_complete:
                        on_complete(dl_id)
                    self._watchers.pop(dl_id, None)
                    return
                continue

            # Look for new or modified files
            try:
                current_files = os.listdir(download_dir)
            except OSError:
                continue

            for fname in current_files:
                # Skip browser partial download markers
                if fname.endswith(".crdownload") or fname.endswith(".tmp") or fname.endswith(".partial"):
                    continue

                fp = os.path.join(download_dir, fname)
                if not os.path.isfile(fp):
                    continue

                try:
                    mtime = os.path.getmtime(fp)
                except OSError:
                    continue

                if fname not in existing_files or mtime > existing_files.get(fname, 0) + 1:
                    if mtime >= start_time - 5:
                        matched_file = fname
                        last_size = 0
                        stable_count = 0
                        print(f"[download_engine] Watcher {dl_id}: detected file {fname}")
                        break

            # Also check for partial download files (Edge uses .crdownload)
            if not matched_file:
                for fname in current_files:
                    if not (fname.endswith(".crdownload") or fname.endswith(".partial")):
                        continue
                    fp = os.path.join(download_dir, fname)
                    try:
                        mtime = os.path.getmtime(fp)
                    except OSError:
                        continue
                    if mtime >= start_time - 5:
                        try:
                            size = os.path.getsize(fp)
                        except OSError:
                            size = 0
                        rec["received_bytes"] = size
                        if on_progress:
                            on_progress(dl_id, size, 0)
                        break

        rec = self._find_record(dl_id)
        if rec and rec.get("status") == "Downloading":
            if matched_file:
                fp = os.path.join(download_dir, matched_file)
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    size = 0
                if size > 1024:
                    self._complete_download(dl_id, fp, size)
                    if on_complete:
                        on_complete(dl_id)
                    self._watchers.pop(dl_id, None)
                    return

            rec["status"] = "Check Downloads folder"
            self._save_history()
            if on_error:
                on_error(dl_id, "Timed out watching for file. Check your Downloads folder.")
        self._watchers.pop(dl_id, None)

    def _complete_download(self, dl_id: str, path: str, size: int):
        """Mark a download as completed."""
        for r in self.records:
            if r.get("id") == dl_id:
                r["status"] = "Completed"
                r["path"] = path
                r["total_bytes"] = size
                r["received_bytes"] = size
                break
        self._save_history()
        print(f"[download_engine] Download {dl_id} completed: {path} ({size} bytes)")

    def _find_record(self, dl_id: str) -> Optional[dict]:
        for r in self.records:
            if r.get("id") == dl_id:
                return r
        return None

    def mark_failed(self, dl_id: str, error: str):
        """Mark a download as failed."""
        for r in self.records:
            if r.get("id") == dl_id:
                r["status"] = "Failed"
                r["error"] = error
                break
        self._save_history()

    def cancel_download(self, dl_id: str):
        """Mark a download as cancelled (watcher thread will exit on next poll)."""
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
