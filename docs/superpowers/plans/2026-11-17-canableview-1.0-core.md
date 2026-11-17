# CANableView 1.0 Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working PySide6 MDI CAN analyzer with Trace, Transmit and Statistics windows, logging and replay, over slcan, gs_usb and virtual buses.

**Architecture:** One process (approach A). `BusManager` owns the python-can `Bus` and a `Notifier` reader thread, and dispatches every RX frame and every TX echo to registered listener callables. `FrameHub` is one such listener: it queues frames and emits one `batch` signal per ~50 ms on the GUI thread. The logger is another listener, so logging never depends on GUI speed.

**Tech Stack:** Python 3.12+, PySide6, python-can (`slcan`, `gs_usb`, `virtual`), pyserial, pyusb, pytest, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-17-canableview-design.md`

## Global Constraints

- Python 3.12+. Windows first; no OS-specific code outside `BusManager.open`.
- Only `BusManager` touches `can.Bus`. Windows never call python-can bus methods directly.
- Windows receive frames only via `FrameHub.batch`, never per frame.
- Every frame (RX and TX echo) reaches the logger listener on the reader/sender path, not via the GUI.
- Replay, cyclic TX and one-shot TX send nothing unless Transmit is armed; one "Stop all" action stops every cyclic task and replay and disarms.
- Trace ring-buffer default capacity 100 000 rows; hub batch interval 50 ms.
- UI built in code (no `.ui` files), Qt Fusion style.
- Software-only ID filtering (gs_usb has no hardware filters).

## Review Focus

1. USB cable pulled mid-session → reader thread fails; app must show "disconnected" with the error text, not crash or hang; log file stays readable. (Test in Task 1.)
2. Wrong or busy COM port / no gs_usb device → `open` fails; user sees a readable error and the app stays disconnected. (Test in Task 1.)
3. Trace buffer full → oldest rows dropped, row count stays at capacity, no exception. (Test in Task 3.)
4. Send pressed while disconnected or not armed → nothing sent, clear status message, no exception. (Test in Task 6.)
5. App closed while logging → logger stopped and file readable by `can.LogReader`. (Test in Task 8.)

---

### File structure

```
pyproject.toml
src/canableview/__init__.py
src/canableview/__main__.py        entry: python -m canableview
src/canableview/bus.py             BusConfig, BusManager
src/canableview/hub.py             FrameHub
src/canableview/trace_model.py     TraceModel (pure Qt model)
src/canableview/trace_window.py    TraceWindow, byte-highlight delegate, ID filter
src/canableview/stats.py           BusStats (pure) + StatisticsWindow
src/canableview/transmit.py        parse_hex, TxRow, TransmitModel, TransmitWindow
src/canableview/recorder.py        Recorder (logging), Replayer
src/canableview/main_window.py     MainWindow, ConnectionBar, status bar, QSettings
tests/...                          one test file per module
docs/hardware-checklist.md
```

---

### Task 1: Project scaffold and BusManager

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/canableview/__init__.py`, `src/canableview/bus.py`
- Test: `tests/test_bus.py`

**Interfaces:**
- Produces:
  - `@dataclass BusConfig(interface: Literal["slcan","gs_usb","virtual"], channel: str, bitrate: int = 500_000, fd: bool = False, data_bitrate: int = 2_000_000)`
  - `class BusManager(QObject)`: signals `connected()`, `disconnected()`, `error(str)`; `open(cfg: BusConfig) -> None`; `close() -> None`; `is_open: bool` (property); `send(msg: can.Message) -> bool`; `send_periodic(msg: can.Message, period_s: float) -> can.broadcastmanager.CyclicSendTaskABC | None`; `add_listener(fn: Callable[[can.Message], None]) -> None`; `remove_listener(fn) -> None`.
  - TX echo: `send` and each periodic send dispatch a copy with `is_rx=False` and `timestamp=time.time()` to all listeners.

