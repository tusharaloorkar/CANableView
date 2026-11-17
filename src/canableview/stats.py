"""Bus-load statistics over a sliding window of frame timestamps, and the Statistics MDI child."""
from __future__ import annotations

import time
from collections import Counter, deque

import can
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from .bus import BusConfig
from .hub import FrameHub

# FD constants: nominal = arbitration (17 std / 36 ext incl. BRS) + 13 tail (CRC delim, ACK, EOF, IFS);
# data phase = ESI + DLC + stuff count (1+4+4) + CRC (17, or 21 above 16 bytes) + payload.
_FD_NOMINAL = (30, 49)  # (standard, extended)


def frame_bits(msg: can.Message) -> tuple[int, int]:
    """(bits at nominal rate, bits at data rate) for one frame."""
    n = len(msg.data)
    # shortcut: bit stuffing ignored (real load ~10-20% higher), upgrade if users compare against CANalyzer
    if not msg.is_fd:
        return (67 if msg.is_extended_id else 47) + 8 * n, 0
    nominal = _FD_NOMINAL[msg.is_extended_id]
    data = 9 + (21 if n > 16 else 17) + 8 * n
    return (nominal, data) if msg.bitrate_switch else (nominal + data, 0)


class BusStats:
    def __init__(self, bitrate: int, data_bitrate: int, window_s: float = 1.0) -> None:
        self._bitrate, self._data_bitrate, self._window = bitrate, data_bitrate, window_s
        self._frames: deque[tuple[float, int | None, float]] = deque()  # (timestamp, id or None, seconds on wire)
        self._ids: Counter[int] = Counter()
        self.error_frames = 0

    def add(self, msgs: list[can.Message], now: float) -> None:
        for m in msgs:
            if m.is_error_frame:
                self.error_frames += 1
                continue
            nom, dat = frame_bits(m)
            self._frames.append((m.timestamp, m.arbitration_id, nom / self._bitrate + dat / self._data_bitrate))
            self._ids[m.arbitration_id] += 1
        cutoff = now - self._window
        while self._frames and self._frames[0][0] < cutoff:
            _, aid, _ = self._frames.popleft()
            self._ids[aid] -= 1
            if not self._ids[aid]:
                del self._ids[aid]

    @property
    def load_percent(self) -> float:
        return 100 * sum(f[2] for f in self._frames) / self._window

    @property
    def fps(self) -> float:
        return len(self._frames) / self._window

    @property
    def per_id_fps(self) -> dict[int, float]:
        return {i: c / self._window for i, c in self._ids.items()}

    @property
    def unique_ids(self) -> int:
        return len(self._ids)


class StatisticsWindow(QWidget):
    def __init__(self, hub: FrameHub, bus_cfg: BusConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Statistics")
        self.cards: dict[str, QLabel] = {}
        grid = QGridLayout()
        for col, name in enumerate(("Bus load", "Frames/s", "Error frames", "Unique IDs")):
            grid.addWidget(QLabel(name), 0, col)
            self.cards[name] = QLabel("0")
            self.cards[name].setStyleSheet("font-size: 20pt; font-weight: bold")
            grid.addWidget(self.cards[name], 1, col)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["ID", "Frames/s"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(self.table)
        self._offset: float | None = None  # frame clock minus time.monotonic(), learned per batch
        self.set_config(bus_cfg)
        hub.batch.connect(self._on_batch)
        # the hub emits nothing when idle, so age the window out ourselves
        self._idle = QTimer(self)
        self._idle.timeout.connect(self._on_idle)
        self._idle.start(500)

    def set_config(self, cfg: BusConfig) -> None:
        """Bitrates change on reconnect: restart the window."""
        self._stats = BusStats(cfg.bitrate, cfg.data_bitrate)
        self._refresh()

    def _on_batch(self, msgs: list[can.Message]) -> None:
        if not msgs:
            return
        now = max(m.timestamp for m in msgs)
        self._offset = now - time.monotonic()
        self._stats.add(msgs, now=now)
        self._refresh()

    def _on_idle(self) -> None:
        if self._offset is None:
            return
        self._stats.add([], now=time.monotonic() + self._offset)
        self._refresh()

    def _refresh(self) -> None:
        s = self._stats
        self.cards["Bus load"].setText(f"{s.load_percent:.1f} %")
        self.cards["Frames/s"].setText(f"{s.fps:.0f}")
        self.cards["Error frames"].setText(str(s.error_frames))
        self.cards["Unique IDs"].setText(str(s.unique_ids))
        rows = sorted(s.per_id_fps.items())
        self.table.setRowCount(len(rows))
        for r, (aid, fps) in enumerate(rows):
            # ids above 0x7FF can only be extended
            text = f"0x{aid:08X}" if aid > 0x7FF else f"0x{aid:03X}"
            self.table.setItem(r, 0, QTableWidgetItem(text))
            self.table.setItem(r, 1, QTableWidgetItem(f"{fps:.1f}"))
