"""Preserve host reception time through the single-message callback contract."""

import threading
import time
from contextlib import contextmanager

_reception = threading.local()


@contextmanager
def reception_time(received_at_s):
    previous = getattr(_reception, "received_at_s", None)
    _reception.received_at_s = received_at_s
    try:
        yield
    finally:
        _reception.received_at_s = previous


def feedback_received_at():
    """Use original reception time, or now for direct decoder invocations."""
    received = getattr(_reception, "received_at_s", None)
    return time.monotonic() if received is None else received