- [ ] **Step 1: Scaffold.** `git init`; `pyproject.toml` with src layout, deps `PySide6`, `python-can[gs_usb,serial]`, dev deps `pytest`, `pytest-qt`; `requires-python = ">=3.12"`. `pip install -e .[dev]`.

- [ ] **Step 2: Write failing tests**

```python
def test_virtual_roundtrip(qtbot):
    a, b = BusManager(), BusManager()
    got = []
    b.add_listener(got.append)
    a.open(BusConfig("virtual", "t1")); b.open(BusConfig("virtual", "t1"))
    assert a.send(can.Message(arbitration_id=0x123, data=b"\x01\x02"))
    qtbot.waitUntil(lambda: len(got) == 1, timeout=2000)
    assert got[0].arbitration_id == 0x123 and got[0].is_rx

def test_send_echoes_tx_to_own_listeners(qtbot):
    a = BusManager(); seen = []
    a.add_listener(seen.append); a.open(BusConfig("virtual", "t2"))
    a.send(can.Message(arbitration_id=0x200, data=b"\x01"))
    assert len(seen) == 1 and seen[0].is_rx is False

def test_open_bad_port_emits_error(qtbot):
    m = BusManager()
    with qtbot.waitSignal(m.error, timeout=3000):
        m.open(BusConfig("slcan", "COM_DOES_NOT_EXIST"))
    assert not m.is_open

def test_send_when_closed_returns_false():
    assert BusManager().send(can.Message(arbitration_id=1)) is False

def test_reader_failure_emits_error_and_disconnected(qtbot, monkeypatch):
    m = BusManager(); m.open(BusConfig("virtual", "t3"))
    monkeypatch.setattr(m._bus, "recv", Mock(side_effect=can.CanOperationError("unplugged")))
    with qtbot.waitSignals([m.error, m.disconnected], timeout=3000):
        pass
    assert not m.is_open
```

- [ ] **Step 3: Run** `pytest tests/test_bus.py -v` → FAIL (module missing).

- [ ] **Step 4: Implement `bus.py`.**
  - `open` maps config to `can.Bus` kwargs: virtual → `interface="virtual", channel=cfg.channel, receive_own_messages=False`; slcan → `channel=cfg.channel, bitrate=cfg.bitrate` (+ FD kwargs — **verify** the current python-can slcan FD parameter names in its docs; if unsupported, emit `error("CAN FD over slcan not supported by installed python-can")`); gs_usb → **verify** kwargs (`channel`/`index`/`bus`/`address`) against python-can gs_usb docs; channel string is the device index.
  - Any exception in `open` → `error.emit(str(exc))`, stay closed, never raise.
  - `can.Notifier(bus, [self._dispatch])`; `_dispatch` calls every listener, catching and logging listener exceptions so one bad listener can't kill the reader.
  - A 500 ms `QTimer` checks `notifier.exception`; if set → `close()` then `error.emit(...)`, `disconnected.emit()`.
  - `send_periodic` uses `bus.send_periodic(msg, period_s, modifier_callback=...)` where the callback dispatches the echo (python-can ≥ 4.2; verify).

- [ ] **Step 5: Run** `pytest tests/test_bus.py -v` → PASS.

- [ ] **Step 6: Commit** `feat: BusManager with slcan, gs_usb and virtual backends`

---

### Task 2: FrameHub

**Files:** Create `src/canableview/hub.py`; Test `tests/test_hub.py`

**Interfaces:**
- Consumes: `BusManager.add_listener`.
- Produces: `class FrameHub(QObject)`: signal `batch(list)` (list of `can.Message`); `push(msg: can.Message) -> None` (thread-safe); `start(interval_ms: int = 50)`, `stop()`.

- [ ] **Step 1: Failing tests**

```python
def test_push_from_thread_arrives_as_one_batch(qtbot):
    hub = FrameHub(); hub.start(50)
    t = threading.Thread(target=lambda: [hub.push(can.Message(arbitration_id=i)) for i in range(500)])
    with qtbot.waitSignal(hub.batch, timeout=1000) as sig:
        t.start(); t.join()
    assert len(sig.args[0]) == 500

def test_no_signal_when_empty(qtbot):
    hub = FrameHub(); hub.start(20)
    with qtbot.assertNotEmitted(hub.batch, wait=100):
        pass
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with `collections.deque` + `QTimer`; drain everything present at tick time into one list; emit only if non-empty.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: FrameHub batches frames for the GUI`

