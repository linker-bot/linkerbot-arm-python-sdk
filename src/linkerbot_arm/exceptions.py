"""Arm exception names with transport categories and legacy constructors.

The arm classes remain distinct so existing imports, catches and pickling keep
working. Multiple positional exception arguments remain supported, unlike the
transport's message/cause constructor. The dispatcher adapts transport errors
at the arm boundary instead of requiring users to catch a new exception type.
"""

import builtins

from linkerbot_transport import errors as _errors


class LinkerbotError(_errors.LinkerbotError):
    """Base exception for arm errors; accepts the original Exception arguments."""

    def __init__(self, *args) -> None:
        Exception.__init__(self, *args)
        self.cause = None


class TimeoutError(LinkerbotError, _errors.TimeoutError):
    """Raised when an arm response does not arrive within the timeout."""

    def __init__(self, *args) -> None:
        # The original arm TimeoutError already inherited builtins.TimeoutError.
        # Preserve its errno/strerror/filename handling for positional calls.
        builtins.TimeoutError.__init__(self, *args)
        self.cause = None


class CANError(LinkerbotError, _errors.TransportError):
    """Raised for CAN communication errors at the arm boundary."""


class ValidationError(LinkerbotError, _errors.ValidationError):
    """Raised when arm input validation fails."""


class StateError(LinkerbotError, _errors.DeviceStateError):
    """Raised when the arm is not in a state allowing the operation."""
