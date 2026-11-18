# CANableView

A CAN / CAN FD analyzer for low-cost CANable boards, with a multi-window (MDI) interface built in PySide6.

## Features

- **Trace window**: receive and transmit frames in scrolling or fixed mode (one row per ID). Changed bytes are highlighted, and an ID filter accepts single IDs, ranges and lists, such as `0x100-0x3FF, 0x7E8`.
- **Transmit window**: send frames once or on a cycle, including CAN FD with bit-rate switching. Nothing is sent until you arm it, and **Stop all** halts every cyclic frame and any running replay with one click.
- **Statistics**: bus load, frames per second, error frames and a per-ID rate table.
- **Logging and replay**: record to BLF, ASC or CSV, and replay a log with its original timing.
- **Virtual bus**: develop, test and demo without any hardware.

## Supported hardware

| Board | Firmware | Interface | CAN FD |
|---|---|---|---|
| CANable 2.0 | slcan (stock) | `slcan` (COM port) | Yes |
| CANable 1.x / 2.0 | candleLight | `gs_usb` (native USB) | No |
| — | — | `virtual` | Yes |

On CANable 2.0, CAN FD works only with the slcan firmware. You can switch firmware with the [official updater](https://canable.io/updater/).

## Install

Requires Python 3.12 or newer. Windows is the main target.

```bash
git clone https://github.com/tusharaloorkar/CANableView.git
cd CANableView
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

## Run

```bash
python -m canableview
```

To try it without hardware, choose `virtual` in the toolbar, keep the channel as `vcan0`, and click **Connect**.

## Test

```bash
pytest
pytest -m slow
```

The `slow` marker selects a throughput stress test, which pushes 10,000 frames/s for 5 s and checks that every frame is logged.

For checks on real boards, see [docs/hardware-checklist.md](docs/hardware-checklist.md).

## Roadmap

- 1.1: DBC decoding and live signal graphs
- 1.2: J1939
- 1.3: ISO-TP and UDS diagnostics
- 2.0: Python scripting

## License

[MIT](LICENSE)