---

### Task 3: TraceModel

**Files:** Create `src/canableview/trace_model.py`; Test `tests/test_trace_model.py`

**Interfaces:**
- Produces: `class TraceModel(QAbstractTableModel)`: `__init__(capacity: int = 100_000)`; `COLUMNS = ["Time", "Δt", "ID", "Dir", "DLC", "Flags", "Data"]`; `set_mode(mode: Literal["scroll", "fixed"])` (clears); `append_batch(msgs: list[can.Message])`; `clear()`; `message_at(row: int) -> can.Message`; `CHANGED_ROLE = Qt.UserRole + 1` → `list[int]` of byte indices changed within the last 1.0 s (fixed mode only, else `[]`).
- Display formats: Time `f"{t:.4f}"` relative to first frame; ID `0x{id:03X}` standard, `0x{id:08X}` extended; Dir `Rx`/`Tx`; Flags any of `FD BRS ESI RTR ERR` space-joined; Data uppercase hex bytes space-separated.

- [ ] **Step 1: Failing tests**

```python
def msg(i, data=b"\x00"*8, t=0.0, **kw): return can.Message(arbitration_id=i, data=data, timestamp=t, **kw)

def test_scroll_appends_rows():
    m = TraceModel(); m.append_batch([msg(1), msg(2)]); assert m.rowCount() == 2

def test_capacity_drops_oldest():
    m = TraceModel(capacity=100)
    m.append_batch([msg(i) for i in range(250)])
    assert m.rowCount() == 100 and m.message_at(0).arbitration_id == 150

def test_fixed_mode_one_row_per_id_and_dir():
    m = TraceModel(); m.set_mode("fixed")
    m.append_batch([msg(1), msg(1), msg(2), msg(1, is_rx=False)])
    assert m.rowCount() == 3

def test_fixed_mode_reports_changed_bytes():
    m = TraceModel(); m.set_mode("fixed")
    m.append_batch([msg(1, b"\x00\x00", t=0.0), msg(1, b"\x00\x05", t=0.1)])
    assert m.index(0, 6).data(TraceModel.CHANGED_ROLE) == [1]

def test_formats():
    m = TraceModel()
    m.append_batch([msg(0x18FEF100, b"\xAB", is_extended_id=True, is_fd=True, bitrate_switch=True)])
    assert m.index(0, 2).data() == "0x18FEF100"
    assert m.index(0, 5).data() == "FD BRS"
    assert m.index(0, 6).data() == "AB"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Scroll: `deque(maxlen=capacity)`; per batch, if overflow `beginRemoveRows(0, n-1)` first, then one `beginInsertRows` for the batch. Fixed: dict key `(id, is_extended_id, is_rx)` → row index, plus per-row `list[float]` last-change time per byte; existing row → `dataChanged`. "Within 1.0 s" is measured against the newest frame timestamp, so tests are deterministic.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: TraceModel ring buffer with scroll and fixed modes`

---

### Task 4: TraceWindow

**Files:** Create `src/canableview/trace_window.py`; Test `tests/test_trace_window.py`

**Interfaces:**
- Consumes: `TraceModel`, `FrameHub.batch`.
- Produces: `class TraceWindow(QWidget)`: `__init__(hub: FrameHub)`; `set_id_filter(text: str) -> bool` (accepts `""`, `"0x100"`, `"0x100-0x3FF"`, comma-separated list; returns False and leaves filter unchanged on bad input); `model: TraceModel`; `proxy: QSortFilterProxyModel`; mode toggle (scroll/fixed) and a Clear action in a small toolbar; auto-scroll to bottom in scroll mode unless the user has scrolled up.
- `ByteHighlightDelegate` paints Data column bytes listed in `CHANGED_ROLE` with an amber background.

