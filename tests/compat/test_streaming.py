"""Run the real streaming method used by ROS2 with fake motors."""

from unittest.mock import Mock

import pytest

from linkerbot import A7, P7, A7lite, ValidationError


@pytest.fixture(params=[A7, A7lite, P7])
def arm(request):
    device = request.param.__new__(request.param)
    device._motors = [Mock() for _ in range(7)]
    device._kx = Mock()
    device._kx.get_joint_limits.return_value = [(-1.0, 1.0)] * 7
    return device


def test_streaming_sends_angles_without_starting_a_motion_timer(arm):
    values = [0.1 * i for i in range(7)]
    arm._set_angles(values)
    for motor, value in zip(arm._motors, values):
        motor.set_angle.assert_called_once_with(value)


@pytest.mark.parametrize(
    "values,error", [([0.0] * 6, ValueError), ([2.0] * 7, ValidationError)]
)
def test_invalid_streaming_command_sends_nothing(arm, values, error):
    with pytest.raises(error):
        arm._set_angles(values)
    for motor in arm._motors:
        motor.set_angle.assert_not_called()


def test_existing_check_limits_keyword_is_preserved(arm):
    arm._set_angles([2.0] * 7, check_limits=False)
    for motor in arm._motors:
        motor.set_angle.assert_called_once_with(2.0)
