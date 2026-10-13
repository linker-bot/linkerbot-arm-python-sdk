"""Run the real streaming method used by ROS2 with fake motors."""

from unittest.mock import Mock

import pytest

from linkerbot_arm import A7, P7, A7lite, ValidationError
from linkerbot_arm.arm.a7.motor import A7Motor
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.common.model import AccelerationState, AngleState, VelocityState
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from linkerbot_arm.motion_timer import MotionTimer


@pytest.fixture(params=[A7, A7lite, P7])
def arm(request):
    device = request.param.__new__(request.param)
    dispatcher = Mock()
    device._can_dispatcher = dispatcher
    device._motion_timer = MotionTimer()
    types = [A7liteMotor if request.param is A7lite else A7Motor] * 7
    if request.param is P7:
        types[5:] = [MotorV2, MotorV2]
    device._motors = [cls(51 + i, dispatcher) for i, cls in enumerate(types)]
    for motor in device._motors:
        motor._angle = AngleState(angle=0.0, timestamp=0.0)
        motor._control_velocity = VelocityState(velocity=0.5, timestamp=0.0)
        motor._control_acceleration = AccelerationState(acceleration=1.0, timestamp=0.0)
    device._kx = Mock()
    device._kx.get_joint_limits.return_value = [(-1.0, 1.0)] * 7
    if request.param is A7lite:
        device._control_modes = None
    yield device
    device._motion_timer.cancel()


def test_streaming_sends_angles_without_starting_a_motion_timer(arm):
    values = [0.1 * i for i in range(7)]
    arm._set_angles(values)
    assert arm._can_dispatcher.send.call_count == 7
    # P7's first external cycle seeds from feedback; later cycles perform the
    # approved automatic limiting. A7/A7lite still submit the requested target.
    accepted = [0.0] * 7 if isinstance(arm, P7) else values
    for motor, value in zip(arm._motors, accepted):
        assert motor.control_angle.angle == value
    assert not arm.is_moving()
    assert arm._motion_timer._timer is None


@pytest.mark.parametrize(
    "values,error", [([0.0] * 6, ValueError), ([2.0] * 7, ValidationError)]
)
def test_invalid_streaming_command_sends_nothing(arm, values, error):
    with pytest.raises(error):
        arm._set_angles(values)
    arm._can_dispatcher.send.assert_not_called()


def test_existing_check_limits_keyword_is_preserved(arm):
    arm._set_angles([2.0] * 7, check_limits=False)
    for motor in arm._motors:
        assert motor.control_angle.angle == (0.0 if isinstance(arm, P7) else 2.0)
