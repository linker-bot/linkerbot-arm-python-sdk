"""Translate transport failures without changing its process-global classes."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import ParamSpec, TypeVar

from linkerbot_transport.errors import TransportError
from linkerbot_transport.errors import ValidationError as TransportValidationError

from linkerbot_arm.exceptions import CANError, LinkerbotError, ValidationError

_P = ParamSpec("_P")
_R = TypeVar("_R")


@contextmanager
def arm_errors() -> Iterator[None]:
    try:
        yield
    except LinkerbotError:
        raise
    except TransportValidationError as error:
        raise ValidationError(*error.args) from error
    except TransportError as error:
        raise CANError(*error.args) from error


def adapt_errors(function: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(function)
    def call(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with arm_errors():
            return function(*args, **kwargs)

    return call
