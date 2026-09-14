"""LinkerBot arm SDK, preserving the original linkerbot import paths.

Arm exports are loaded lazily; importing the package does not load Pinocchio.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from .comm import CanInterface
from .exceptions import (
    CANError,
    LinkerbotError,
    StateError,
    TimeoutError,
    ValidationError,
)

if TYPE_CHECKING:  # pragma: no cover - import-time only for static checkers
    from .arm import A7, P7, A7lite, ControlMode, Pose

# Map every lazily-exported public name to (submodule, attribute).
# Adding a new public re-export here is the only change required to surface it
# at the top level without forcing eager import of its subpackage.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "A7": ("linkerbot.arm", "A7"),
    "P7": ("linkerbot.arm", "P7"),
    "A7lite": ("linkerbot.arm", "A7lite"),
    "ControlMode": ("linkerbot.arm", "ControlMode"),
    "Pose": ("linkerbot.arm", "Pose"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'linkerbot' has no attribute {name!r}")
    module_name, attr = target
    value = getattr(importlib.import_module(module_name), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY_EXPORTS})


__all__ = [  # noqa: RUF022 - preserve the original export order
    "LinkerbotError",
    "TimeoutError",
    "CANError",
    "ValidationError",
    "StateError",
    "A7",
    "P7",
    "A7lite",
    "Pose",
    "ControlMode",
    "CanInterface",
]
