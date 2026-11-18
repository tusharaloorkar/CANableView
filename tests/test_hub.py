import threading

import can

from canableview.hub import FrameHub


def test_push_from_thread_arrives_as_one_batch(qtbot):
    hub = FrameHub()
    hub.start(50)
    t = threading.Thread(target=lambda: [hub.push(can.Message(arbitration_id=i)) for i in range(500)])
    with qtbot.waitSignal(hub.batch, timeout=1000) as sig:
        t.start()
        t.join()
    assert len(sig.args[0]) == 500
    hub.stop()


def test_no_signal_when_empty(qtbot):
    hub = FrameHub()
    hub.start(20)
    with qtbot.assertNotEmitted(hub.batch, wait=100):
        pass
    hub.stop()
