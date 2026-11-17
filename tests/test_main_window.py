from unittest.mock import patch

import can
from PySide6.QtCore import QSettings
from PySide6.QtGui import QCloseEvent

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
    rates = [bar.data_bitrate.itemData(i) for i in range(bar.data_bitrate.count())]
    assert rates == [2_000_000, 5_000_000]  # python-can slcan set_bitrate only accepts these
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
    w.closeEvent(QCloseEvent())
    s = QSettings("CANableView", "CANableView")
    assert s.value("geometry") is not None and s.value("open_windows") is not None


def test_reader_failure_error_survives_stop_status(qtbot):
    w = _connected(qtbot)
    w.bus.error.emit("reader died")
    with patch.object(w.transmit, "stop_all", side_effect=lambda: w.transmit.status.emit("other")):
        w.bus.disconnected.emit()
    assert w.last_error in w.statusBar().currentMessage()


def test_reader_failure_during_replay_keeps_error(qtbot, tmp_path):
    w = _connected(qtbot)
    p = tmp_path / "r.blf"
    with can.Logger(p) as lg:
        for i in range(10):
            lg(can.Message(arbitration_id=i, timestamp=i * 0.05))
    w.transmit.arm(True)
    w.start_replay(p)
    with qtbot.waitSignal(w.replayer.finished, timeout=3000):
        w.bus.error.emit("reader died")
        w.bus.close()  # a real reader failure closes the bus before emitting disconnected
        w.bus.disconnected.emit()
    qtbot.wait(50)
    assert w.last_error in w.statusBar().currentMessage()


def test_reconnect_clears_last_error(qtbot):
    w = _win(qtbot)
    w.bus.error.emit("old")
    w.connection_bar.set_interface("virtual")
    w.connect_bus()
    assert w.bus.is_open and w.last_error == ""


def _slow_log(path, n=1000, spacing=0.01):
    with can.Logger(path) as lg:
        for i in range(n):
            lg(can.Message(arbitration_id=0x100 + i % 8, timestamp=i * spacing))
    return path


def test_manual_disarm_stops_replay(qtbot, tmp_path):
    w = _connected(qtbot)
    other = BusManager(); got = []
    other.add_listener(got.append); other.open(BusConfig("virtual", "vcan0"))
    w.transmit.arm(True)
    w.start_replay(_slow_log(tmp_path / "r.blf"))
    qtbot.waitUntil(lambda: len(got) > 0, timeout=2000)
    with qtbot.waitSignal(w.replayer.finished, timeout=500):  # file runs 10 s
        w.transmit.arm_btn.click()  # Arm off
    assert not w.transmit.armed
    qtbot.wait(50)
    n = len(got)
    qtbot.wait(200)
    assert len(got) == n
    other.close()


def test_closing_transmit_subwindow_hides_it(qtbot):
    import shiboken6
    from canableview.transmit import TxRow
    w = _connected(qtbot)
    other = BusManager(); got = []
    other.add_listener(got.append); other.open(BusConfig("virtual", "vcan0"))
    w.transmit.add_row(TxRow(0x123, False, False, False, b"\x01", 10))
    w.transmit.arm(True)
    assert w.transmit.start_cyclic(0)
    w._subs["Transmit"].close()
    qtbot.wait(50)  # deferred delete would run here
    assert shiboken6.isValid(w.transmit) and shiboken6.isValid(w._subs["Transmit"])
    w.disconnect_bus()
    qtbot.wait(50)
    n = len(got)
    qtbot.wait(100)
    assert n > 0 and len(got) == n
    w._sync_window_menu()
    a = w._win_actions["Transmit"]
    assert not a.isChecked()
    a.trigger()
    assert not w._subs["Transmit"].isHidden()
    other.close()


def test_hiding_transmit_window_disarms_and_stops_cyclic(qtbot):
    from canableview.transmit import TxRow
    w = _connected(qtbot)
    w.show(); qtbot.waitExposed(w)
    other = BusManager(); got = []
    other.add_listener(got.append); other.open(BusConfig("virtual", "vcan0"))
    w.transmit.add_row(TxRow(0x123, False, False, False, b"\x01", 10))
    w.transmit.arm(True)
    assert w.transmit.start_cyclic(0)
    w._subs["Transmit"].close()
    assert not w.transmit.armed
    qtbot.wait(50)
    n = len(got)
    qtbot.wait(100)
    assert len(got) == n  # nothing sent once hidden
    other.close()


def test_reconnect_while_connected_runs_safety_teardown(qtbot):
    from canableview.transmit import TxRow
    w = _connected(qtbot)
    w.transmit.add_row(TxRow(0x123, False, False, False, b"\x01", 10))
    w.transmit.arm(True)
    assert w.transmit.start_cyclic(0)
    task = w.transmit._tasks[0]
    with patch.object(task, "stop", wraps=task.stop) as stop:
        w.connect_bus()
    assert w.bus.is_open and not w.transmit.armed
    assert stop.called and not w.transmit._tasks


def test_replay_action_shows_running_and_stops(qtbot, tmp_path):
    w = _connected(qtbot)
    a = w.connection_bar.replay_action
    w.transmit.arm(True)
    w.start_replay(_slow_log(tmp_path / "r.blf"))
    assert a.isChecked() and a.text() == "Stop replay"
    with qtbot.waitSignal(w.replayer.finished, timeout=500):
        a.trigger()
    qtbot.wait(20)
    assert not a.isChecked() and a.text() == "Replay"
