"""Guard the pre-migration public and integration API surface."""

from __future__ import annotations

import inspect
import json
from enum import Enum
from pathlib import Path

from linkerbot_arm import A7, P7, A7lite, ControlMode, Pose
from linkerbot_arm.arm import State, WayPoint
from linkerbot_arm.arm.a7.motor import A7Motor
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from linkerbot_arm.comm.can import CanInterface, CANMessageDispatcher
from linkerbot_arm.exceptions import (
    CANError,
    LinkerbotError,
    StateError,
    TimeoutError,
    ValidationError,
)


def _signature(obj):
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return None


SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures/api_surface_snapshot.json").read_text()
)

_CLASSES = {
    "linkerbot_arm.A7": A7,
    "linkerbot_arm.A7lite": A7lite,
    "linkerbot_arm.P7": P7,
    "linkerbot_arm.arm.Pose": Pose,
    "linkerbot_arm.arm.State": State,
    "linkerbot_arm.arm.WayPoint": WayPoint,
    "linkerbot_arm.arm.ControlMode": ControlMode,
    "linkerbot_arm.arm.a7.motor.A7Motor": A7Motor,
    "linkerbot_arm.arm.p7.motor_v2.MotorV2": MotorV2,
    "linkerbot_arm.comm.can.CANMessageDispatcher": CANMessageDispatcher,
    "linkerbot_arm.comm.can.CanInterface": CanInterface,
    "linkerbot_arm.exceptions.LinkerbotError": LinkerbotError,
    "linkerbot_arm.exceptions.TimeoutError": TimeoutError,
    "linkerbot_arm.exceptions.CANError": CANError,
    "linkerbot_arm.exceptions.ValidationError": ValidationError,
    "linkerbot_arm.exceptions.StateError": StateError,
}


def test_pre_migration_api_snapshot_is_current() -> None:
    for path, cls in _CLASSES.items():
        expected = SNAPSHOT["classes"][path]
        assert cls.__module__ == expected["module"]
        assert cls.__qualname__ == expected["qualname"]
        if issubclass(cls, Enum):
            # Enum's generated constructor differs between Python versions.
            # The SDK contract is the declared member names and values.
            members = {name: member.value for name, member in cls.__members__.items()}
            assert members == expected["members"]
            # Generated Enum internals vary too; source-defined methods are
            # covered by tests/compat/test_api.py against the upstream snapshot.
            continue
        assert _signature(cls) == expected["signature"]
        methods = {
            name: _signature(obj)
            for name, obj in cls.__dict__.items()
            if (callable(obj) and (not name.startswith("__") or name == "__init__"))
        }
        assert methods == expected["methods"]
