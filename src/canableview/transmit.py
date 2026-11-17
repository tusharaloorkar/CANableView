"""Transmit MDI child: editable TX rows, explicit arm, one-shot and cyclic send, Stop all."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import can
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .bus import BusManager

log = logging.getLogger(__name__)
_FD_LENGTHS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64}
_COLS = ["ID", "Ext", "FD", "BRS", "Data", "Cycle (ms)"]
_ID, _EXT, _FD, _BRS, _DATA, _CYCLE = range(6)


def parse_hex(text: str, fd: bool) -> bytes:
    digits = "".join(text.split())
    if len(digits) % 2:
        raise ValueError("Data needs an even number of hex digits")
    try:
        data = bytes.fromhex(digits)
    except ValueError:
        raise ValueError("Data must be hex bytes") from None
    if fd:
        if len(data) not in _FD_LENGTHS:
            raise ValueError("FD data length must be 0-8, 12, 16, 20, 24, 32, 48 or 64 bytes")
    elif len(data) > 8:
        raise ValueError("Classic CAN data is at most 8 bytes")
    return data


@dataclass
class TxRow:
    arbitration_id: int
    extended: bool
    fd: bool
    brs: bool
    data: bytes
    period_ms: int | None


def _message(row: TxRow) -> can.Message:
    limit = 0x1FFFFFFF if row.extended else 0x7FF
    if not 0 <= row.arbitration_id <= limit:
        raise ValueError(f"ID out of range (max 0x{limit:X})")
    if row.brs and not row.fd:
        raise ValueError("BRS requires FD")
    parse_hex(row.data.hex(), row.fd)  # re-check length rules against the FD flag
    return can.Message(
        arbitration_id=row.arbitration_id, is_extended_id=row.extended,
        is_fd=row.fd, bitrate_switch=row.brs, data=row.data,
    )


class TransmitWindow(QWidget):
    status = Signal(str)
    stopped_all = Signal()

    def __init__(self, bus: BusManager) -> None:
        super().__init__()
        self._bus = bus
        self.rows: list[TxRow] = []
        self._tasks: dict[int, object] = {}
        self._armed = False
        self._loading = False

        bus.disconnected.connect(lambda: self.arm(False))
        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.itemChanged.connect(self._on_item_changed)

        self.arm_btn = QPushButton("Arm")
        self.arm_btn.setCheckable(True)
        self.arm_btn.toggled.connect(self.arm)
        self.stop_btn = QPushButton("Stop all")
        self.stop_btn.clicked.connect(self.stop_all)
        add_btn = QPushButton("Add row")
        add_btn.clicked.connect(lambda: self.add_row(TxRow(0, False, False, False, b"", None)))
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_current)
        cyc_btn = QPushButton("Start/Stop cyclic")
        cyc_btn.clicked.connect(self._toggle_cyclic)

        bar = QHBoxLayout()
        for b in (self.arm_btn, self.stop_btn, add_btn, send_btn, cyc_btn):
            bar.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.table)
        self._retitle()

    @property
    def armed(self) -> bool:
        return self._armed

    def _retitle(self) -> None:
        self.setWindowTitle("Transmit" + (" — armed" if self._armed else ""))
        self.arm_btn.setStyleSheet("color: red;" if self._armed else "")

    def arm(self, on: bool) -> None:
        self._armed = on  # disarm first so a failing stop() can never leave it armed
        self.arm_btn.blockSignals(True)
        self.arm_btn.setChecked(on)
        self.arm_btn.blockSignals(False)
        self._retitle()
        if not on:
            self._stop_tasks()

    def _stop_tasks(self) -> None:
        tasks, self._tasks = self._tasks, {}
        for t in tasks.values():
            try:
                t.stop()
            except Exception:  # noqa: BLE001 - keep stopping the rest
                log.exception("failed to stop cyclic task")

    def stop_all(self) -> None:
        try:
            self.arm(False)  # also stops cyclic tasks
        finally:
            self.stopped_all.emit()

    def _current(self) -> int | None:
        r = self.table.currentRow()
        return r if r >= 0 else None

    def _send_current(self) -> None:
        i = self._current()
        if i is not None:
            self.send_row(i)

    def _toggle_cyclic(self) -> None:
        i = self._current()
        if i is None:
            return
        if i in self._tasks:
            self._tasks.pop(i).stop()
        else:
            self.start_cyclic(i)

    def add_row(self, row: TxRow) -> None:
        self.rows.append(row)
        r = self.table.rowCount()
        self._loading = True
        self.table.insertRow(r)
        self.table.setItem(r, _ID, QTableWidgetItem(f"{row.arbitration_id:X}"))
        for col, val in ((_EXT, row.extended), (_FD, row.fd), (_BRS, row.brs)):
            it = QTableWidgetItem()
            it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it.setCheckState(Qt.Checked if val else Qt.Unchecked)
            self.table.setItem(r, col, it)
        self.table.setItem(r, _DATA, QTableWidgetItem(row.data.hex(" ").upper()))
        self.table.setItem(r, _CYCLE, QTableWidgetItem("" if row.period_ms is None else str(row.period_ms)))
        self._loading = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        r, c, row = item.row(), item.column(), self.rows[item.row()]
        old = self._tasks.pop(r, None)
        if old is not None:
            old.stop()  # edited row no longer matches what was running
        try:
            if c == _ID:
                try:
                    row.arbitration_id = int(item.text(), 16)
                except ValueError:
                    raise ValueError("ID must be hex") from None
            elif c == _EXT:
                row.extended = item.checkState() == Qt.Checked
            elif c == _FD:
                row.fd = item.checkState() == Qt.Checked
            elif c == _BRS:
                row.brs = item.checkState() == Qt.Checked
            elif c == _DATA:
                row.data = parse_hex(item.text(), row.fd)
            elif c == _CYCLE:
                t = item.text().strip()
                if t and (not t.isdigit() or int(t) <= 0):
                    raise ValueError("Cycle must be a positive number of ms")
                row.period_ms = int(t) if t else None
        except ValueError as exc:
            self.status.emit(str(exc))
            self._refresh(r, c)

    def _refresh(self, r: int, c: int) -> None:
        row = self.rows[r]
        text = {
            _ID: f"{row.arbitration_id:X}",
            _DATA: row.data.hex(" ").upper(),
            _CYCLE: "" if row.period_ms is None else str(row.period_ms),
        }.get(c)
        if text is not None:
            self._loading = True
            self.table.item(r, c).setText(text)
            self._loading = False

    def _ready(self, i: int) -> can.Message | None:
        if not self._armed:
            self.status.emit("Arm transmit first")
        elif not self._bus.is_open:
            self._tasks.clear()  # bus is gone, so are its tasks
            self.status.emit("Not connected")
        else:
            try:
                return _message(self.rows[i])
            except ValueError as exc:
                self.status.emit(str(exc))
        return None

    def send_row(self, i: int) -> bool:
        msg = self._ready(i)
        if msg is None:
            return False
        if not self._bus.send(msg):
            self.status.emit("Send failed")
            return False
        return True

    def start_cyclic(self, i: int) -> bool:
        msg = self._ready(i)
        if msg is None:
            return False
        period = self.rows[i].period_ms
        if not period:
            self.status.emit("Set a cycle time first")
            return False
        if i in self._tasks:
            return True
        task = self._bus.send_periodic(msg, period / 1000)
        if task is None:
            self.status.emit("Not connected")
            return False
        self._tasks[i] = task
        return True
