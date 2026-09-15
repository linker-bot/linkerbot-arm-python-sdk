"""Compatibility boundary over the low-level Transport 1.x dispatcher.

The transport owns CAN I/O, queues and worker threads. This adapter keeps the
arm SDK's legacy send return value and exception categories; it deliberately
does not use CANTransport, send_now or receipt waits.
"""

import logging
import queue
import threading
from collections.abc import Callable

import can
from linkerbot_transport.can.can import (
    DEFAULT_MAX_CONSECUTIVE_ERRORS as DEFAULT_MAX_CONSECUTIVE_ERRORS,
)
from linkerbot_transport.can.can import (
    ERROR_BACKOFF_BASE_S as ERROR_BACKOFF_BASE_S,
)
from linkerbot_transport.can.can import (
    ERROR_BACKOFF_MAX_S as ERROR_BACKOFF_MAX_S,
)
from linkerbot_transport.can.can import (
    THREAD_JOIN_TIMEOUT_S as THREAD_JOIN_TIMEOUT_S,
)
from linkerbot_transport.can.can import (
    CANMessageDispatcher as _TransportDispatcher,
)
from linkerbot_transport.can.can import (
    _error_backoff_s as _error_backoff_s,
)
from linkerbot_transport.errors import (
    LinkerbotError as _TransportErrorBase,
)
from linkerbot_transport.errors import (
    QueueFullError,
    TransportError,
)
from linkerbot_transport.errors import (
    ValidationError as _TransportValidationError,
)

from linkerbot_arm.exceptions import CANError, ValidationError

from .types import CanInterface as CanInterface

logger = logging.getLogger(__name__)


class CANMessageDispatcher(_TransportDispatcher):
    """Use transport workers while retaining the arm dispatcher call contract."""

    def __init__(
        self,
        interface_name: str,
        interface_type: str = "socketcan",
        on_bus_error: Callable[[Exception], None] | None = None,
        max_consecutive_errors: int = DEFAULT_MAX_CONSECUTIVE_ERRORS,
    ) -> None:
        self._compat_shutdown_lock = threading.Lock()
        try:
            super().__init__(
                interface_name,
                interface_type,
                on_bus_error=on_bus_error,
                max_consecutive_errors=max_consecutive_errors,
            )
        except _TransportValidationError as error:
            raise ValidationError(*error.args) from error

    def send(self, msg: can.Message) -> None:
        """Enqueue without waiting; preserve None, CANError and queue.Full."""
        try:
            super().send(msg)
        except QueueFullError as error:
            raise queue.Full() from error
        except TransportError as error:
            raise CANError(*error.args) from error

    def _shutdown_bus(self) -> _TransportErrorBase | None:
        """Keep legacy log-and-finish policy even for concurrent stop calls."""
        with self._compat_shutdown_lock:
            error = super()._shutdown_bus()
            if error is not None:
                logger.warning("CAN bus shutdown failed: %s", error)
                with self._shutdown_lock:
                    self._shutdown_complete = True
        # stop() and all worker joins stay in transport. A stopped worker may
        # still need joining after a stop initiated inside a receive callback.
        return None
