"""Frame logging (BLF/ASC/CSV) and log replay through BusManager.send."""
from __future__ import annotations

import threading
from pathlib import Path

import can
from PySide6.QtCore import QObject, Signal

from canableview.bus import BusManager

_EXTS = {".blf", ".asc", ".csv"}


class _LockedListener:
    """python-can writers have no locking; RX (reader thread) and TX echo (caller thread) both write."""

    def __init__(self, logger: can.io.generic.MessageWriter) -> None:
        self._logger = logger
        self._lock = threading.Lock()

    def __call__(self, msg: can.Message) -> None:
        with self._lock:
            self._logger(msg)

    def stop(self) -> None:
        with self._lock:
            self._logger.stop()


class Recorder:
    def __init__(self, bus: BusManager) -> None:
        self._bus = bus
        self._listener: _LockedListener | None = None
        self.path: Path | None = None

    @property
    def active(self) -> bool:
        return self._listener is not None

    def start(self, path: Path) -> None:
        if self.active:
            raise RuntimeError("recorder already active")
        path = Path(path)
        if path.suffix.lower() not in _EXTS:
            raise ValueError(f"unsupported log format {path.suffix!r}; use .blf, .asc or .csv")
        self._listener = _LockedListener(can.Logger(path))
        self.path = path
        self._bus.add_listener(self._listener)

    def stop(self) -> None:
        if self._listener is None:
            return
        self._bus.remove_listener(self._listener)  # before stop(): no write to a closed file
        self._listener.stop()
        self._listener = None


class Replayer(QObject):
    finished = Signal()

    def __init__(self, bus: BusManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, path: Path) -> None:
        if self.running:
            raise RuntimeError("replay already running")
        reader = can.LogReader(Path(path))  # raises here on missing/unreadable file; no thread started
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(reader,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2.0)

    def _run(self, reader) -> None:
        try:
            for msg in can.MessageSync(reader):
                if self._stop.is_set():
                    break
                if msg.is_error_frame:
                    continue  # logged bus errors are not frames; slcan would send them as data
                self._bus.send(msg)
        finally:
            reader.stop()
            self.finished.emit()
