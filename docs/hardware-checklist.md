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

Checking results: the Trace window lists received frames; the status bar shows `Rx: N` and `Tx: N`. These are cumulative since app start and are not reset on connect, so note them before a test and compare the increase (delta) afterwards. The Statistics window shows Bus load, Frames/s, Error frames, Unique IDs and an ID / Frames/s table (no per-ID totals).

## 1. slcan classic 500k

Board A and B on slcan firmware.

- [ ] A toolbar: interface `slcan`, channel `COM5`, bitrate 500000, FD off, Connect. Same on B with `COM6`.
- [ ] Note Rx on B and Tx on A (status bars).
- [ ] In A's Transmit window: click Arm, row ID `123`, Data `11 22 33 44 55 66 77 88`, click Send.
- [ ] B Trace shows one row `0x123` with that data; B Rx increased by 1 and A Tx increased by 1.
- [ ] Repeat B to A (in B's Transmit window: Arm, then Send).
- [ ] Note B Rx again. In A's Transmit window (armed) set Cycle (ms) `10` on the row, select it, click Start/Stop cyclic, wait 10 s, then click Start/Stop cyclic again to stop. B Rx increased by ~1000, B Statistics shows `0x123` at ~100 Frames/s while running, Error frames 0, no error on the status bar.

## 2. slcan FD 500k / 2M

Board A and B on slcan firmware.

- [ ] Both toolbars: interface `slcan`, bitrate 500000, FD ticked, data bitrate 2000000, Connect.
- [ ] A Transmit: arm, row ID `1ABC`, Ext ticked, FD ticked, BRS ticked, Data of 64 bytes, Send.
- [ ] B Trace shows the FD frame with all 64 bytes and FD/BRS flags.
- [ ] Untick BRS on the row (A's Transmit window is still armed), click Send; B Trace shows the frame with 64 bytes and FD but no BRS.

## 3. gs_usb classic (candleLight firmware)

Flash board A (or both) with candleLight firmware.

- [ ] Toolbar: interface `gs_usb`, channel `0` (device index), bitrate 500000, FD off, Connect.
- [ ] Tick FD and Connect: connection fails with the error "CAN FD over gs_usb not supported" on the status bar. Untick FD again.
- [ ] With B on slcan (500k): in A's Transmit window click Arm, row ID `123`, Send; B Trace shows it. In B's Transmit window click Arm, Send; A Trace shows it.

## 4. Cable unplug mid-trace

- [ ] Connect A and B at 500k. In A's Transmit window click Arm, set Cycle (ms) `10` on a row, select it, click Start/Stop cyclic.
- [ ] Unplug the USB cable of board B while B is tracing.
- [ ] Within ~1 s B shows a disconnected state and an error on the status bar; the app does not freeze or crash. B's Transmit window is disarmed (B is the instance whose board was unplugged).
- [ ] Replug, press Connect: tracing resumes and the error clears.

## 5. Wrong COM port

- [ ] Toolbar: interface `slcan`, channel `COM99` (nonexistent), Connect.
- [ ] Status bar shows an error; the app stays disconnected and usable.
- [ ] Select a COM port belonging to another device (not a CANable): error or no frames, no hang.

## 6. Logging 10 min at 50 % load

- [ ] Both at 500000 classic, connected. 50 % load is about 4 000 frames/s with 8-byte frames (~125 bits each).
- [ ] Note A Tx and B Rx (status bars).
- [ ] On B click Log and choose a `.blf` file. The status bar shows "Logging: <file>".
- [ ] On A, in the Transmit window click Arm, add several rows with Cycle (ms) set (e.g. 8 rows at 2 ms), select each row in turn and click Start/Stop cyclic (or use a second tool). B Statistics Bus load should read ~50 %. Run 10 min.
- [ ] Stop the sender (A: Stop all), then on B click Log again to stop. Error frames stays 0, the GUI stayed responsive, and the increase in B Rx matches the increase in A Tx.
- [ ] Reopen the file with Replay (or `can.LogReader`): frame count matches the sender's count.
