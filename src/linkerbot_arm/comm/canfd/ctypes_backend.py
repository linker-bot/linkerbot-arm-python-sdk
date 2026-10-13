"""Legacy vendor API backed by transport's shared loader and CAN FD I/O.

Only model and exception conversion live here. Library handles, Init/Exit
reference counts, buffers, calls and retryable cleanup belong to transport
and are shared with hand.
"""

import threading
from pathlib import Path

from linkerbot_transport.canfd import ctypes_backend as _backend
from linkerbot_transport.canfd.ctypes_backend import (
    CANFD_DEFAULT_MAX_RECEIVE_FRAMES,
    CANFD_DEFAULT_RECEIVE_TIMEOUT_MS,
    CANFD_DEFAULT_SEND_TIMEOUT_MS,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CANFD_EXTENDED_FRAME_FLAG as CANFD_EXTENDED_FRAME_FLAG,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CANFD_FRAME_DATA_SIZE as CANFD_FRAME_DATA_SIZE,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CANFD_REMOTE_FRAME_DISABLED as CANFD_REMOTE_FRAME_DISABLED,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CANFD_SCAN_NO_DEVICE as CANFD_SCAN_NO_DEVICE,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CANFD_STANDARD_FRAME_FLAG as CANFD_STANDARD_FRAME_FLAG,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CANFD_STATUS_OK as CANFD_STATUS_OK,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CANFD_TRANSMIT_FRAME_COUNT as CANFD_TRANSMIT_FRAME_COUNT,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CANFD_TRANSMIT_MAX_BATCH as CANFD_TRANSMIT_MAX_BATCH,
)
from linkerbot_transport.canfd.ctypes_backend import (
    Any as Any,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CanFDConfig as CanFDConfig,
)
from linkerbot_transport.canfd.ctypes_backend import (
    CanFDMsg as CanFDMsg,
)
from linkerbot_transport.canfd.ctypes_backend import (
    DevInfo as DevInfo,
)
from linkerbot_transport.canfd.ctypes_backend import (
    atexit as atexit,
)
from linkerbot_transport.canfd.ctypes_backend import (
    ctypes as ctypes,
)
from linkerbot_transport.canfd.ctypes_backend import (
    logging as logging,
)
from linkerbot_transport.canfd.ctypes_backend import (
    os as os,
)
from linkerbot_transport.canfd.ctypes_backend import (
    platform as platform,
)

from linkerbot_arm.exceptions import CANError as CANError
from linkerbot_arm.exceptions import ValidationError as ValidationError

from ._compat import adapt_errors, arm_errors
from .types import CANFDConfigOptions, CANFDMessage
from .types import dlc_to_length as dlc_to_length


class CANFDInterface(_backend.CANFDInterface):
    """Retain arm configuration, messages and errors over transport I/O."""

    def __init__(
        self,
        device_index: int = 0,
        channel_index: int = 0,
        library_path: str | Path | None = None,
        config: CANFDConfigOptions | None = None,
    ) -> None:
        with arm_errors():
            super().__init__(
                device_index,
                channel_index,
                library_path,
                config or CANFDConfigOptions(),
            )

    _open = adapt_errors(_backend.CANFDInterface._open)
    _ensure_open = adapt_errors(_backend.CANFDInterface._ensure_open)

    @property
    def config(self) -> CANFDConfigOptions:
        return self._config

    def send(
        self, message: CANFDMessage, timeout_ms: int = CANFD_DEFAULT_SEND_TIMEOUT_MS
    ) -> None:
        with arm_errors():
            super().send(message, timeout_ms)

    def send_batch(
        self,
        messages: list[CANFDMessage],
        timeout_ms: int = CANFD_DEFAULT_SEND_TIMEOUT_MS,
    ) -> None:
        with arm_errors():
            super().send_batch(messages, timeout_ms)

    def receive(
        self,
        max_frames: int = CANFD_DEFAULT_MAX_RECEIVE_FRAMES,
        timeout_ms: int = CANFD_DEFAULT_RECEIVE_TIMEOUT_MS,
    ) -> list[CANFDMessage]:
        with arm_errors():
            return super().receive(max_frames, timeout_ms)

    def read_dev_info(self) -> dict[str, str]:
        with arm_errors():
            return super().read_dev_info()

    def _frame_to_message(self, frame: CanFDMsg) -> CANFDMessage:
        with arm_errors():
            message = super()._frame_to_message(frame)
        return CANFDMessage(
            message.arbitration_id,
            message.data,
            message.dlc,
            message.is_extended_id,
            message.frame_type,
            message.timestamp,
        )

    def close(self) -> None:
        """Preserve arm errors while transport retains failed cleanup for retry."""
        with arm_errors():
            super().close()


def __getattr__(name):
    # Preserve deep helper/constant imports without copying the shared loader.
    value = getattr(_backend, name)
    if callable(value) and not isinstance(value, type):
        return adapt_errors(value)
    return value


# Preserve the pre-cleanup deep-module star imports as well as explicit imports.
__all__ = [
    "Any",
    "CANError",
    "CANFDConfigOptions",
    "CANFDInterface",
    "CANFDMessage",
    "CANFD_DEFAULT_MAX_RECEIVE_FRAMES",
    "CANFD_DEFAULT_RECEIVE_TIMEOUT_MS",
    "CANFD_DEFAULT_SEND_TIMEOUT_MS",
    "CANFD_EXTENDED_FRAME_FLAG",
    "CANFD_FRAME_DATA_SIZE",
    "CANFD_REMOTE_FRAME_DISABLED",
    "CANFD_SCAN_NO_DEVICE",
    "CANFD_STANDARD_FRAME_FLAG",
    "CANFD_STATUS_OK",
    "CANFD_TRANSMIT_FRAME_COUNT",
    "CANFD_TRANSMIT_MAX_BATCH",
    "CanFDConfig",
    "CanFDMsg",
    "DevInfo",
    "Path",
    "ValidationError",
    "atexit",
    "ctypes",
    "dlc_to_length",
    "logging",
    "os",
    "platform",
    "threading",
]
