"""Control profile values are distinct from measured velocity; never open CAN."""

import struct
from queue import Full
from types import SimpleNamespace
from unittest.mock import Mock

import can
import pytest

from linkerbot_arm import A7, P7, A7lite, StateError, ValidationError
from linkerbot_arm.arm.a7.motor import A7Motor
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.common.model import AccelerationState, VelocityState
from linkerbot_arm.motion_timer import MotionTimer


class ProfileDispatcher:
    def __init__(self):
        self.callbacks = []
        self.sent = []

    def subscribe(self, callback):
        self.callbacks.append(callback)

    def send(self, message):
        self.sent.append(message)
        values = {0x05: 0.0, 0x06: 0.0, 0x1C: 0.5, 0x1D: 1.0}
        command = message.data[0]
        reply = can.Message(
            arbitration_id=message.arbitration_id,
            is_extended_id=False,
            data=bytes([command]) + struct.pack("<f", values.get(command, 1.0)),
        )
        for callback in self.callbacks:
            callback(reply)


def test_stationary_motor_uses_profile_register_for_duration(monkeypatch):
    dispatcher = ProfileDispatcher()
    motors = [A7Motor(mid, dispatcher) for mid in range(61, 68)]
    for motor in motors:
        motor.read_initial_state(timeout_s=0)
        assert motor.velocity.velocity == 0
        assert motor.control_velocity.velocity == 0.5
    for mid in range(61, 68):
        commands = [
            frame.data[0] for frame in dispatcher.sent if frame.arbitration_id == mid
        ]
        assert commands.count(0x05) == 1
        assert commands.count(0x1C) == 1
    arm = A7.__new__(A7)
    arm._motors = motors
    arm._kx = SimpleNamespace(get_joint_limits=lambda: [(-3, 3)] * 7)
    arm._motion_timer = MotionTimer()
    arm._set_angles = Mock()
    # Capture the real computed duration without creating a long-running timer.
    start = Mock()
    monkeypatch.setattr(arm._motion_timer, "start", start)
    arm.wait_motion_done = Mock()
    arm.move_j([0.5] * 7, blocking=True)
    start.assert_called_once_with(1.5)
    arm.wait_motion_done.assert_called_once()
    arm._set_angles.assert_called_once_with([0.5] * 7)


@pytest.fixture(params=[A7, A7lite, P7])
def arm(request):
    arm = request.param.__new__(request.param)
    arm._motors = [Mock() for _ in range(7)]
    arm._control_modes = None
    arm._kx = SimpleNamespace(get_joint_limits=lambda: [(-3, 3)] * 7)
    arm._motion_timer = MotionTimer()
    arm.get_angles = Mock(return_value=[0.0] * 7)
    arm.get_control_velocities = Mock(return_value=[0.5] * 7)
    arm.get_control_acceleration = Mock(return_value=[1.0] * 7)
    arm.set_velocities = Mock()
    arm.set_accelerations = Mock()
    arm._set_angles = Mock()
    arm.inverse_kinematics = Mock(return_value=[0.5] * 7)
    yield arm
    arm._motion_timer.cancel()


@pytest.mark.parametrize("method", ["move_j", "move_p"])
@pytest.mark.parametrize("field", ["velocity", "acceleration"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), None])
def test_invalid_profile_rejected_before_any_motion_or_limit_write(
    arm, method, field, value
):
    getter = (
        arm.get_control_velocities
        if field == "velocity"
        else arm.get_control_acceleration
    )
    values = getter.return_value.copy()
    values[2] = value
    getter.return_value = values
    with pytest.raises(StateError, match="Joint 3"):
        getattr(arm, method)([0.5] * 7, blocking=False)
    arm._set_angles.assert_not_called()
    arm.set_velocities.assert_not_called()
    arm.set_accelerations.assert_not_called()
    assert not arm.is_moving()


def test_joint_duration_rejects_incomplete_and_invalid_feedback(arm):
    with pytest.raises(StateError, match="counts"):
        arm._move_duration([0] * 7, [0.5] * 7, [0.5] * 6, [1] * 7)
    with pytest.raises(StateError, match="Joint 3"):
        arm._move_duration(
            [0, 0, float("nan"), 0, 0, 0, 0], [0.5] * 7, [0.5] * 7, [1] * 7
        )


def test_stationary_axes_do_not_require_positive_speed(arm):
    assert arm._move_duration([0] * 7, [0.5] + [0] * 6, [0.5] + [0] * 6, [1] * 7) == 1.5
    assert arm._move_duration([0] * 7, [0] * 7, [0] * 7, [0] * 7) == 0


def test_missing_cached_profile_is_reported_before_submission(arm):
    arm.get_control_velocities.side_effect = AttributeError("missing _control_velocity")
    with pytest.raises(StateError, match="unavailable"):
        arm.move_j([0.5] * 7, blocking=False)
    arm._set_angles.assert_not_called()
    arm.set_velocities.assert_not_called()
    assert not arm.is_moving()


@pytest.mark.parametrize(
    "values", [[0.5] * 6, [float("nan")] * 7, [1e100] * 7, [4.0] * 7]
)
def test_target_validation_precedes_parameter_reads(arm, values):
    arm.get_angles.side_effect = AssertionError("must validate before reading")
    with pytest.raises((ValueError, ValidationError)):
        arm.move_j(values)
    arm.get_angles.assert_not_called()
    arm._set_angles.assert_not_called()


@pytest.mark.parametrize("cls", [A7Motor, A7liteMotor])
@pytest.mark.parametrize("field", ["velocity", "acceleration"])
def test_rejected_profile_write_preserves_cached_admitted_value(cls, field):
    dispatcher = Mock()
    motor = cls(61, dispatcher)
    motor._control_velocity = VelocityState(velocity=0.5, timestamp=1)
    motor._control_acceleration = AccelerationState(acceleration=1.0, timestamp=1)
    before = getattr(motor, "_control_" + field)
    dispatcher.send.side_effect = Full("queue full")
    with pytest.raises(Full):
        getattr(motor, "set_" + field)(2.0)
    assert getattr(motor, "_control_" + field) is before
    dispatcher.send.side_effect = None
    getattr(motor, "set_" + field)(2.0)
    assert getattr(getattr(motor, "_control_" + field), field) == 2.0
