# CANableView — Design

Date: 2026-11-17
Status: Draft, awaiting approval

## Intent

A free, personal-project CAN / CAN FD analyzer for low-cost CANable boards, with a
CANalyzer-style MDI interface. Built with PySide6. It must serve four uses equally:

- developing and debugging own ECU firmware
- reverse-engineering vehicle buses
- industrial / J1939 buses
- a portfolio-quality showcase

Why: CANalyzer costs thousands; existing free tools for CANable (SavvyCAN, Cangaroo)
are rough. The goal is a polished, reliable tool that makes a $30 adapter feel professional.

## Goals

- Trace window for RX and TX, CANalyzer-style, that stays responsive on a busy bus.
- Support both CANable firmwares:
  - **slcan** (stock firmware, COM port) — the only route to CAN FD on CANable 2.0.
  - **gs_usb / candleLight** — classic CAN, native USB.
- Virtual bus so everything can be developed, tested and demoed without hardware.
- Every frame received is logged when logging is on, even if the GUI falls behind.
- Ship in phases; each phase is usable on its own.

## Non-goals

- Linux/macOS polish in 1.0 (Windows first; python-can keeps the door open).
- Other adapter brands (PEAK, Kvaser, Vector) — python-can supports them, but no UI or
  testing effort until asked.
- LIN, FlexRay, Ethernet.
- Writing or flashing CANable firmware.

## Anti-goals (failure even if it "works")

- GUI freezes or stutters under bus load.
- Silently dropping frames from a log.
- Sending frames on a real bus the user did not explicitly ask to send
  (replay, cyclic TX and scripts must be visibly armed and stoppable in one click).
- A feature list that grows faster than it stabilizes: each phase must be solid before the next.

## Constraints and known facts

- Python 3.12+, PySide6, python-can.
- CANable 1.x: classic CAN only. CANable 2.0 (STM32G431): FD-capable hardware.
- Per canable.io, candleLight firmware on CANable 2.0 does **not** support FD frames;
  candleLight_fw README lists STM32G431 boards as not yet supported. FD therefore goes
  through slcan. **Unverified:** python-can slcan FD on Windows with current CANable 2.0
  firmware — first thing to test once hardware arrives.
- gs_usb on Windows needs `pyusb` + a libusb backend DLL; the device itself enumerates
  as WinUSB (no driver install).
- python-can gs_usb does not support hardware message filtering → filter in software.
- Hardware for development: 2× CANable 2.0 wired together, 120 Ω termination at each end.

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| **A (chosen)** | One process. python-can `Bus` + `Notifier` on a reader thread → queue → `QTimer` drains every ~50 ms into a ring-buffer model. | Simplest, easy to debug. GIL caps throughput; a saturated 5 Mbit FD bus may lag the GUI (logging still keeps every frame). |
| B | Bus in a separate `multiprocessing` worker, batches over pipe/shared memory. | GUI can never stall the receiver. Costs: Windows spawn, pickling, harder errors/debugging. Only worth it if A measurably drops frames. |
| C | Qt `QtSerialBus` / `QCanBus`. | Rejected: no slcan or candleLight plugin on Windows. |

Chosen: **A** (Claude's call; user accepted the architecture as drawn). The bus sits behind
one class so moving to B later changes only that class.

## Architecture

```
MDI windows      Trace | Transmit | Statistics | Signals(1.1) | J1939(1.2) | Diag(1.3) | Script(2.0)
                    ▲
Core             Frame hub (ring buffer, 50 ms batches)   Logger / replay (BLF, ASC, CSV)
                    ▲                                          ▲
Bus layer        Bus manager — python-can Bus + Notifier on reader thread; TX goes down through it
                    │
Backends         slcan (FD, COM port) | gs_usb (classic, candleLight) | virtual
                    │
Hardware         2× CANable 2.0
```

### Components

- **Bus manager** — owns the python-can `Bus`. Opens with interface (`slcan`, `gs_usb`,
  `virtual`), channel, bitrate, and FD data bitrate. Reader thread via `Notifier`.
  Exposes `send(msg)` and connect/disconnect/error signals. The only code that touches python-can's Bus.
- **Frame hub** — thread-safe queue fed by the reader; a `QTimer` (~50 ms) drains it and
  emits one batch signal. All windows subscribe to batches, never to single frames.
- **Logger** — a `Notifier` listener (python-can `BLFWriter` / `ASCWriter` / `CSVWriter`),
  so it runs on the reader path and never depends on GUI speed.
- **Replay** — python-can `LogReader` + `MessageSync`, sends through the bus manager.
- **Trace window** — `QTableView` over a ring-buffer `QAbstractTableModel` (fixed cap, e.g.
  100k rows). Modes: chronological scroll and fixed (one row per ID, updated in place).
  Columns: time, Δt, channel, ID, dir RX/TX, DLC, flags (FD/BRS/ESI/RTR/ERR), data.
  Software ID filters. Changed-byte highlighting in fixed mode.
- **Transmit window** — table of frames: one-shot and cyclic (python-can
  `send_periodic`). 1.1 adds signal editing from DBC.
- **Statistics window** — bus load %, frames/sec total and per ID, error frame count.
- **MDI shell** — `QMainWindow` + `QMdiArea`, connection toolbar, window menu,
  save/restore layout and settings (`QSettings`).

### Phases

| Phase | Scope | Estimate (8–10 h/week) |
|---|---|---|
| 1.0 Core | Bus manager, 3 backends, Trace, Transmit, Statistics, logging, replay | 4–6 weeks |
| 1.1 DBC | `cantools` decoding in Trace, Signals window with live `pyqtgraph` plots, DBC signal editing in Transmit | 2–3 weeks |
| 1.2 J1939 | PGN/SPN decoding, transport protocol (BAM / CMDT) reassembly | 2 weeks |
| 1.3 Diagnostics | ISO-TP + UDS requests (read DTCs, read data by ID) | 2–3 weeks |
| 2.0 Scripting | Python node reacting to frames and timers, CAPL-like | 3–4 weeks |

## Testing

- Unit tests (pytest) for models, filters, statistics math, decoders — run on the virtual bus.
- A stress test that pushes N frames/sec through the virtual bus to find approach A's real limit.
- Hardware checklist once boards arrive: slcan classic, slcan FD, gs_usb classic, two-board loopback.

## Left to the builder

- Package layout, naming, exact column widths and colors.
- Ring-buffer size default and batch interval tuning (start 100k rows / 50 ms).
- Library choice for dependency-light extras (ISO-TP: `can-isotp`; UDS: `udsoncan`;
  J1939: `can-j1939` or own decoder) — decide at the start of each phase.
- Packaging (PyInstaller) — decide before first release.

## Calls Claude made (check these)

1. Approach A, single process.
2. Windows-first; other OSes not tested in 1.0.
3. Other adapter brands out of scope.
4. Replay / cyclic TX / scripts must be explicitly armed (safety on real vehicles).
5. Logger runs on the reader path, not the GUI path.
6. Python 3.12+.
