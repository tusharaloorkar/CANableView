"""Thread-safe frame queue that emits one batch per GUI tick."""
from __future__ import annotations

from collections import deque

import can
from PySide6.QtCore import QObject, QTimer, Signal


class FrameHub(QObject):
    batch = Signal(list)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # deque.append/popleft are atomic, so push() needs no lock across threads
        self._queue: deque[can.Message] = deque()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)

    def push(self, msg: can.Message) -> None:
        # Called from the python-can Notifier thread: must not touch Qt objects
        self._queue.append(msg)

    def start(self, interval_ms: int = 50) -> None:
        self._timer.start(interval_ms)

    def stop(self) -> None:
        self._timer.stop()

    def _flush(self) -> None:
        if not self._queue:
            return
        # only this (GUI) thread pops and producers only append, so len() bounds the drain
        self.batch.emit([self._queue.popleft() for _ in range(len(self._queue))])
