from unittest.mock import Mock

import can
import pytest

from canableview.bus import BusConfig, BusManager
from canableview.recorder import Recorder, Replayer


@pytest.mark.parametrize("ext", [".blf", ".asc", ".csv"])
def test_record_roundtrip(tmp_path, ext):
    bus = BusManager()
    bus.open(BusConfig("virtual", f"r{ext}"))
    rec = Recorder(bus)
    p = tmp_path / f"x{ext}"
    rec.start(p)
    assert rec.active and rec.path == p
    for i in range(10):
        bus.send(can.Message(arbitration_id=i, data=b"\x01", is_extended_id=False))
    rec.stop()
    assert not rec.active
    assert len(list(can.LogReader(p))) == 10
    bus.close()


def test_bad_extension(tmp_path):
    with pytest.raises(ValueError):
        Recorder(BusManager()).start(tmp_path / "x.txt")


def test_stop_before_start_noop():
    Recorder(BusManager()).stop()


def test_start_twice_raises(tmp_path):
    rec = Recorder(BusManager())
    rec.start(tmp_path / "a.asc")
    with pytest.raises(RuntimeError):
        rec.start(tmp_path / "b.asc")
    rec.stop()


def _write_log(p, n, spacing):
    with can.ASCWriter(p) as wr:
        for i in range(n):
            wr.on_message_received(can.Message(arbitration_id=i, timestamp=i * spacing))


def test_replay_sends_all(tmp_path, qtbot):
    p = tmp_path / "in.asc"
    _write_log(p, 5, 0.001)
    bus = Mock()
    r = Replayer(bus)
    with qtbot.waitSignal(r.finished, timeout=3000):
        r.start(p)
    assert bus.send.call_count == 5


def test_replay_stop_midfile(tmp_path, qtbot):
    p = tmp_path / "slow.asc"
    _write_log(p, 40, 0.05)
    bus = Mock()
    r = Replayer(bus)
    count = []
    r.finished.connect(lambda: count.append(1))
    with qtbot.waitSignal(r.finished, timeout=3000):
        r.start(p)
        qtbot.wait(150)
        r.stop()
    qtbot.wait(100)
    assert count == [1]
    assert 0 < bus.send.call_count < 40


def test_replay_start_twice_raises(tmp_path, qtbot):
    p = tmp_path / "slow.asc"
    _write_log(p, 40, 0.05)
    r = Replayer(Mock())
    r.start(p)
    with pytest.raises(RuntimeError):
        r.start(p)
    with qtbot.waitSignal(r.finished, timeout=3000):
        r.stop()


def test_replay_missing_file_raises(tmp_path):
    r = Replayer(Mock())
    with pytest.raises(Exception):
        r.start(tmp_path / "nope.asc")
    with pytest.raises(Exception) as ei:
        r.start(tmp_path / "nope.asc")
    assert not isinstance(ei.value, RuntimeError)


def test_replay_skips_error_frames(tmp_path, qtbot):
    p = tmp_path / "err.asc"
    with can.ASCWriter(p) as wr:
        wr.on_message_received(can.Message(arbitration_id=1, timestamp=0.0))
        wr.on_message_received(can.Message(is_error_frame=True, timestamp=0.001))
        wr.on_message_received(can.Message(arbitration_id=2, timestamp=0.002))
    bus = Mock()
    r = Replayer(bus)
    with qtbot.waitSignal(r.finished, timeout=3000):
        r.start(p)
    assert [c.args[0].arbitration_id for c in bus.send.call_args_list] == [1, 2]