- [ ] **Step 1: Failing tests**

```python
def test_batch_reaches_view(qtbot):
    hub = FrameHub(); w = TraceWindow(hub); qtbot.addWidget(w)
    hub.batch.emit([can.Message(arbitration_id=0x123)])
    assert w.model.rowCount() == 1

def test_id_filter_range(qtbot):
    hub = FrameHub(); w = TraceWindow(hub); qtbot.addWidget(w)
    hub.batch.emit([can.Message(arbitration_id=i) for i in (0x50, 0x150, 0x500)])
    assert w.set_id_filter("0x100-0x3FF")
    assert w.proxy.rowCount() == 1

def test_bad_filter_rejected(qtbot):
    w = TraceWindow(FrameHub()); qtbot.addWidget(w)
    assert w.set_id_filter("zz") is False
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with `QTableView` + `QSortFilterProxyModel` subclass overriding `filterAcceptsRow` against parsed ranges; uniform row heights (`verticalHeader().setDefaultSectionSize`) for speed; monospace font for Data/ID.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: TraceWindow with ID filter and changed-byte highlight`

---

### Task 5: Statistics

**Files:** Create `src/canableview/stats.py`; Test `tests/test_stats.py`

**Interfaces:**
- Produces:
  - `frame_bits(msg: can.Message) -> tuple[int, int]` → (bits at nominal rate, bits at data rate). Classic: `(47 + 8*len, 0)` standard / `(67 + 8*len, 0)` extended. FD with BRS: arbitration overhead at nominal, data field + CRC at data rate. FD without BRS: all at nominal.
  - `class BusStats`: `__init__(bitrate: int, data_bitrate: int, window_s: float = 1.0)`; `add(msgs: list[can.Message], now: float)`; `load_percent: float`; `fps: float`; `error_frames: int`; `per_id_fps: dict[int, float]`; `unique_ids: int`.
  - `class StatisticsWindow(QWidget)`: `__init__(hub: FrameHub, bus_cfg: BusConfig)`; four value cards (Bus load, Frames/s, Error frames, Unique IDs) + per-ID table.
- Shortcut comment required: bit stuffing ignored (real load ~10–20 % higher); upgrade if users compare against CANalyzer.

- [ ] **Step 1: Failing tests**

```python
def test_classic_bits():
    assert frame_bits(can.Message(arbitration_id=1, data=bytes(8))) == (111, 0)

def test_load_500k():
    s = BusStats(500_000, 2_000_000)
    s.add([can.Message(arbitration_id=1, data=bytes(8), timestamp=i/1000) for i in range(1000)], now=1.0)
    assert s.load_percent == pytest.approx(22.2, abs=0.1)
    assert s.fps == pytest.approx(1000, abs=1)

def test_error_frames_counted():
    s = BusStats(500_000, 2_000_000)
    s.add([can.Message(is_error_frame=True)], now=0.0)
    assert s.error_frames == 1
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; FD BRS split — choose arbitration overhead constants and document them in a one-line comment; add a test pinning the chosen value.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: bus statistics and Statistics window`

---

### Task 6: Transmit

**Files:** Create `src/canableview/transmit.py`; Test `tests/test_transmit.py`

**Interfaces:**
- Consumes: `BusManager.send`, `BusManager.send_periodic`, `BusManager.is_open`.
- Produces:
  - `parse_hex(text: str, fd: bool) -> bytes` — accepts `"01 02 0A"` or `"01020A"`; raises `ValueError` on non-hex, odd digit count, >8 bytes classic, or FD length not in {0–8, 12, 16, 20, 24, 32, 48, 64}.
  - `@dataclass TxRow(arbitration_id: int, extended: bool, fd: bool, brs: bool, data: bytes, period_ms: int | None)`.
  - `class TransmitWindow(QWidget)`: `__init__(bus: BusManager)`; `add_row(row: TxRow)`; `armed: bool`; `arm(on: bool)`; `send_row(i: int) -> bool`; `start_cyclic(i: int) -> bool`; `stop_all()`; signal `status(str)`.
  - Armed state shown in the window title bar text ("armed" in red); "Stop all" button always enabled.

