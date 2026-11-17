"""Trace MDI child: table view over TraceModel with ID filter and changed-byte highlight."""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView, QStyledItemDelegate, QTableView, QToolBar, QVBoxLayout, QWidget,
)

from .hub import FrameHub
from .trace_model import TraceModel

_DATA_COL = 6
_AMBER = QColor(255, 191, 0, 170)


def valid_changed(raw, nbytes: int) -> list[int]:
    """Changed-byte indices still inside the payload (it can shrink after a change)."""
    return [i for i in raw or [] if i < nbytes]


def parse_id_filter(text: str) -> list[tuple[int, int]] | None:
    """'' -> [] (accept all); '0x100', '0x100-0x3FF', comma lists. None on bad input."""
    ranges = []
    try:
        for tok in text.split(","):
            if not tok.strip():
                if text.strip():
                    return None
                continue
            lo, _, hi = tok.partition("-")
            lo = int(lo.strip(), 0)
            hi = int(hi.strip(), 0) if hi else lo
            if lo < 0 or hi < lo:
                return None
            ranges.append((lo, hi))
    except ValueError:
        return None
    return ranges


class IdFilterProxy(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self._ranges: list[tuple[int, int]] = []

    def set_ranges(self, ranges: list[tuple[int, int]]) -> None:
        self.beginFilterChange()
        self._ranges = ranges
        self.endFilterChange()

    def filterAcceptsRow(self, source_row: int, parent: QModelIndex) -> bool:
        if not self._ranges:
            return True
        i = self.sourceModel().message_at(source_row).arbitration_id
        return any(lo <= i <= hi for lo, hi in self._ranges)


class ByteHighlightDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        if index.column() == _DATA_COL:
            text = index.data(Qt.DisplayRole) or ""
            nbytes = (len(text) + 1) // 3  # "AA BB CC"
            fm = option.fontMetrics
            x0 = option.rect.x() + 3  # Qt's default text margin
            for i in valid_changed(index.data(TraceModel.CHANGED_ROLE), nbytes):
                x = x0 + fm.horizontalAdvance(text[: 3 * i])
                w = fm.horizontalAdvance(text[3 * i : 3 * i + 2])
                painter.fillRect(x, option.rect.y(), w, option.rect.height(), _AMBER)
        super().paint(painter, option, index)


class TraceWindow(QWidget):
    def __init__(self, hub: FrameHub) -> None:
        super().__init__()
        self.setWindowTitle("Trace")
        self.model = TraceModel()
        self.proxy = IdFilterProxy()
        self.proxy.setSourceModel(self.model)

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(ByteHighlightDelegate(self.view))
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(self.view.fontMetrics().height() + 4)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.horizontalHeader().setStretchLastSection(True)

        bar = QToolBar()
        self.mode_action = QAction("Fixed", self, checkable=True)
        self.mode_action.toggled.connect(self._set_fixed)
        self.clear_action = QAction("Clear", self)
        self.clear_action.triggered.connect(self.model.clear)
        bar.addAction(self.mode_action)
        bar.addAction(self.clear_action)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(bar)
        lay.addWidget(self.view)

        # fixed mode never emits dataChanged when a highlight expires, so repaint on a timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self.view.viewport().update)

        hub.batch.connect(self._on_batch)

    def set_id_filter(self, text: str) -> bool:
        ranges = parse_id_filter(text)
        if ranges is None:
            return False
        self.proxy.set_ranges(ranges)
        return True

    def _on_batch(self, msgs: list) -> None:
        sb = self.view.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 2
        self.model.append_batch(msgs)
        if at_bottom and self.model._mode == "scroll":
            self.view.scrollToBottom()

    def _set_fixed(self, fixed: bool) -> None:
        self.model.set_mode("fixed" if fixed else "scroll")
        self._sync_timer()

    def _sync_timer(self) -> None:
        if self.mode_action.isChecked() and self.isVisible():
            self.refresh_timer.start()
        else:
            self.refresh_timer.stop()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._sync_timer()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._sync_timer()
