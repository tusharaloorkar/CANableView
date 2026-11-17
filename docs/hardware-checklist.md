# Hardware test checklist

Run once when the CANable 2.0 boards arrive. Tick each box; note failures with the observed behaviour.

## Setup

- Two CANable 2.0 boards, A and B, each on its own USB port.
- Wiring: CANH-CANH, CANL-CANL, GND-GND between A and B.
- 120 ohm termination at each end of the bus: use the termination jumper/solder bridge if your board has one, else a 120 ohm resistor across CANH-CANL. Without it, expect errors or missing frames.
- Find each board's COM port in Device Manager (Ports (COM & LPT)), e.g. COM5 and COM6.
- Firmware: slcan firmware for slcan and FD checks. candleLight firmware (gs_usb) has no CAN FD. Flashing is out of scope; official updater: https://canable.io/updater/
- Start two CANableView instances: instance A on board A, instance B on board B.

## How to send

In the Transmit window:

1. Click **Add row**; fill the columns ID (hex), Ext, FD, BRS, Data (hex bytes), Cycle (ms). Select the row.
2. Click **Arm** (the window title shows "armed"). Nothing is sent until armed; the status bar says "Arm transmit first" otherwise.
3. **Send** sends the selected row once. Set **Cycle (ms)** and click **Start/Stop cyclic** to send periodically; click it again to stop. **Stop all** disarms and stops everything.

Checking results: the Trace window lists received frames; the status bar shows `Rx: N` and `Tx: N`. The Statistics window shows Bus load, Frames/s, Error frames, Unique IDs and an ID / Frames/s table (no per-ID totals).

## 1. slcan classic 500k

Board A and B on slcan firmware.

- [ ] A toolbar: interface `slcan`, channel `COM5`, bitrate 500000, FD off, Connect. Same on B with `COM6`.
- [ ] In A's Transmit window: arm, row ID `123`, Data `11 22 33 44 55 66 77 88`, click Send.
- [ ] B Trace shows one row `0x123` with that data; B status bar `Rx: 1`; A status bar `Tx: 1`.
- [ ] Repeat B to A.
- [ ] On A set Cycle (ms) `10`, Start/Stop cyclic for 10 s, then stop: B status bar `Rx` rose by ~1000, B Statistics shows `0x123` at ~100 Frames/s while running, Error frames 0, no error on the status bar.

## 2. slcan FD 500k / 2M

Board A and B on slcan firmware.

- [ ] Both toolbars: interface `slcan`, bitrate 500000, FD ticked, data bitrate 2000000, Connect.
- [ ] A Transmit: arm, row ID `1ABC`, Ext ticked, FD ticked, BRS ticked, Data of 64 bytes, Send.
- [ ] B Trace shows the FD frame with all 64 bytes and FD/BRS flags.
- [ ] Repeat with BRS unticked.

## 3. gs_usb classic (candleLight firmware)

Flash board A (or both) with candleLight firmware.

- [ ] Toolbar: interface `gs_usb`, channel `0` (device index), bitrate 500000, FD off, Connect.
- [ ] Tick FD and Connect: connection fails with the error "CAN FD over gs_usb not supported" on the status bar. Untick FD again.
- [ ] Send `123` from A (gs_usb) with B on slcan (500k); B Trace shows it. Send B to A; A Trace shows it.

## 4. Cable unplug mid-trace

- [ ] Connect A and B at 500k, send cyclic 10 ms from A.
- [ ] Unplug the USB cable of board B while B is tracing.
- [ ] Within ~1 s B shows a disconnected state and an error on the status bar; the app does not freeze or crash. The Transmit window is disarmed.
- [ ] Replug, press Connect: tracing resumes and the error clears.

## 5. Wrong COM port

- [ ] Toolbar: interface `slcan`, channel `COM99` (nonexistent), Connect.
- [ ] Status bar shows an error; the app stays disconnected and usable.
- [ ] Select a COM port belonging to another device (not a CANable): error or no frames, no hang.

## 6. Logging 10 min at 50 % load

- [ ] Both at 500000 classic. 50 % load is about 4 000 frames/s with 8-byte frames (~125 bits each). Generate it from A (several cyclic rows in the Transmit window, or a second tool); B Statistics Bus load should read ~50 %.
- [ ] On B click Log, choose a `.blf` file, run 10 min. The status bar shows "Logging: <file>".
- [ ] Click Log again to stop. Error frames stays 0, the GUI stayed responsive, and the status bar `Rx` matches the sender's `Tx` (A).
- [ ] Reopen the file with Replay (or `can.LogReader`): frame count matches the sender's count.
