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
        module = expected["module"]
        if cls is CanInterface:
            # The frozen dataclass is now re-exported from transport.
            module = "linkerbot_transport.can.types"
        assert cls.__module__ == module
        assert cls.__qualname__ == expected["qualname"]
        if issubclass(cls, Enum):
            # Enum's generated constructor differs between Python versions.
            # The SDK contract is the declared member names and values.
            members = {name: member.value for name, member in cls.__members__.items()}
            additions = {"MIT": 2, "CSP": 3} if cls is ControlMode else {}
            assert members == expected["members"] | additions
            # Generated Enum internals vary too; source-defined methods are
            # covered by tests/compat/test_api.py against the upstream snapshot.
            continue
        if issubclass(cls, LinkerbotError):
            # Exception's C constructor had no inspectable signature. The
            # compatibility constructor explicitly retains arbitrary *args;
            # argument, catch and pickle behavior is checked separately.
            assert expected["signature"] is None
            assert expected["methods"] == {}
            assert _signature(cls) == "(*args) -> None"
            continue
        assert _signature(cls) == expected["signature"]
        if cls is CANMessageDispatcher:
            for name, signature in expected["methods"].items():
                assert _signature(getattr(cls, name)) == signature, name
            continue
        methods = {
            name: _signature(obj)
            for name, obj in cls.__dict__.items()
            if (callable(obj) and (not name.startswith("__") or name == "__init__"))
        }
        if cls is A7lite:
            # Keep the frozen signatures; approve only the explicit additions.
            for name, signature in expected["methods"].items():
                assert methods[name] == signature, name
            assert methods.keys() - expected["methods"].keys() == {
                "_modes_or_pp",
                "_all_modes_are",
                "_any_mode_is",
                "_hold_mit_joint",
                "_validate_mit_joint",
                "set_control_modes",
                "set_mits",
                "stream_joint_targets",
                "set_csp_angles",
                "set_limit_spds",
                "get_limit_spds",
            }
        else:
            additions = {
                "A7Motor": {"_consume_poll", "_prepare_angle"},
                "A7liteMotor": {"_prepare_angle", "_prepare_mit"},
                "MotorV2": {
                    "_prepare_angle",
                    "_heartbeat_once",
                    "_build_ptm_frame",
                    "ensure_ptm_mode",
                    "set_torque_ref",
                },
                "P7": {"_ensure_v2_ptm_mode"},
                "DataRelay": {"try_request", "_register_notified_waiter"},
            }.get(cls.__name__, set())
            for name, signature in expected["methods"].items():
                if cls is MotorV2 and name == "_build_servo_frame":
                    # The upstream PTM fix replaces this private wire encoder.
                    # Keep the frozen baseline and all public signatures intact.
                    assert name not in methods
                    continue
                assert methods[name] == signature, name
            assert methods.keys() - expected["methods"].keys() == additions
