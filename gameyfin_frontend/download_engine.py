import json
import os
import re
import threading
import time
import uuid
from typing import Optional, Callable

import requests

from .settings import settings_manager


_FILENAME_RE = re.compile(r"[^A-Za-z0-9._() -]+")


def _safe_filename(name: str, fallback: str = "download") -> str:
    n = (name or "").strip().strip('"').strip()
    if not n:
        return fallback
    n = n.replace("\\", "_").replace("/", "_").replace(":", "_")
    n = _FILENAME_RE.sub("_", n)
    n = n.strip(" ._")
    return n or fallback


def _filename_from_content_disposition(cd: str) -> str:
    """
    Best-effort parse of Content-Disposition for filename / filename*.
    """
    if not cd:
        return ""
    # filename*=UTF-8''name.ext
    m = re.search(r"filename\*\s*=\s*([^']*)''([^;]+)", cd, flags=re.IGNORECASE)
    if m:
        try:
            from urllib.parse import unquote
            return unquote(m.group(2))
        except Exception:
            return m.group(2)
    # filename*=UTF-8'name.ext   (some servers omit the second apostrophe)
    m = re.search(r"filename\*\s*=\s*([^']*)'([^;]+)", cd, flags=re.IGNORECASE)
    if m:
        try:
            from urllib.parse import unquote
            return unquote(m.group(2))
        except Exception:
            return m.group(2)
    m = re.search(r'filename\s*=\s*\"?([^\";]+)\"?', cd, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _looks_like_html(buf: bytes) -> bool:
    if not buf:
        return False
    s = buf.lstrip()[:256].lower()
    return s.startswith(b"<!doctype html") or s.startswith(b"<html") or b"<head" in s or b"<body" in s


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
                       on_error: Optional[Callable] = None,
                       cookies: Optional[list] = None) -> str:
        """Start a file download. Returns a unique download ID.

        ``cookies`` is an optional pre-captured list of cookie dicts
        (``{"name": ..., "value": ..., "domain": ...}``).  When supplied the
        download thread uses them directly, bypassing the lazy ``get_cookies_fn``
        call that would otherwise race with any window navigation.
        """
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
            prefetched_cookies=cookies,
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
                 get_cookies_fn, on_progress, on_complete, on_error,
                 prefetched_cookies: Optional[list] = None):
        self.dl_id = dl_id
        self.record = record
        self.engine = engine
        self._get_cookies = get_cookies_fn
        self._prefetched_cookies = prefetched_cookies
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
        # Prefer pre-captured cookies (grabbed before window navigation) to avoid
        # the race condition where get_cookies() runs after the window has moved to
        # a file:// URL and returns an empty list.
        cookie_list = self._prefetched_cookies
        if cookie_list is None and self._get_cookies:
            try:
                cookie_list = self._get_cookies()
            except Exception as e:
                print(f"Warning: could not extract cookies: {e}")
        for c in (cookie_list or []):
            name = c.get("name", "")
            value = c.get("value", "")
            domain = c.get("domain", "")
            if name and value:
                if domain:
                    session.cookies.set(name, value, domain=domain)
                else:
                    session.cookies.set(name, value)
        print(f"[download] session built with {len(session.cookies)} cookie(s)")
        return session

    def _run(self):
        save_path = self.record["path"]
        url = self.record["url"]

        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            session = self._build_session()
            resp = session.get(url, stream=True, timeout=60, verify=False, allow_redirects=True)
            resp.raise_for_status()

            # Determine final filename/path from response headers if available.
            cd = resp.headers.get("Content-Disposition", "") or resp.headers.get("content-disposition", "")
            ct = resp.headers.get("Content-Type", "") or resp.headers.get("content-type", "")
            final_url = getattr(resp, "url", url) or url
            self.record["final_url"] = final_url
            self.record["content_type"] = ct

            server_name = _filename_from_content_disposition(cd)
            server_name = _safe_filename(server_name, fallback="")

            base_dir = os.path.dirname(save_path)
            requested_name = os.path.basename(save_path)

            # If the requested filename is a numeric ID (no ext) or generic, prefer server filename.
            if server_name:
                final_path = os.path.join(base_dir, server_name)
            else:
                final_path = save_path
                # If it's numeric with no extension and content looks like an archive, add .zip.
                if re.fullmatch(r"\\d+", requested_name) and "." not in requested_name:
                    if "zip" in ct.lower() or "octet-stream" in ct.lower():
                        final_path = save_path + ".zip"

            self.record["path"] = final_path

            total = int(resp.headers.get("Content-Length", 0))
            self.record["total_bytes"] = total

            received = 0
            last_progress_time = 0.0
            chunk_size = 1024 * 256

            # Peek at first chunk to detect HTML/login/error pages.
            it = resp.iter_content(chunk_size=chunk_size)
            first = next(it, b"")
            if self._cancelled:
                return

            if ct.lower().startswith("text/html") or _looks_like_html(first):
                snippet = first[:1024].decode("utf-8", errors="replace")
                raise RuntimeError(
                    "Server returned HTML instead of a game file. "
                    "This usually means you're not authenticated (cookies missing) or the server redirected to a login/error page. "
                    f"(final_url={final_url}, content_type={ct}, first_bytes={len(first)})\n\n"
                    + snippet
                )

            with open(final_path, "wb") as f:
                if first:
                    f.write(first)
                    received += len(first)
                    self.record["received_bytes"] = received
                for chunk in it:
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
