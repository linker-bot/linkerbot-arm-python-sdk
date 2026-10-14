"""Real decoders and cache reads; no physical bus or motion is used."""

import math
import struct
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import Mock

import can
import pytest

from linkerbot_arm import A7, P7, A7lite, ArmFeedback, JointFeedback
from linkerbot_arm.arm.a7.motor import A7Motor, SensorType
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.p7.motor_v2 import MotorV2


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Feedback tests must not open hardware")

    monkeypatch.setattr(can, "Bus", forbidden)
    monkeypatch.setattr(can.interface, "Bus", forbidden)


def frame(cls, mid, value=1.25):
    if cls is A7Motor:
        return can.Message(
            arbitration_id=mid,
            is_extended_id=False,
            data=b"\x06" + struct.pack("<f", value),
        )
    if cls is A7liteMotor:
        return can.Message(
            arbitration_id=0x020000FD | (mid << 8),
            is_extended_id=True,
            data=bytes.fromhex("ffffffffffff012c"),
        )
    return can.Message(
        arbitration_id=mid,
        is_extended_id=False,
        data=bytes.fromhex("01ffffffff00071e"),
    )


def deliver(motor):
    cls = type(motor)
    message = frame(cls, motor._id)
    if cls is A7Motor:
        for field in (SensorType.POSITION, SensorType.VELOCITY, SensorType.TORQUE):
            message.data[0] = field
            motor._on_message(message)
    else:
        motor._on_message(message)


def make_arm(cls):
    arm = cls.__new__(cls)
    arm._closed = False
    arm._bus_error = None
    kinds = [A7liteMotor] * 7 if cls is A7lite else [A7Motor] * 7
    if cls is P7:
        kinds[-2:] = [MotorV2] * 2
    arm._motors = [kind(mid, Mock()) for kind, mid in zip(kinds, range(61, 68))]
    arm.get_pose = Mock(side_effect=AssertionError("Unexpected FK"))
    arm.get_state = Mock(side_effect=AssertionError("Unexpected full state read"))
    return arm


