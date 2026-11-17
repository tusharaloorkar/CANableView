"""CAN bus lifecycle, listener fan-out and TX echo."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass
from typing import Callable, Literal

import can
from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)


@dataclass
class BusConfig:
    interface: Literal["slcan", "gs_usb", "virtual"]
    channel: str
    bitrate: int = 500_000
    fd: bool = False
    data_bitrate: int = 2_000_000


class BusManager(QObject):
    connected = Signal()
    disconnected = Signal()
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus: can.BusABC | None = None
        self._notifier: can.Notifier | None = None
        self._listeners: list[Callable[[can.Message], None]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._check_reader)

    @property
    def is_open(self) -> bool:
        return self._bus is not None

    def add_listener(self, fn: Callable[[can.Message], None]) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[can.Message], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def open(self, cfg: BusConfig) -> None:
        if self._bus is not None:
            self.close()
        try:
            bus = self._make_bus(cfg)
        except Exception as exc:  # noqa: BLE001 - any backend failure is reported, never raised
            self.error.emit(str(exc))
            return
        self._bus = bus
        self._notifier = can.Notifier(bus, [self._dispatch], timeout=0.1)  # short: close() joins the reader on the GUI thread
        self._timer.start()
        self.connected.emit()

    @staticmethod
    def _make_bus(cfg: BusConfig) -> can.BusABC:
        if cfg.interface == "virtual":
            return can.Bus(interface="virtual", channel=cfg.channel, receive_own_messages=False)
        if cfg.interface == "slcan":
            bus = can.Bus(interface="slcan", channel=cfg.channel, bitrate=cfg.bitrate)
            if cfg.fd:
                # python-can slcan only takes the data rate via set_bitrate (2M/5M)
                try:
                    bus.set_bitrate(cfg.bitrate, cfg.data_bitrate)
                except Exception:
                    bus.shutdown()
                    raise
            return bus
        if cfg.interface == "gs_usb":
            if cfg.fd:
                raise ValueError("CAN FD over gs_usb not supported by installed python-can")
            return can.Bus(interface="gs_usb", channel=int(cfg.channel), bitrate=cfg.bitrate)
        raise ValueError(f"unknown interface {cfg.interface!r}")

    def close(self) -> None:
        self._timer.stop()
        notifier, bus = self._notifier, self._bus
        self._notifier = self._bus = None
        if notifier is not None:
            notifier.stop()
        if bus is not None:
            bus.shutdown()

    def _check_reader(self) -> None:
        if self._notifier is None or self._notifier.exception is None:
            return
        exc = self._notifier.exception
        self.close()
        self.error.emit(str(exc))
        self.disconnected.emit()

    def _dispatch(self, msg: can.Message) -> None:
        for fn in list(self._listeners):
            try:
                fn(msg)
            except Exception:  # noqa: BLE001
                log.exception("listener failed")

    def _echo(self, msg: can.Message) -> None:
        tx = copy.copy(msg)
        tx.is_rx = False
        tx.timestamp = time.time()
        self._dispatch(tx)

    def send(self, msg: can.Message) -> bool:
        if self._bus is None:
            return False
        try:
            self._bus.send(msg)
        except can.CanError as exc:
            self.error.emit(str(exc))
            return False
        self._echo(msg)
        return True

    def send_periodic(self, msg: can.Message, period_s: float):
        if self._bus is None:
            return None
        try:
            return self._bus.send_periodic(msg, period_s, modifier_callback=self._echo)
        except can.CanError as exc:
            self.error.emit(str(exc))
            return None
