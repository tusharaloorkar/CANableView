"""Table model for the Trace window: ring buffer (scroll) or one row per ID (fixed)."""
from __future__ import annotations

from typing import Literal

import can
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

_CHANGE_WINDOW = 1.0  # seconds a changed byte stays highlighted
_NEVER = float("-inf")


class TraceModel(QAbstractTableModel):
    COLUMNS = ["Time", "Δt", "ID", "Dir", "DLC", "Flags", "Data"]
    CHANGED_ROLE = Qt.UserRole + 1

    def __init__(self, capacity: int = 100_000) -> None:
        super().__init__()
        self._capacity = capacity
        self._mode: str = "scroll"
        self._reset()

    def _reset(self) -> None:
        # list, not deque: deque indexing is O(n) mid-queue and data() indexes constantly
        self._rows: list[can.Message] = []
        self._t0: float | None = None
        self._newest = 0.0
        # fixed mode only; parallel to self._rows (which is then a plain, never-trimmed list)
        self._key_row: dict[tuple, int] = {}
        self._prev_ts: list[float | None] = []
        self._changed_at: list[list[float]] = []

    def set_mode(self, mode: Literal["scroll", "fixed"]) -> None:
        self.beginResetModel()
        self._mode = mode
        self._reset()
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._reset()
        self.endResetModel()

    def message_at(self, row: int) -> can.Message:
        return self._rows[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        return None

    # -- ingestion ---------------------------------------------------------
    def append_batch(self, msgs: list[can.Message]) -> None:
        if not msgs:
            return
        if self._t0 is None:
            self._t0 = msgs[0].timestamp
        self._newest = max(self._newest, max(m.timestamp for m in msgs))
        if self._mode == "scroll":
            self._append_scroll(msgs)
        else:
            self._append_fixed(msgs)

    def _append_scroll(self, msgs: list[can.Message]) -> None:
        msgs = msgs[-self._capacity:]
        overflow = len(self._rows) + len(msgs) - self._capacity
        if overflow > 0:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            del self._rows[:overflow]
            self.endRemoveRows()
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(msgs) - 1)
        self._rows.extend(msgs)
        self.endInsertRows()

    @staticmethod
    def _key(m: can.Message) -> tuple:
        return (m.arbitration_id, m.is_extended_id, m.is_rx)

    def _append_fixed(self, msgs: list[can.Message]) -> None:
        old_count = len(self._rows)
        new_keys = {self._key(m) for m in msgs} - self._key_row.keys()
        if new_keys:
            self.beginInsertRows(QModelIndex(), old_count, old_count + len(new_keys) - 1)
        touched: set[int] = set()
        for m in msgs:
            k = self._key(m)
            row = self._key_row.get(k)
            if row is None:
                row = self._key_row[k] = len(self._rows)
                self._rows.append(m)
                self._prev_ts.append(None)
                self._changed_at.append([_NEVER] * len(m.data))
            else:
                old = self._rows[row]
                ch = self._changed_at[row]
                ch.extend([_NEVER] * (len(m.data) - len(ch)))
                for i, b in enumerate(m.data):
                    if i >= len(old.data) or old.data[i] != b:
                        ch[i] = m.timestamp
                self._prev_ts[row] = old.timestamp
                self._rows[row] = m
                touched.add(row)
        if new_keys:
            self.endInsertRows()
        touched = {r for r in touched if r < old_count}
        if touched:
            self.dataChanged.emit(
                self.index(min(touched), 0), self.index(max(touched), len(self.COLUMNS) - 1)
            )

    # -- display -----------------------------------------------------------
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if role == self.CHANGED_ROLE:
            if self._mode != "fixed" or index.column() != 6:
                return []
            return [
                i for i, t in enumerate(self._changed_at[row]) if self._newest - t <= _CHANGE_WINDOW
            ]
        if role != Qt.DisplayRole:
            return None
        m = self._rows[row]
        col = index.column()
        if col == 0:
            return f"{m.timestamp - self._t0:.4f}"
        if col == 1:
            if self._mode == "fixed":
                prev = self._prev_ts[row]
            else:
                prev = self._rows[row - 1].timestamp if row else None
            return f"{0.0 if prev is None else m.timestamp - prev:.4f}"
        if col == 2:
            return f"0x{m.arbitration_id:08X}" if m.is_extended_id else f"0x{m.arbitration_id:03X}"
        if col == 3:
            return "Rx" if m.is_rx else "Tx"
        if col == 4:
            return str(m.dlc)
        if col == 5:
            flags = (
                ("FD", m.is_fd), ("BRS", m.bitrate_switch), ("ESI", m.error_state_indicator),
                ("RTR", m.is_remote_frame), ("ERR", m.is_error_frame),
            )
            return " ".join(n for n, on in flags if on)
        if col == 6:
            return m.data.hex(" ").upper()
        return None
