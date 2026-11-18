import can
import pytest

from canableview.bus import BusConfig
from canableview.hub import FrameHub
from canableview.stats import BusStats, StatisticsWindow, frame_bits


def test_classic_bits():
    assert frame_bits(can.Message(arbitration_id=1, data=bytes(8), is_extended_id=False)) == (111, 0)
    assert frame_bits(can.Message(arbitration_id=1, data=bytes(8), is_extended_id=True)) == (131, 0)


def test_fd_bits_pinned():
    # std FD, 8 bytes: 30 nominal; data phase 1+4+4+17+64 = 90
    m = can.Message(arbitration_id=1, data=bytes(8), is_fd=True, bitrate_switch=True, is_extended_id=False)
    assert frame_bits(m) == (30, 90)
    # 20 bytes -> 21-bit CRC
    m = can.Message(arbitration_id=1, data=bytes(20), is_fd=True, bitrate_switch=True, is_extended_id=True)
    assert frame_bits(m) == (49, 1 + 4 + 4 + 21 + 160)
    # no BRS: everything at nominal
    m = can.Message(arbitration_id=1, data=bytes(8), is_fd=True, is_extended_id=False)
    assert frame_bits(m) == (120, 0)


def test_load_500k():
    s = BusStats(500_000, 2_000_000)
    s.add([can.Message(arbitration_id=1, data=bytes(8), is_extended_id=False, timestamp=i / 1000) for i in range(1000)], now=1.0)
    assert s.load_percent == pytest.approx(22.2, abs=0.1)
    assert s.fps == pytest.approx(1000, abs=1)


def test_window_slides():
    s = BusStats(500_000, 2_000_000)
    s.add([can.Message(arbitration_id=1, timestamp=0.0)], now=0.0)
    s.add([can.Message(arbitration_id=2, timestamp=5.0)], now=5.0)
    assert s.fps == 1 and s.unique_ids == 1 and s.per_id_fps == {2: 1.0}


def test_error_frames_counted():
    s = BusStats(500_000, 2_000_000)
    s.add([can.Message(is_error_frame=True)], now=0.0)
    assert s.error_frames == 1
    assert s.unique_ids == 0 and s.per_id_fps == {} and s.fps == 0


def test_tx_echo_counts():
    s = BusStats(500_000, 2_000_000)
    s.add([can.Message(arbitration_id=1, is_rx=False, timestamp=1.0)], now=1.0)
    assert s.fps == 1 and s.load_percent > 0


def test_window_batch_updates_cards_and_table(qtbot):
    hub = FrameHub(); w = StatisticsWindow(hub, BusConfig("virtual", "x")); qtbot.addWidget(w)
    hub.batch.emit([can.Message(arbitration_id=0x123, data=bytes(8), timestamp=1.0),
                    can.Message(arbitration_id=0x1ABCDEF, is_extended_id=True, timestamp=1.0),
                    can.Message(is_error_frame=True, timestamp=1.0)])
    assert w.cards["Unique IDs"].text() == "2"
    assert w.cards["Error frames"].text() == "1"
    assert w.table.rowCount() == 2
    assert {w.table.item(r, 0).text() for r in range(2)} == {"0x123", "0x01ABCDEF"}


def test_set_config_changes_load(qtbot):
    hub = FrameHub(); w = StatisticsWindow(hub, BusConfig("virtual", "x", bitrate=500_000)); qtbot.addWidget(w)
    batch = [can.Message(arbitration_id=1, data=bytes(8), timestamp=0.5)]
    hub.batch.emit(batch)
    before = w.cards["Bus load"].text()
    w.set_config(BusConfig("virtual", "x", bitrate=250_000))
    hub.batch.emit(batch)
    assert w.cards["Bus load"].text() != before


def test_advance_evicts_when_quiet():
    s = BusStats(500_000, 2_000_000)
    s.add([can.Message(arbitration_id=1, timestamp=t / 10) for t in range(10)], now=1.0)
    assert s.fps > 0
    s.add([], now=3.0)
    assert s.fps == 0 and s.load_percent == 0 and s.per_id_fps == {}


def test_idle_tick_zeroes_cards(qtbot, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("canableview.stats.time.monotonic", lambda: clock[0])
    hub = FrameHub(); w = StatisticsWindow(hub, BusConfig("virtual", "x")); qtbot.addWidget(w)
    hub.batch.emit([can.Message(arbitration_id=1, timestamp=5.0)])
    assert w.cards["Frames/s"].text() == "1"
    clock[0] = 103.0
    w._on_idle()
    assert w.cards["Frames/s"].text() == "0" and w.table.rowCount() == 0


def test_out_of_order_timestamp_does_not_stall_eviction():
    s = BusStats(500_000, 2_000_000)
    s.add([can.Message(arbitration_id=1, timestamp=1000.0)], now=1000.0)  # far-future stamp at the head
    for t in range(100):
        s.add([can.Message(arbitration_id=2, timestamp=t / 10)], now=t / 10)
    assert s.fps <= 12  # ~10 frames in the 1 s window + the stray one, not 101
