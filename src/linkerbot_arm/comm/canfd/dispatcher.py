"""Arm CAN FD call compatibility over transport's workers and send queue.

Keep the original Future[None], arm exceptions and bounded best-effort stop.
Transport performs all frame dispatch, batching, receive and send operations.
"""

import threading
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path

from linkerbot_transport.canfd import dispatcher as _dispatcher
from linkerbot_transport.canfd.dispatcher import (
    DEFAULT_MAX_CONSECUTIVE_ERRORS,
    THREAD_JOIN_TIMEOUT_S,
    _QueuedSend,
)
from linkerbot_transport.canfd.dispatcher import (
    ERROR_BACKOFF_BASE_S as ERROR_BACKOFF_BASE_S,
)
from linkerbot_transport.canfd.dispatcher import (
    ERROR_BACKOFF_MAX_S as ERROR_BACKOFF_MAX_S,
)
from linkerbot_transport.canfd.dispatcher import (
    RECEIVE_BATCH_SIZE as RECEIVE_BATCH_SIZE,
)
from linkerbot_transport.canfd.dispatcher import (
    RECEIVE_TIMEOUT_MS as RECEIVE_TIMEOUT_MS,
)
from linkerbot_transport.canfd.dispatcher import (
    SEND_QUEUE_GET_TIMEOUT_S as SEND_QUEUE_GET_TIMEOUT_S,
)
from linkerbot_transport.canfd.dispatcher import (
    dataclass as dataclass,
)
from linkerbot_transport.canfd.dispatcher import (
    logging as logging,
)
from linkerbot_transport.canfd.dispatcher import (
    queue as queue,
)
from linkerbot_transport.canfd.dispatcher import (
    time as time,
)
from linkerbot_transport.errors import TransportError

from linkerbot_arm.exceptions import CANError, StateError, ValidationError

from .ctypes_backend import CANFDInterface
from .types import CANFDBackend, CANFDConfigOptions, CANFDMessage


class _PreservedFailure(BaseException):
    def __init__(self, error: BaseException) -> None:
        self.error = error


class CANFDSendReceipt(Future[None]):
    """Original, non-cancellable queued-send Future with transport tracker hooks."""

    def _dispatch(self) -> None:
        self.set_result(None)

    def _fail(self, error: BaseException) -> None:
        if isinstance(error, _PreservedFailure):
            error = error.error
        elif not isinstance(error, CANError):
            if isinstance(error, TransportError):
                mapped = CANError(*error.args)
                mapped.__cause__ = error.__cause__ or error.cause or error
                error = mapped
            else:
                error = _send_error(error, "CANFD background send failed")
        self.set_exception(error)