@pytest.mark.parametrize("cls", [A7, A7lite, P7])
def test_full_chain_missing_fresh_stale_recovery_close_and_bus_error(cls, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    arm = make_arm(cls)
    assert not arm.get_feedback().is_fresh(0.5)
    for motor in arm._motors:
        deliver(motor)
    snapshot = arm.get_feedback()
    assert snapshot.is_fresh(0.5)
    assert snapshot.oldest_received_at == 100.0
    assert snapshot.joints[0] is arm._motors[0]._feedback
    with pytest.raises(FrozenInstanceError):
        snapshot.joints[0].angle = 42
    clock[0] = 100.6
    for motor in arm._motors[:-1]:
        deliver(motor)
    assert not arm.get_feedback().is_fresh(0.5)  # one missing joint is enough
    deliver(arm._motors[-1])
    assert arm.get_feedback().is_fresh(0.5)
    assert not snapshot.is_fresh(0.5)  # old snapshot remains old
    arm._on_bus_error(RuntimeError("lost CAN"))
    assert not arm.get_feedback().connected
    assert not arm.get_feedback().is_fresh(0.5)
    arm._closed = False  # even an independently set bus fault invalidates it
    assert not arm.get_feedback().connected
    arm._bus_error = None
    arm._closed = True
    assert not arm.get_feedback().is_fresh(0.5)
    for motor in arm._motors:
        motor._dispatcher.send.assert_not_called()


def test_a7_receive_time_survives_delayed_consumption_and_partial_polling(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    motor = A7Motor(61, Mock())
    deliver(motor)
    original = motor._feedback
    clock[0] = 20.0
    motor._consume_poll(SensorType.POSITION, struct.pack("<f", 1.25))
    assert motor._feedback is original  # poll consumption cannot freshen data
    motor._on_message(frame(A7Motor, 61, 2.0))
    feedback = ArmFeedback((motor._feedback,), True)
    assert feedback.oldest_received_at == 10.0
    assert motor._feedback.angle_received_at == 20.0
    assert not feedback.is_fresh(0.5)


@pytest.mark.parametrize("cls", [A7Motor, A7liteMotor, MotorV2])
def test_targets_and_registers_do_not_refresh_measurements(cls, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    motor = cls(61, Mock())
    deliver(motor)
    sample = motor._feedback
    clock[0] = 20.0
    motor.set_angle(0.0)
    motor.set_velocity(0.5)
    if cls is A7Motor:
        register = can.Message(
            arbitration_id=61, is_extended_id=False, data=b"\x1c" + bytes(4)
        )
    elif cls is A7liteMotor:
        register = can.Message(
            arbitration_id=0x11003DFD,
            is_extended_id=True,
            data=bytes.fromhex("1670000000000000"),
        )
    else:
        register = can.Message(
            arbitration_id=0x63D,
            is_extended_id=False,
            data=bytes.fromhex("3d0b0102030400ff"),
        )
    motor._on_message(register)
    assert motor._feedback is sample
    assert not ArmFeedback((sample,), True).is_fresh(0.5)


@pytest.mark.parametrize("cls", [A7Motor, A7liteMotor, MotorV2])
@pytest.mark.parametrize(
    "fault", ["wrong_id", "short", "error", "remote", "fd", "extended", "dlc"]
)
def test_malformed_frames_do_not_freshen(cls, fault):
    motor = cls(61, Mock())
    deliver(motor)
    old = motor._feedback
    message = frame(cls, 61)
    if fault == "wrong_id":
        message.arbitration_id = 0x02003EFD if cls is A7liteMotor else 62
    elif fault == "short":
        message.data = message.data[:2]
        message.dlc = 2
    elif fault == "dlc":
        message.dlc = 1
    else:
        attribute = {
            "error": "is_error_frame",
            "remote": "is_remote_frame",
            "fd": "is_fd",
            "extended": "is_extended_id",
        }[fault]
        setattr(message, attribute, not getattr(message, attribute))
    motor._on_message(message)
    assert motor._feedback is old


@pytest.mark.parametrize("cls", [A7Motor, A7liteMotor, MotorV2])
def test_wall_clock_jump_and_legacy_mutation_cannot_change_freshness(cls, monkeypatch):
    monkeypatch.setattr("time.monotonic", lambda: 100.0)
    monkeypatch.setattr("time.time", lambda: -1e9)
    motor = cls(61, Mock())
    deliver(motor)
    sample = motor._feedback
    assert ArmFeedback((sample,), True).is_fresh(0.5)
    monkeypatch.setattr("time.time", lambda: 1e15)
    if cls is not A7Motor:
        motor.angle.angle = math.inf  # legacy pydantic models remain mutable
    assert motor._feedback is sample
    assert ArmFeedback((sample,), True).is_fresh(0.5)
    assert not ArmFeedback((sample,), True).is_fresh(0.5, now=101.0)


@pytest.mark.parametrize(
    "field",
    [
        "angle",
        "velocity",
        "torque",
        "angle_received_at",
        "velocity_received_at",
        "torque_received_at",
    ],
)
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_samples_are_invalid(field, value):
    joint = JointFeedback(1, 2, 3, 100, 100, 100)
    assert not ArmFeedback((replace(joint, **{field: value}),), True).is_fresh(
        0.5, now=100
    )


def test_missing_future_empty_and_invalid_age():
    sample = JointFeedback(1, 2, 3, 100, 100, 101)
    assert not ArmFeedback((sample,), True).is_fresh(1, now=100)
    assert not ArmFeedback((JointFeedback(),), True).is_fresh(1)
    assert not ArmFeedback((), True).is_fresh(1)
    assert ArmFeedback((), True).oldest_received_at is None
    for bad in [0, -1, math.nan, math.inf, True, "0.5"]:
        with pytest.raises(ValueError):
            ArmFeedback((sample,), True).is_fresh(bad)


def test_close_during_snapshot_read_is_visible():
    # Lifecycle flags are read after motor samples, not cached at function entry.
    from linkerbot_arm.feedback import read_feedback

    arm = SimpleNamespace(_closed=False, _bus_error=None)

    class ClosingMotor:
        @property
        def _feedback(self):
            arm._closed = True
            return JointFeedback(1, 2, 3, 100, 100, 100)

    arm._motors = [ClosingMotor()]
    assert not read_feedback(arm).connected


@pytest.mark.parametrize("cls", [A7, A7lite, P7])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_real_close_invalidates_feedback_even_if_cleanup_fails(cls, cleanup_fails):
    arm = make_arm(cls)
    for motor in arm._motors:
        deliver(motor)
    assert arm.get_feedback().is_fresh(1.0)
    arm.stop_polling = Mock()
    arm.wait_motion_done = Mock()
    arm._can_dispatcher = Mock()
    if cleanup_fails:
        arm._can_dispatcher.stop.side_effect = RuntimeError("cannot close adapter")
        with pytest.raises(RuntimeError, match="cannot close adapter"):
            arm.close()
    else:
        arm.close()
    assert not arm.get_feedback().connected
    assert not arm.get_feedback().is_fresh(1.0)


@pytest.mark.parametrize(
    "module_path,cls",
    [
        ("linkerbot_arm.arm.a7_lite.motor", A7liteMotor),
        ("linkerbot_arm.arm.p7.motor_v2", MotorV2),
    ],
)
def test_frame_is_published_atomically_and_does_not_alias_mutable_states(
    module_path, cls, monkeypatch
):
    import importlib

    module = importlib.import_module(module_path)
    motor = cls(61, Mock())
    old = motor._feedback
    velocity_state = module.VelocityState

    def during_decode(**kwargs):
        # Simulate a reader running between two legacy field assignments.
        assert motor._feedback is old
        motor._angle.angle = 999.0
        return velocity_state(**kwargs)

    monkeypatch.setattr(module, "VelocityState", during_decode)
    deliver(motor)
    assert motor._feedback is not old
    assert motor._feedback.angle != 999.0
    assert motor._feedback.angle_received_at == motor._feedback.velocity_received_at
    assert motor._feedback.angle_received_at == motor._feedback.torque_received_at


@pytest.mark.parametrize(
    "register,field",
    [
        (SensorType.POSITION, "angle"),
        (SensorType.VELOCITY, "velocity"),
        (SensorType.TORQUE, "torque"),
    ],
)
@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf])
def test_a7_nonfinite_reply_invalidates_feedback_but_not_register_cache(
    register, field, invalid, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    motor = A7Motor(61, Mock())
    relay = motor._get_relay(register)
    deliver(motor)
    before = motor._feedback
    previous_reply = relay.snapshot()
    clock[0] = 100.1
    message = frame(A7Motor, 61, invalid)
    message.data[0] = register
    motor._on_message(message)
    assert not math.isfinite(getattr(motor._feedback, field))
    assert getattr(motor._feedback, field + "_received_at") == clock[0]
    for other in {"angle", "velocity", "torque"} - {field}:
        assert getattr(motor._feedback, other) == getattr(before, other)
        assert getattr(motor._feedback, other + "_received_at") == getattr(
            before, other + "_received_at"
        )
    assert relay.snapshot() == previous_reply
    assert not ArmFeedback((motor._feedback,), True).is_fresh(1.0)

    clock[0] = 100.2
    message.data[1:] = struct.pack("<f", 2.5)
    motor._on_message(message)
    assert ArmFeedback((motor._feedback,), True).is_fresh(1.0)
    assert relay.snapshot() == struct.pack("<f", 2.5)
