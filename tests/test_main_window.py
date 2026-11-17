from unittest.mock import patch

import can
from PySide6.QtCore import QSettings

from canableview.bus import BusConfig, BusManager
from canableview.main_window import ConnectionBar, MainWindow
from canableview.recorder import Replayer


def _win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def _connected(qtbot):
    w = _win(qtbot)
    w.connection_bar.set_interface("virtual")
    w.connect_bus()
    return w


def test_virtual_end_to_end(qtbot):
    w = _connected(qtbot)
    other = BusManager()
    other.open(BusConfig("virtual", "vcan0"))
    other.send(can.Message(arbitration_id=0x321))
    qtbot.waitUntil(lambda: w.trace.model.rowCount() == 1, timeout=2000)
    other.close()


def test_close_while_logging_leaves_readable_file(qtbot, tmp_path):
    w = _connected(qtbot)
    p = tmp_path / "l.blf"
    w.recorder.start(p)
    w.bus.send(can.Message(arbitration_id=1))
    w.close()
    assert len(list(can.LogReader(p))) == 1


def test_connect_error_shown_in_status(qtbot):
    w = _win(qtbot)
    w.connection_bar.set_interface("slcan")
    w.connection_bar.channel.setText("COM_NOPE")
    w.connect_bus()
    assert w.last_error and not w.bus.is_open
    assert w.last_error in w.statusBar().currentMessage()


def test_connection_bar_defaults(qtbot):
    bar = ConnectionBar()
    qtbot.addWidget(bar)
    for name, ch in (("slcan", "COM3"), ("gs_usb", "0"), ("virtual", "vcan0")):
        bar.set_interface(name)
        assert bar.channel.text() == ch
    cfg = bar.config()
    assert (cfg.bitrate, cfg.fd, cfg.data_bitrate) == (500_000, False, 2_000_000)
    assert not bar.data_bitrate.isEnabled()
    bar.fd.setChecked(True)
    assert bar.data_bitrate.isEnabled() and bar.config().fd


def test_disconnect_stops_transmit_then_closes(qtbot):
    w = _connected(qtbot)
    w.transmit.arm(True)
    w.disconnect_bus()
    assert not w.transmit.armed and not w.bus.is_open
    assert w.connection_bar.connect_action.text() == "Connect"


def test_reader_failure_stops_replay_and_transmit(qtbot):
    with patch.object(Replayer, "stop") as stop:
        w = _connected(qtbot)
        w.transmit.arm(True)
        stop.reset_mock()
        w.bus.disconnected.emit()
        assert stop.called
    assert not w.transmit.armed


def test_replay_gating(qtbot, tmp_path):
    w = _win(qtbot)
    p = tmp_path / "r.blf"
    w.start_replay(p)
    assert "Not connected" in w.statusBar().currentMessage()
    w.connection_bar.set_interface("virtual")
    w.connect_bus()
    w.start_replay(p)
    assert "Arm transmit first" in w.statusBar().currentMessage()
    w.transmit.arm(True)
    w.start_replay(tmp_path / "missing.blf")  # error -> status, no exception
    assert w.statusBar().currentMessage()
    assert "Arm transmit first" not in w.statusBar().currentMessage()


def test_logging_errors_go_to_status(qtbot, tmp_path):
    w = _connected(qtbot)
    w.start_logging(tmp_path / "bad.xyz")
    assert not w.recorder.active and "unsupported" in w.statusBar().currentMessage()
    w.start_logging(tmp_path / "ok.csv")
    assert w.recorder.active and "ok.csv" in w.log_label.text()
    w.stop_logging()
    assert not w.recorder.active and w.log_label.text() == "Not logging"


def test_subwindow_title_mirrors_child(qtbot):
    w = _win(qtbot)
    sub = w.transmit.parentWidget()
    assert sub.windowTitle() == "Transmit"
    w.transmit.arm(True)
    assert sub.windowTitle() == "Transmit — armed"


def test_counts_per_batch(qtbot):
    w = _win(qtbot)
    rx, tx = can.Message(arbitration_id=1), can.Message(arbitration_id=2, is_rx=False)
    w.hub.batch.emit([rx, rx, tx])
    assert "2" in w.rx_label.text() and "1" in w.tx_label.text()


def test_close_is_idempotent_and_saves_settings(qtbot):
    w = _win(qtbot)
    w.close()
    w.closeEvent(__import__("PySide6.QtGui", fromlist=["QCloseEvent"]).QCloseEvent())
    s = QSettings("CANableView", "CANableView")
    assert s.value("geometry") is not None and s.value("open_windows") is not None