- [ ] **Step 1: Failing tests**

```python
def test_parse_hex_ok(): assert parse_hex("01 02 0a", fd=False) == b"\x01\x02\x0a"
@pytest.mark.parametrize("bad", ["zz", "123", "00 "*9])
def test_parse_hex_rejects(bad):
    with pytest.raises(ValueError): parse_hex(bad, fd=False)
def test_parse_hex_fd_len():
    with pytest.raises(ValueError): parse_hex("00"*9, fd=True)
    assert len(parse_hex("00"*12, fd=True)) == 12

def test_send_requires_arm(qtbot):
    bus = Mock(is_open=True); w = TransmitWindow(bus); qtbot.addWidget(w)
    w.add_row(TxRow(0x200, False, False, False, b"\x01", None))
    with qtbot.waitSignal(w.status):
        assert w.send_row(0) is False
    bus.send.assert_not_called()

def test_send_when_disconnected(qtbot):
    bus = Mock(is_open=False); w = TransmitWindow(bus); qtbot.addWidget(w)
    w.add_row(TxRow(0x200, False, False, False, b"\x01", None)); w.arm(True)
    assert w.send_row(0) is False

def test_stop_all_stops_tasks_and_disarms(qtbot):
    task = Mock(); bus = Mock(is_open=True); bus.send_periodic.return_value = task
    w = TransmitWindow(bus); qtbot.addWidget(w)
    w.add_row(TxRow(0x200, False, False, False, b"\x01", 100)); w.arm(True)
    assert w.start_cyclic(0)
    w.stop_all()
    task.stop.assert_called_once(); assert w.armed is False
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; table cells edited inline, invalid data cell shows the `ValueError` text via `status` and keeps the old value.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: Transmit window with arm, one-shot and cyclic send`

---

### Task 7: Recorder and Replayer

**Files:** Create `src/canableview/recorder.py`; Test `tests/test_recorder.py`

**Interfaces:**
- Consumes: `BusManager.add_listener/remove_listener/send`.
- Produces:
  - `class Recorder`: `__init__(bus: BusManager)`; `start(path: Path) -> None` (format by extension `.blf` `.asc` `.csv` via `can.Logger`; other extension → `ValueError`); `stop() -> None`; `active: bool`; `path: Path | None`.
  - `class Replayer(QObject)`: `__init__(bus: BusManager)`; `start(path: Path) -> None` (worker thread, `can.MessageSync(can.LogReader(path))`, each frame → `bus.send`); `stop()`; signal `finished()`. Caller (MainWindow) checks Transmit armed before calling `start`; `TransmitWindow.stop_all` also calls `Replayer.stop`.

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.parametrize("ext", [".blf", ".asc", ".csv"])
def test_record_roundtrip(tmp_path, qtbot, ext):
    bus = BusManager(); bus.open(BusConfig("virtual", f"r{ext}"))
    rec = Recorder(bus); p = tmp_path / f"x{ext}"; rec.start(p)
    for i in range(10): bus.send(can.Message(arbitration_id=i, data=b"\x01"))
    rec.stop()
    assert len(list(can.LogReader(p))) == 10

def test_bad_extension(tmp_path):
    with pytest.raises(ValueError): Recorder(BusManager()).start(tmp_path / "x.txt")

