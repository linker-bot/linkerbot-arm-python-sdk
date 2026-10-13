"""Internal backend selection; the public arm constructors stay unchanged."""

import logging
import os
import threading
from contextlib import contextmanager

from linkerbot_arm.exceptions import CANError, StateError, ValidationError

logger = logging.getLogger(__name__)
_close_lock_guard = threading.Lock()


def _stop_background(arm):
    timer = getattr(arm, "_motion_timer", None)
    if timer is not None:
        timer.cancel()
    for motor in getattr(arm, "_motors", ()):
        stop = getattr(motor, "stop_polling", None)
        if stop is not None:
            try:
                stop()
            except Exception:
                logger.exception("Failed to stop motor polling during fault cleanup")
    if hasattr(arm, "_polling"):
        arm._polling = False


@contextmanager
def arm_dispatcher(arm, model, side, name, backend, legacy_factory):
    selection = os.environ.get("LINKERBOT_ARM_TRANSPORT", "cantransport")
    if selection not in ("dispatcher", "cantransport"):
        raise ValidationError(
            "LINKERBOT_ARM_TRANSPORT must be 'dispatcher' or 'cantransport'"
        )

    from .can import ManagedCANDispatcher

    ready = False
    pending = None
    lock = threading.Lock()

    def on_error(error):
        nonlocal pending
        with lock:
            pending = error
            initialized = ready
        if initialized:
            try:
                arm._on_bus_error(error)
            finally:
                _stop_background(arm)

    arm._resources_closed = False
    arm._closing = False
    arm._connection_close_lock = threading.Lock()
    dispatcher = (
        legacy_factory(name, backend, on_bus_error=on_error)
        if selection == "dispatcher"
        else ManagedCANDispatcher(name, backend, model, side, on_error)
    )
    try:
        yield dispatcher
        # A fault during initialization must not be overwritten by _closed=False.
        with lock:
            ready = True
            error = pending
        if error is not None:
            raise CANError(str(error)) from error
    except BaseException:
        arm._closed = True
        _stop_background(arm)
        try:
            dispatcher.stop()
        except BaseException:
            logger.exception("Failed to close CAN connection after arm initialization")
        else:
            arm._resources_closed = True
        raise


def _finish_cancelled_worker(timer):
    """Defer repeated process interrupts until the worker releases its resources."""
    while True:
        try:
            timer.cancel()
            timer._wait_worker_done()
            return
        except (KeyboardInterrupt, SystemExit):
            # The closer propagates its original exception after cleanup.
            # Re-enter this wait without marking the arm closed or releasing CAN.
            continue


def close_arm(arm):
    """Close either backend; a faulted arm can still own live CAN resources.

    Normal close waits for motion as before. Even when waiting is interrupted,
    attempt connection cleanup, preserving the original exception. A failed
    physical close remains retryable and must never look successful.
    Repeated interrupts while awaiting cancelled workers are deferred until
    restoration finishes; they must not release the worker's CAN connection.
    """
    from linkerbot_transport.errors import TransportError

    timer = getattr(arm, "_motion_timer", None)
    if timer is not None and timer._is_worker_thread():
        raise StateError("Cannot close an arm from its active motion worker")
    with _close_lock_guard:
        lock = getattr(arm, "_connection_close_lock", None)
        if lock is None:
            lock = arm._connection_close_lock = threading.Lock()
    with lock:
        if getattr(arm, "_resources_closed", False):
            return
        was_closed = getattr(arm, "_closed", False)
        active_worker = False
        if timer is not None:
            with timer._lock:
                arm._closing = True
                timer._closing = True
                active_worker = not timer._worker_done.is_set()
        primary = None
        try:
            if timer is not None:
                timer._wait_worker_done(report_error=active_worker)
            if not was_closed:
                arm.wait_motion_done()
        except BaseException as error:
            primary = error
            if timer is not None:
                # Cancellation wakes the motion event before restoration exits.
                _finish_cancelled_worker(timer)
        finally:
            arm._closed = True
            if timer is not None:
                timer.cancel()
            stop_polling = getattr(arm, "stop_polling", None)
            if stop_polling is not None:
                try:
                    stop_polling()
                except BaseException as error:
                    if primary is None:
                        primary = error
                    else:
                        logger.exception("Polling cleanup also failed")
            try:
                arm._can_dispatcher.stop()
            except BaseException as error:
                if primary is not None:
                    logger.exception("CAN cleanup also failed; close() can be retried")
                elif isinstance(error, TransportError):
                    raise CANError(str(error)) from error
                else:
                    raise
            else:
                arm._resources_closed = True
        if primary is not None:
            raise primary


def exit_arm(arm, body_error):
    """Do not replace an application error with a secondary close failure."""
    try:
        arm.close()
    except BaseException:
        if body_error is None:
            raise
        logger.exception("CAN cleanup failed while handling application error")
    return False
