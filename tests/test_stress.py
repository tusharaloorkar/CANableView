import threading
import time

import can
import pytest
from PySide6.QtCore import QTimer

from canableview.main_window import MainWindow

RATE, SECONDS, CHUNK = 10_000, 5, 100


@pytest.mark.slow
def test_virtual_bus_10k_fps_for_5s(qtbot, tmp_path):
    """Approach A (reader thread + 50 ms GUI batches) under 10 000 frames/s for 5 s.

    Asserts: BLF holds every frame actually sent; 10 ms GUI timer max gap < 200 ms.
    Observed (2026-11-17, dev machine): sent 50 000 at 9 994/s, logged 50 000,
    max GUI gap 37 ms, 6.4 s total.
    """
    w = MainWindow()
    qtbot.addWidget(w)
    w.connection_bar.set_interface("virtual")
    w.connect_bus()
    path = tmp_path / "stress.blf"
    w.start_logging(path)

    sent = [0]
    done = threading.Event()

    def sender():
        bus = can.Bus(interface="virtual", channel="vcan0")
        t0 = time.perf_counter()
        try:
            for i in range(RATE * SECONDS // CHUNK):
                for j in range(CHUNK):
                    n = i * CHUNK + j
                    bus.send(can.Message(arbitration_id=n % 0x7FF, data=n.to_bytes(4, "big")))
                    sent[0] += 1
                delay = t0 + (i + 1) * CHUNK / RATE - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
        finally:
            bus.shutdown()
            done.set()

    stamps: list[float] = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: stamps.append(time.perf_counter()))
    timer.start()

    t_start = time.perf_counter()
    threading.Thread(target=sender, daemon=True).start()
    while not done.is_set():
        qtbot.wait(10)
    send_time = time.perf_counter() - t_start
    qtbot.wait(1000)  # let reader thread drain
    timer.stop()
    w.stop_logging()

    logged = len(list(can.LogReader(path)))
    max_gap = max(b - a for a, b in zip(stamps, stamps[1:])) * 1000
    print(f"sent={sent[0]} rate={sent[0] / send_time:.0f}/s logged={logged} max_gap={max_gap:.0f}ms")
    assert logged == sent[0]
    assert max_gap < 200