def test_replay_sends_all(tmp_path, qtbot):
    p = tmp_path / "in.asc"
    with can.ASCWriter(p) as wr:
        for i in range(5): wr.on_message_received(can.Message(arbitration_id=i, timestamp=i / 1000))
    bus = Mock(); r = Replayer(bus)
    with qtbot.waitSignal(r.finished, timeout=3000): r.start(p)
    assert bus.send.call_count == 5
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: logging to BLF/ASC/CSV and log replay`

---

### Task 8: MainWindow and app entry

**Files:** Create `src/canableview/main_window.py`, `src/canableview/__main__.py`; Test `tests/test_main_window.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `class ConnectionBar(QToolBar)`: interface combo (`slcan`, `gs_usb`, `virtual`), channel edit (default `COM3` / `0` / `vcan0` per interface), bitrate combo (125k, 250k, 500k, 1M), FD checkbox, data bitrate combo (1M, 2M, 4M, 5M; enabled only with FD), Connect/Disconnect button, Log, Replay, Clear actions; `config() -> BusConfig`; `set_interface(name: str)` (also sets the default channel); `channel: QLineEdit`.
  - `class MainWindow(QMainWindow)`: owns `bus: BusManager`, `hub: FrameHub`, `recorder: Recorder`, `replayer: Replayer`, `trace: TraceWindow`, `transmit: TransmitWindow`, `connection_bar: ConnectionBar`, `last_error: str`; `connect_bus()` opens with `connection_bar.config()`; `QMdiArea` central; Window menu opens Trace/Transmit/Statistics (one Trace, Transmit, Statistics open by default, tiled); status bar shows Rx count, Tx count, log file name, buffer fill, connection state and last error; `closeEvent` stops replay, cyclic tasks, recorder, closes bus, saves geometry + open windows to `QSettings("CANableView", "CANableView")`.
  - `__main__.py`: `QApplication`, `setStyle("Fusion")`, show `MainWindow`.

- [ ] **Step 1: Failing tests**

```python
def test_virtual_end_to_end(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w.connection_bar.set_interface("virtual"); w.connect_bus()
    other = BusManager(); other.open(BusConfig("virtual", "vcan0"))
    other.send(can.Message(arbitration_id=0x321))
    qtbot.waitUntil(lambda: w.trace.model.rowCount() == 1, timeout=2000)

def test_close_while_logging_leaves_readable_file(qtbot, tmp_path):
    w = MainWindow(); qtbot.addWidget(w)
    w.connection_bar.set_interface("virtual"); w.connect_bus()
    p = tmp_path / "l.blf"; w.recorder.start(p)
    w.bus.send(can.Message(arbitration_id=1))
    w.close()
    assert len(list(can.LogReader(p))) == 1

def test_connect_error_shown_in_status(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w.connection_bar.set_interface("slcan"); w.connection_bar.channel.setText("COM_NOPE"); w.connect_bus()
    assert w.last_error and not w.bus.is_open
    assert w.last_error in w.statusBar().currentMessage()
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Tests must use a temp `QSettings` scope (`QSettings.setPath` to `tmp_path` in a conftest fixture) so they never touch the user's real settings.
- [ ] **Step 4: Run** `pytest -v` (full suite) → PASS.
- [ ] **Step 5: Manual check:** `python -m canableview`, connect virtual, open a second app instance or script sending on `vcan0`, see frames, toggle fixed mode, record and replay.
- [ ] **Step 6: Commit** `feat: MDI main window and app entry point`

---

### Task 9: Throughput stress test and hardware checklist

**Files:** Create `tests/test_stress.py`, `docs/hardware-checklist.md`

- [ ] **Step 1: Stress test** (marked `@pytest.mark.slow`): sender thread pushes 10 000 frames/s for 5 s on virtual bus into a `MainWindow`; assert recorder file holds all 50 000 frames and the GUI event loop processed a 10 ms `QTimer` with max gap < 200 ms. Record the observed numbers in the test's docstring.
- [ ] **Step 2: Run** `pytest -m slow -v`; if it fails, record the limit found and raise it with the user before tuning (do not silently move to approach B).
- [ ] **Step 3: Write `docs/hardware-checklist.md`:** two CANable 2.0, 120 Ω at each end; checks: slcan classic 500k loopback, slcan FD 500k/2M loopback, gs_usb classic loopback (candleLight firmware), cable unplug mid-trace, wrong COM port, logging 10 min at 50 % load.
- [ ] **Step 4: Commit** `test: throughput stress test and hardware checklist`
