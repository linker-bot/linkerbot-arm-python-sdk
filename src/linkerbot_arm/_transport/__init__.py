"""Internal backend selection; the public arm constructors stay unchanged."""

import logging
import os
import threading
from contextlib import contextmanager

from linkerbot_arm.exceptions import CANError, ValidationError

logger = logging.getLogger(__name__)


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


def close_arm(arm):
    """Close either backend; a faulted arm can still own live CAN resources.

    Normal close waits for motion as before. Even when waiting is interrupted,
    attempt connection cleanup, preserving the original exception. A failed
    physical close remains retryable and must never look successful.
    """
    from linkerbot_transport.errors import TransportError

    if getattr(arm, "_resources_closed", False):
        return
    was_closed = getattr(arm, "_closed", False)
    arm._closed = True
    primary = None
    try:
        stop_polling = getattr(arm, "stop_polling", None)
        if stop_polling is not None:
            stop_polling()
        if not was_closed:
            arm.wait_motion_done()
    except BaseException as error:
        primary = error
    finally:
        timer = getattr(arm, "_motion_timer", None)
        if timer is not None:
            timer.cancel()
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