class CANFDMessageDispatcher(_dispatcher.CANFDMessageDispatcher):
    """Delegate workers while preserving the existing arm dispatcher API."""

    def __init__(
        self,
        device_index: int = 0,
        channel_index: int = 0,
        library_path: str | Path | None = None,
        config: CANFDConfigOptions | None = None,
        on_bus_error: Callable[[Exception], None] | None = None,
        max_consecutive_errors: int = DEFAULT_MAX_CONSECUTIVE_ERRORS,
        interface: CANFDBackend | None = None,
    ) -> None:
        if (
            not isinstance(max_consecutive_errors, int)
            or isinstance(max_consecutive_errors, bool)
            or max_consecutive_errors <= 0
        ):
            raise ValidationError("max_consecutive_errors must be a positive int")
        if interface is None:
            interface = CANFDInterface(
                device_index,
                channel_index,
                library_path,
                config,
            )
        super().__init__(
            device_index,
            channel_index,
            library_path,
            config,
            on_bus_error,
            max_consecutive_errors,
            interface,
        )

    def send(self, message: CANFDMessage) -> CANFDSendReceipt:
        """Enqueue a frame and return its physical-transmission receipt.

        Queue acceptance is not physical send success. Call ``result()`` on
        the returned receipt when the caller must observe backend failures.
        """
        receipt = CANFDSendReceipt()
        with self._error_lock:
            if self._bus_error is not None:
                raise CANError(f"CANFD bus unavailable: {self._bus_error}")
            if not self._running:
                raise RuntimeError("Cannot send on a stopped CANFDMessageDispatcher")
            self._register_receipt(receipt)
            try:
                self._send_queue.put_nowait(_QueuedSend(message, receipt))
            except BaseException:
                self._discard_receipt(receipt)
                raise
        return receipt

    def stop(self) -> None:
        """Stop dispatcher threads and close the CANFD interface.

        Strict ordering to honour the interface's close contract:

        1. Flip ``_error_reported`` and ``_running`` so both worker threads
           observe the shutdown signal on their next iteration.
        2. Join send_thread first (it polls the queue at 10 ms granularity).
        3. Join recv_thread (worst case ~10 ms for vendor receive timeout).
        4. Only then call ``interface.close()`` — by now no worker thread is
           touching the vendor library, so close()'s drain step is uncontended.
        5. Clear subscribers under their own lock.

        If ``stop()`` is invoked from inside a dispatcher-managed callback,
        the calling thread is skipped to avoid join-self deadlock.
        """
        with self._error_lock:
            self._error_reported = True
            self._running = False
        self._fail_all_receipts(
            StateError("CANFD dispatcher stopped before queued send completed")
        )
        current = threading.current_thread()
        for thread in (self._send_thread, self._recv_thread):
            if thread is current:
                continue
            if thread.is_alive():
                thread.join(timeout=THREAD_JOIN_TIMEOUT_S)
                if thread.is_alive():
                    self._logger.warning(
                        "%s did not stop within %.1fs",
                        thread.name,
                        THREAD_JOIN_TIMEOUT_S,
                    )
                    return
        with self._close_lock:
            if not self._interface_closed:
                self._interface_closed = True
                try:
                    self._interface.close()
                except Exception as error:
                    # Surface as warning rather than swallow silently; the SDK has
                    # already accepted the shutdown so we don't propagate the error.
                    self._logger.warning("CANFD interface close failed: %s", error)
        with self._subscribers_lock:
            self._subscribers.clear()
            self._filtered_subscribers.clear()

    def _handle_bus_error(self, error: Exception) -> None:
        with self._error_lock:
            if self._error_reported:
                return
            self._error_reported = True
            self._running = False
            self._bus_error = error
        self._fail_all_receipts(_send_error(error, "CANFD bus unavailable"))
        self._logger.error(f"CANFD bus fatal error, stopping dispatcher: {error}")
        if self._on_bus_error is not None:
            try:
                self._on_bus_error(error)
            except Exception as callback_error:
                self._logger.error(f"Error in on_bus_error callback: {callback_error}")

    def _register_receipt(self, receipt: CANFDSendReceipt) -> None:
        receipt.set_running_or_notify_cancel()
        self._receipts.register(receipt)

    def _discard_receipt(self, receipt: CANFDSendReceipt) -> None:
        self._receipts.discard(receipt)

    def _complete_receipt(self, receipt: CANFDSendReceipt) -> None:
        self._receipts.succeed(receipt)

    def _fail_receipt(self, receipt: CANFDSendReceipt, error: BaseException) -> None:
        self._receipts.fail(receipt, _PreservedFailure(error))

    def _take_receipt(self, receipt: CANFDSendReceipt) -> bool:
        return self._receipts._take(receipt)

    def _fail_all_receipts(self, error: BaseException) -> None:
        self._receipts.fail_all(_PreservedFailure(error))


def _send_error(error: BaseException, operation: str) -> CANError:
    if isinstance(error, CANError):
        return error
    wrapped = CANError(f"{operation}: {error}")
    wrapped.__cause__ = error
    return wrapped


def __getattr__(name):
    return getattr(_dispatcher, name)


# Preserve the pre-cleanup deep-module star imports as well as explicit imports.
__all__ = [
    "CANError",
    "CANFDBackend",
    "CANFDConfigOptions",
    "CANFDInterface",
    "CANFDMessage",
    "CANFDMessageDispatcher",
    "CANFDSendReceipt",
    "Callable",
    "DEFAULT_MAX_CONSECUTIVE_ERRORS",
    "ERROR_BACKOFF_BASE_S",
    "ERROR_BACKOFF_MAX_S",
    "Future",
    "Path",
    "RECEIVE_BATCH_SIZE",
    "RECEIVE_TIMEOUT_MS",
    "SEND_QUEUE_GET_TIMEOUT_S",
    "StateError",
    "THREAD_JOIN_TIMEOUT_S",
    "ValidationError",
    "dataclass",
    "logging",
    "queue",
    "threading",
    "time",
]
