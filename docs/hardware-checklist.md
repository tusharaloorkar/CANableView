# Hardware test checklist

Run once when the CANable 2.0 boards arrive. Tick each box; note failures with the observed behaviour.

## Setup

- Two CANable 2.0 boards, A and B, each on its own USB port.
- Wiring: CANH-CANH, CANL-CANL, GND-GND between A and B.
- 120 ohm termination at each end of the bus: enable the termination jumper/switch on both boards. Without it, expect errors or missing frames.
- Find each board's COM port in Device Manager (Ports (COM & LPT)), e.g. COM5 and COM6.
- Firmware: slcan firmware for slcan and FD checks. candleLight firmware (gs_usb) has no CAN FD. Flashing is out of scope; official updater: https://canable.io/updater/
- Start two CANableView instances: instance A on board A, instance B on board B.

## 1. slcan classic 500k

Board A and B on slcan firmware.

- [ ] A toolbar: interface `slcan`, channel `COM5`, bitrate 500000, FD off, Connect. Same on B with `COM6`.
- [ ] In A's Transmit window send ID `0x123`, DLC 8, data `11 22 33 44 55 66 77 88`.
- [ ] B Trace shows one row `0x123` with that data. Statistics in B shows `0x123` count 1.
- [ ] Repeat B to A.
- [ ] Send periodic at 10 ms from A for 10 s: B Statistics shows ~1000 frames, no gaps in count, no error on status bar.

## 2. slcan FD 500k / 2M

Board A and B on slcan firmware.

- [ ] Both toolbars: interface `slcan`, bitrate 500000, FD on, data bitrate 2000000, Connect.
- [ ] A Transmit: FD frame, BRS on, ID `0x1ABC`, 64 data bytes.
- [ ] B Trace shows the FD frame with the FD/BRS flags and all 64 bytes.
- [ ] Repeat with BRS off.

## 3. gs_usb classic (candleLight firmware)

Flash board A (or both) with candleLight firmware.

- [ ] Toolbar: interface `gs_usb`, channel `0` (device index), bitrate 500000, FD off, Connect.
- [ ] The FD checkbox is not usable or connect fails with a clear error (candleLight has no FD).
- [ ] Send `0x123` from A (gs_usb) with B on slcan (500k); B Trace shows it. Send B to A; A Trace shows it.

## 4. Cable unplug mid-trace

- [ ] Connect A and B at 500k, send periodic 10 ms from A.
- [ ] Unplug the USB cable of board B while B is tracing.
- [ ] Within ~1 s B shows a disconnected state and an error on the status bar; the app does not freeze or crash. Toolbar button returns to Connect.
- [ ] Replug, press Connect: tracing resumes and the error clears.

## 5. Wrong COM port

- [ ] Toolbar: interface `slcan`, channel `COM99` (nonexistent), Connect.
- [ ] Status bar shows an error; the app stays disconnected and usable.
- [ ] Select a COM port belonging to another device (not a CANable): error or no frames, no hang.

## 6. Logging 10 min at 50 % load

- [ ] Both at 500000 classic. 50 % load is about 4 000 fps with 8-byte frames (~125 bits each). Send from A with the Transmit window, or a second tool at that rate.
- [ ] On B press Log, choose a `.blf` file, run 10 min.
- [ ] Stop logging. Statistics shows no dropped/error counters and the GUI stayed responsive throughout.
- [ ] Reopen the file with Replay (or `python -m can.logger`/`can.LogReader`): frame count matches the sender's count.
