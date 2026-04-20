import os
import time
import zipfile
import threading
from typing import Callable, Optional


class UnzipWorker:
    """Runs zip extraction on a background thread."""

    def __init__(self, zip_path: str, target_dir: str,
                 on_progress: Optional[Callable[[int], None]] = None,
                 on_current_file: Optional[Callable[[str], None]] = None,
                 on_finished: Optional[Callable[[], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self.zip_path = zip_path
        self.target_dir = target_dir
        self._on_progress = on_progress
        self._on_current_file = on_current_file
        self._on_finished = on_finished
        self._on_error = on_error
        self._is_running = True
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            with zipfile.ZipFile(self.zip_path, 'r') as zip_ref:
                file_list = zip_ref.infolist()
                total_files = len(file_list)

                if total_files == 0:
                    if self._on_finished:
                        self._on_finished()
                    return

                for i, member in enumerate(file_list):
                    if not self._is_running:
                        if self._on_error:
                            self._on_error("Extraction cancelled by user.")
                        return

                    zip_ref.extract(member, path=self.target_dir)

                    percentage = int(((i + 1) / total_files) * 100)
                    if self._on_progress:
                        self._on_progress(percentage)
                    if self._on_current_file:
                        self._on_current_file(f"Extracting: {member.filename}")

                if self._on_finished:
                    self._on_finished()

        except Exception as e:
            if self._on_error:
                self._on_error(str(e))

    def stop(self):
        self._is_running = False

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


class ProcessMonitorWorker:
    """Monitors a process by PID on a background thread."""

    def __init__(self, pid: int,
                 on_finished: Optional[Callable[[], None]] = None):
        self.pid = pid
        self._on_finished = on_finished
        self._running = True
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        if self.pid <= 0:
            print(f"ProcessMonitor: Invalid PID ({self.pid}), stopping.")
            return

        print(f"ProcessMonitor: Monitoring PID {self.pid}")

        while self._running:
            try:
                os.kill(self.pid, 0)
            except OSError:
                print(f"ProcessMonitor: PID {self.pid} finished.")
                self._running = False
                if self._on_finished:
                    self._on_finished()
                break
            else:
                if not self._running:
                    break
                time.sleep(1)

        print(f"ProcessMonitor: Stopping monitor for {self.pid}")

    def stop(self):
        self._running = False
