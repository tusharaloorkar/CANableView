import can

from canableview.trace_model import TraceModel


def msg(i, data=b"\x00" * 8, t=0.0, **kw):
    return can.Message(arbitration_id=i, data=data, timestamp=t, **kw)


def test_scroll_appends_rows():
    m = TraceModel()
    m.append_batch([msg(1), msg(2)])
    assert m.rowCount() == 2


def test_capacity_drops_oldest():
    m = TraceModel(capacity=100)
    m.append_batch([msg(i) for i in range(250)])
    assert m.rowCount() == 100 and m.message_at(0).arbitration_id == 150


def test_capacity_across_batches_one_insert_signal(qtbot):
    m = TraceModel(capacity=100)
    m.append_batch([msg(i) for i in range(80)])
    ins = []
    m.rowsInserted.connect(lambda *a: ins.append(a))
    m.append_batch([msg(i) for i in range(80, 120)])
    assert m.rowCount() == 100 and m.message_at(0).arbitration_id == 20 and len(ins) == 1


def test_fixed_mode_one_row_per_id_and_dir():
    m = TraceModel()
    m.set_mode("fixed")
    m.append_batch([msg(1), msg(1), msg(2), msg(1, is_rx=False)])
    assert m.rowCount() == 3


def test_fixed_mode_reports_changed_bytes():
    m = TraceModel()
    m.set_mode("fixed")
    m.append_batch([msg(1, b"\x00\x00", t=0.0), msg(1, b"\x00\x05", t=0.1)])
    assert m.index(0, 6).data(TraceModel.CHANGED_ROLE) == [1]
    m.append_batch([msg(2, t=5.0)])
    assert m.index(0, 6).data(TraceModel.CHANGED_ROLE) == []


def test_scroll_changed_role_empty():
    m = TraceModel()
    m.append_batch([msg(1, b"\x00", t=0.0), msg(1, b"\x01", t=0.1)])
    assert m.index(1, 6).data(TraceModel.CHANGED_ROLE) == []


def test_delta_t_modes():
    m = TraceModel()
    m.append_batch([msg(1, t=1.0), msg(2, t=1.5), msg(1, t=2.0)])
    assert [m.index(r, 1).data() for r in range(3)] == ["0.0000", "0.5000", "0.5000"]
    m.set_mode("fixed")
    m.append_batch([msg(1, t=1.0), msg(2, t=1.5), msg(1, t=2.0)])
    assert m.index(0, 1).data() == "1.0000"  # 2.0 - previous id-1 frame at 1.0
    assert m.index(1, 1).data() == "0.0000"  # first frame for id 2
    assert m.index(0, 0).data() == "1.0000"  # latest frame, relative to first (1.0)


def test_formats():
    m = TraceModel()
    m.append_batch([msg(0x18FEF100, b"\xAB", is_extended_id=True, is_fd=True, bitrate_switch=True)])
    assert m.index(0, 2).data() == "0x18FEF100"
    assert m.index(0, 5).data() == "FD BRS"
    assert m.index(0, 6).data() == "AB"
    m.append_batch([msg(0x12, b"", is_rx=False, is_remote_frame=True, is_extended_id=False), msg(0x1, is_error_frame=True)])
    assert m.index(1, 2).data() == "0x012" and m.index(1, 3).data() == "Tx"
    assert m.index(1, 5).data() == "RTR" and m.index(2, 5).data() == "ERR"
    assert m.index(0, 3).data() == "Rx" and m.index(0, 4).data() == "1"


def test_highlight_expires_on_idle_bus(monkeypatch):
    import time
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    m = TraceModel()
    m.set_mode("fixed")
    m.append_batch([msg(1, b"\x00\x00", t=0.0), msg(1, b"\x00\x05", t=0.1)])
    assert m.index(0, 6).data(TraceModel.CHANGED_ROLE) == [1]
    clock[0] += 2.0  # no new frames
    assert m.index(0, 6).data(TraceModel.CHANGED_ROLE) == []
