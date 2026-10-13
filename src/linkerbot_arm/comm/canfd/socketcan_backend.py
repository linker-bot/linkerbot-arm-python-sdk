"""SocketCAN FD compatibility API; transport owns link setup and frame I/O."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading

import can
from linkerbot_transport.canfd import python_can_backend as _python_backend
from linkerbot_transport.canfd import socketcan_backend as _backend
from linkerbot_transport.canfd.socketcan_backend import (
    CANFD_DEFAULT_DATA_BAUD as CANFD_DEFAULT_DATA_BAUD,
)
from linkerbot_transport.canfd.socketcan_backend import (
    CANFD_DEFAULT_NOMINAL_BAUD as CANFD_DEFAULT_NOMINAL_BAUD,
)
from linkerbot_transport.canfd.socketcan_backend import (
    DEFAULT_DATA_BITRATE,
    DEFAULT_NOMINAL_BITRATE,
)

from linkerbot_arm.exceptions import CANError as CANError
from linkerbot_arm.exceptions import ValidationError as ValidationError

from ._compat import adapt_errors, arm_errors
from .types import CANFDMessage
from .types import dlc_to_length as dlc_to_length
from .types import length_to_dlc as length_to_dlc


class SocketCANFDBackend(_backend.SocketCANFDBackend):
    """Preserve arm errors, message types and retryable best-effort shutdown."""

    def __init__(
        self,
        channel: str,
        *,
        bitrate: int = DEFAULT_NOMINAL_BITRATE,
        data_bitrate: int = DEFAULT_DATA_BITRATE,
        fd: bool = True,
        auto_reconfigure: bool = False,
        receive_own_messages: bool = False,
    ) -> None:
        self._compat_close_lock = threading.Lock()
        self._compat_closed = False
        with arm_errors():
            super().__init__(
                channel,
                bitrate=bitrate,
                data_bitrate=data_bitrate,
                fd=fd,
                auto_reconfigure=auto_reconfigure,
                receive_own_messages=receive_own_messages,
            )

    _ensure_link_state = adapt_errors(_backend.SocketCANFDBackend._ensure_link_state)

    def send(self, message: CANFDMessage, timeout_ms: int = 10) -> None:
        if self._compat_closed:
            raise CANError("SocketCAN FD backend is closed")
        with arm_errors():
            super().send(message, timeout_ms)

    def receive(self, max_frames: int = 64, timeout_ms: int = 10) -> list[CANFDMessage]:
        if self._compat_closed:
            raise CANError("SocketCAN FD backend is closed")
        with arm_errors():
            messages = super().receive(max_frames, timeout_ms)
        return [_arm_message(message) for message in messages]

    def close(self) -> None:
        # Stop arm I/O immediately, but let transport retain a failed handle
        # and its channel claim until a later close successfully releases them.
        with self._compat_close_lock:
            self._compat_closed = True
            try:
                super().close()
            except Exception as error:
                logging.getLogger(__name__).warning(
                    "SocketCAN FD shutdown failed; close can be retried: %s", error
                )


def _arm_message(message) -> CANFDMessage:
    return CANFDMessage(
        message.arbitration_id,
        message.data,
        message.dlc,
        message.is_extended_id,
        message.frame_type,
        message.timestamp,
    )


def _to_canfd_message(msg: can.Message) -> CANFDMessage:
    with arm_errors():
        return _arm_message(_python_backend._to_canfd_message(msg))


def __getattr__(name):
    value = getattr(_backend, name)
    if callable(value) and not isinstance(value, type):
        return adapt_errors(value)
    return value


# Preserve the pre-cleanup deep-module star imports as well as explicit imports.
__all__ = [
    "CANError",
    "CANFDMessage",
    "CANFD_DEFAULT_DATA_BAUD",
    "CANFD_DEFAULT_NOMINAL_BAUD",
    "DEFAULT_DATA_BITRATE",
    "DEFAULT_NOMINAL_BITRATE",
    "SocketCANFDBackend",
    "ValidationError",
    "annotations",
    "can",
    "dlc_to_length",
    "json",
    "length_to_dlc",
    "shutil",
    "subprocess",
    "threading",
]
