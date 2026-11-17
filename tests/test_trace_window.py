import can

from canableview.hub import FrameHub
from canableview.trace_window import TraceWindow, valid_changed


def test_batch_reaches_view(qtbot):
    hub = FrameHub(); w = TraceWindow(hub); qtbot.addWidget(w)
    hub.batch.emit([can.Message(arbitration_id=0x123)])
    assert w.model.rowCount() == 1


def test_id_filter_range(qtbot):
    hub = FrameHub(); w = TraceWindow(hub); qtbot.addWidget(w)
    hub.batch.emit([can.Message(arbitration_id=i) for i in (0x50, 0x150, 0x500)])
    assert w.set_id_filter("0x100-0x3FF")
    assert w.proxy.rowCount() == 1


def test_id_filter_list_and_clear(qtbot):
    hub = FrameHub(); w = TraceWindow(hub); qtbot.addWidget(w)
    hub.batch.emit([can.Message(arbitration_id=i) for i in (0x50, 0x150, 0x500)])
    assert w.set_id_filter("0x50, 0x500")
    assert w.proxy.rowCount() == 2
    assert w.set_id_filter("")
    assert w.proxy.rowCount() == 3


def test_bad_filter_rejected_keeps_old(qtbot):
    hub = FrameHub(); w = TraceWindow(hub); qtbot.addWidget(w)
    hub.batch.emit([can.Message(arbitration_id=i) for i in (0x50, 0x150)])
    assert w.set_id_filter("0x50")
    assert w.set_id_filter("zz") is False
    assert w.set_id_filter("0x3-0x1") is False
    assert w.proxy.rowCount() == 1


def test_clear_and_mode(qtbot):
    hub = FrameHub(); w = TraceWindow(hub); qtbot.addWidget(w)
    hub.batch.emit([can.Message(arbitration_id=1)])
    w.clear_action.trigger()
    assert w.model.rowCount() == 0
    w.mode_action.setChecked(True)
    assert w.model._mode == "fixed"
    w.mode_action.setChecked(False)
    assert w.model._mode == "scroll"


def test_refresh_timer_only_in_fixed_and_visible(qtbot):
    hub = FrameHub(); w = TraceWindow(hub); qtbot.addWidget(w)
    w.show()
    assert not w.refresh_timer.isActive()
    w.mode_action.setChecked(True)
    assert w.refresh_timer.isActive() and w.refresh_timer.interval() == 250
    w.hide()
    assert not w.refresh_timer.isActive()
    w.show()
    assert w.refresh_timer.isActive()


def test_highlight_indices_clamped_to_payload():
    assert valid_changed([0, 2, 5, 9], 3) == [0, 2]
    assert valid_changed(None, 3) == []
