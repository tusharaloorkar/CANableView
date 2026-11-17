"""MDI main window wiring bus, hub, trace, transmit, statistics, logging and replay."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QLabel, QLineEdit, QMainWindow, QMdiArea, QToolBar, QWidget,
)

from .bus import BusConfig, BusManager
from .hub import FrameHub
from .recorder import Recorder, Replayer
from .stats import StatisticsWindow
from .trace_window import TraceWindow
from .transmit import TransmitWindow

_DEFAULT_CHANNEL = {"slcan": "COM3", "gs_usb": "0", "virtual": "vcan0"}
_BITRATES = (125_000, 250_000, 500_000, 1_000_000)
_DATA_BITRATES = (1_000_000, 2_000_000, 4_000_000, 5_000_000)
_LOG_FILTER = "CAN logs (*.blf *.asc *.csv)"


def _rate_combo(rates: tuple[int, ...], default: int) -> QComboBox:
    c = QComboBox()
    for r in rates:
        c.addItem(f"{r // 1000} kbit/s", r)
    c.setCurrentIndex(rates.index(default))
    return c


class ConnectionBar(QToolBar):
    def __init__(self) -> None:
        super().__init__("Connection")
        self.interface = QComboBox()
        self.interface.addItems(list(_DEFAULT_CHANNEL))
        self.channel = QLineEdit()
        self.channel.setMaximumWidth(90)
        self.bitrate = _rate_combo(_BITRATES, 500_000)
        self.fd = QCheckBox("FD")
        self.data_bitrate = _rate_combo(_DATA_BITRATES, 2_000_000)
        self.data_bitrate.setEnabled(False)
        self.connect_action = QAction("Connect", self)
        self.log_action = QAction("Log", self)
        self.replay_action = QAction("Replay", self)
        self.clear_action = QAction("Clear", self)

        for w in (self.interface, self.channel, self.bitrate, self.fd, self.data_bitrate):
            self.addWidget(w)
        self.addAction(self.connect_action)
        self.addSeparator()
        for a in (self.log_action, self.replay_action, self.clear_action):
            self.addAction(a)

        self.fd.toggled.connect(self.data_bitrate.setEnabled)
        self.interface.currentTextChanged.connect(lambda n: self.channel.setText(_DEFAULT_CHANNEL[n]))
        self.set_interface("slcan")

    def set_interface(self, name: str) -> None:
        self.interface.setCurrentText(name)
        self.channel.setText(_DEFAULT_CHANNEL[name])

    def config(self) -> BusConfig:
        return BusConfig(
            self.interface.currentText(), self.channel.text().strip(),
            self.bitrate.currentData(), self.fd.isChecked(), self.data_bitrate.currentData(),
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CANableView")
        self.last_error = ""
        self.bus = BusManager(self)
        self.hub = FrameHub(self)
        self.recorder = Recorder(self.bus)
        self.replayer = Replayer(self.bus, self)
        self.bus.add_listener(self.hub.push)

        self.connection_bar = ConnectionBar()
        self.addToolBar(self.connection_bar)
        self.mdi = QMdiArea()
        self.setCentralWidget(self.mdi)
        self.trace = TraceWindow(self.hub)
        self.transmit = TransmitWindow(self.bus)
        self.stats = StatisticsWindow(self.hub, self.connection_bar.config())
        self._subs = {
            "Trace": self._add_sub(self.trace),
            "Transmit": self._add_sub(self.transmit),
            "Statistics": self._add_sub(self.stats),
        }
        menu = self.menuBar().addMenu("&Window")
        self._win_actions = {}
        for name, sub in self._subs.items():
            a = menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(True)
            a.toggled.connect(sub.setVisible)
            self._win_actions[name] = a
        menu.addSeparator()
        menu.addAction("Tile", self.mdi.tileSubWindows)
        menu.aboutToShow.connect(self._sync_window_menu)

        sb = self.statusBar()
        self.state_label, self.rx_label, self.tx_label = QLabel("Disconnected"), QLabel("Rx: 0"), QLabel("Tx: 0")
        self.log_label, self.fill_label = QLabel("Not logging"), QLabel()
        for lbl in (self.state_label, self.rx_label, self.tx_label, self.log_label, self.fill_label):
            sb.addPermanentWidget(lbl)
        self._rx = self._tx = 0
        self._update_fill()

        bar = self.connection_bar
        bar.connect_action.triggered.connect(self._toggle_connection)
        bar.log_action.triggered.connect(self._log_clicked)
        bar.replay_action.triggered.connect(self._replay_clicked)
        bar.clear_action.triggered.connect(self._clear)
        self.bus.error.connect(self._on_error)
        self.bus.disconnected.connect(self._on_bus_disconnected)
        self.hub.batch.connect(self._on_batch)  # after trace's own connection: model is already updated
        self.transmit.disarmed.connect(self.replayer.stop)  # manual disarm, disconnect and Stop all
        self.transmit.status.connect(self.statusBar().showMessage)
        self.replayer.finished.connect(self._on_replay_finished)  # bound method: queued onto the GUI thread
        self.hub.start(50)

        self.mdi.tileSubWindows()
        self._restore()

    def _add_sub(self, w: QWidget):
        sub = self.mdi.addSubWindow(w)
        sub.setWindowTitle(w.windowTitle())
        w.windowTitleChanged.connect(sub.setWindowTitle)
        sub.show()
        return sub

    def _sync_window_menu(self) -> None:
        for name, a in self._win_actions.items():
            a.setChecked(not self._subs[name].isHidden())

    # --- connection -------------------------------------------------------
    def _toggle_connection(self) -> None:
        if self.bus.is_open:
            self.disconnect_bus()
        else:
            self.connect_bus()

    def connect_bus(self) -> None:
        cfg = self.connection_bar.config()
        self.statusBar().clearMessage()
        self.bus.open(cfg)
        if not self.bus.is_open:
            return  # error already shown via bus.error
        self.last_error = ""
        self.stats.set_config(cfg)
        self.connection_bar.connect_action.setText("Disconnect")
        self.state_label.setText(f"Connected: {cfg.interface} {cfg.channel}")

    def disconnect_bus(self) -> None:
        self.transmit.stop_all()  # cyclic + replay + disarm, before the bus goes away
        self.bus.close()
        self._set_disconnected()

    def _set_disconnected(self) -> None:
        self.connection_bar.connect_action.setText("Connect")
        self.state_label.setText("Disconnected")

    def _on_bus_disconnected(self) -> None:
        self.replayer.stop()
        self.transmit.stop_all()
        self._set_disconnected()
        if self.last_error:
            self.statusBar().showMessage(self.last_error)  # stop paths may have overwritten it

    def _on_error(self, text: str) -> None:
        self.last_error = text
        self.statusBar().showMessage(text)

    # --- logging / replay ---------------------------------------------------
    def _log_clicked(self) -> None:
        if self.recorder.active:
            self.stop_logging()
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Log to file", "", _LOG_FILTER)
            if path:
                self.start_logging(Path(path))

    def start_logging(self, path: Path) -> None:
        try:
            self.recorder.start(path)
        except (ValueError, RuntimeError, OSError) as exc:
            self.statusBar().showMessage(f"Logging failed: {exc}")
            return
        self.log_label.setText(f"Logging: {Path(path).name}")

    def stop_logging(self) -> None:
        self.recorder.stop()
        self.log_label.setText("Not logging")

    def _replay_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Replay log", "", _LOG_FILTER)
        if path:
            self.start_replay(Path(path))

    def start_replay(self, path: Path) -> None:
        if not self.bus.is_open:
            self.statusBar().showMessage("Not connected")
        elif not self.transmit.armed:
            self.statusBar().showMessage("Arm transmit first")
        else:
            try:
                self.replayer.start(path)
            except Exception as exc:  # noqa: BLE001 - bad/unreadable file or already running
                self.statusBar().showMessage(f"Replay failed: {exc}")
                return
            self.statusBar().showMessage(f"Replaying {Path(path).name}")

    def _on_replay_finished(self) -> None:
        if not self.bus.is_open and self.last_error:
            self.statusBar().showMessage(self.last_error)  # queued from the worker: don't hide a reader failure
        else:
            self.statusBar().showMessage("Replay finished", 5000)

    # --- status -----------------------------------------------------------
    def _clear(self) -> None:
        self.trace.model.clear()
        self._update_fill()

    def _on_batch(self, msgs: list) -> None:
        rx = sum(1 for m in msgs if m.is_rx)
        self._rx += rx
        self._tx += len(msgs) - rx
        self.rx_label.setText(f"Rx: {self._rx}")
        self.tx_label.setText(f"Tx: {self._tx}")
        self._update_fill()

    def _update_fill(self) -> None:
        m = self.trace.model
        self.fill_label.setText(f"Buffer: {m.rowCount()} / {m._capacity}")

    # --- lifecycle --------------------------------------------------------
    def _restore(self) -> None:
        s = QSettings("CANableView", "CANableView")
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        opened = s.value("open_windows")
        if isinstance(opened, str):
            for name, sub in self._subs.items():
                sub.setVisible(name in opened.split(","))

    def closeEvent(self, e) -> None:
        for step in (self.transmit.stop_all, self.replayer.stop, self.recorder.stop, self.bus.close, self.hub.stop):
            try:
                step()
            except Exception:  # noqa: BLE001 - keep shutting down the rest
                pass
        s = QSettings("CANableView", "CANableView")
        s.setValue("geometry", self.saveGeometry())
        s.setValue("open_windows", ",".join(n for n, sub in self._subs.items() if not sub.isHidden()))
        super().closeEvent(e)
