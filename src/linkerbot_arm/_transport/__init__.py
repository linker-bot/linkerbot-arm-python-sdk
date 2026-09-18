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
    if selection == "dispatcher":
        yield legacy_factory(name, backend, on_bus_error=arm._on_bus_error)
        return
    if selection != "cantransport":
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

    dispatcher = ManagedCANDispatcher(name, backend, model, side, on_error)
    try:
        yield dispatcher
        # A fault during initialization must not be overwritten by _closed=False.
        with lock:
            ready = True
            error = pending
        if error is not None:
            raise CANError(str(error)) from error
    except BaseException:
        _stop_background(arm)
        try:
            dispatcher.stop()
        except Exception:
            logger.exception("Failed to close CANTransport after arm initialization")
        raise


def close_managed_dispatcher(dispatcher):
    """Allow close after a fault; legacy dispatcher semantics remain unchanged."""
    from .can import ManagedCANDispatcher

    if isinstance(dispatcher, ManagedCANDispatcher):
        dispatcher.stop()
