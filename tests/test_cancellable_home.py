"""Exercise the real three-model home implementations with cached fake motors."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from linkerbot_arm import A7, P7, A7lite, ValidationError
from linkerbot_arm.motion_timer import MotionTimer


@pytest.fixture(params=[A7, A7lite, P7])
def arm(request):
    cls = request.param
    arm = cls.__new__(cls)
    arm._motion_timer = MotionTimer()
    arm._control_modes = None
    arm._motors = [Mock() for _ in range(7)]
    arm._kx = SimpleNamespace(get_joint_limits=lambda: [(-3.0, 3.0)] * 7)
    arm.get_angles = lambda: [0.5] * 7
    arm.get_control_velocities = lambda: [0.5] * 7
    arm.get_control_acceleration = lambda: [1.0] * 7
    arm.set_velocities = Mock()
    arm.set_accelerations = Mock()
    arm._set_angles = Mock()
    yield arm
    arm._motion_timer.cancel()


def test_cancel_before_home_admission_never_submits_target(arm):
    cancel = threading.Event()
    cancel.set()
    arm.home_cancellable(cancel)
    arm._set_angles.assert_not_called()
    assert not arm.is_moving()


def test_cancel_during_duration_read_prevents_first_target(arm):
    cancel = threading.Event()

    def read_velocity():
        cancel.set()
        return [0.5] * 7

    arm.get_control_velocities = read_velocity
    arm.home_cancellable(cancel)
    arm._set_angles.assert_not_called()
    assert not arm.is_moving()


def test_cancel_running_home_finishes_without_additional_targets(arm):
    cancel = threading.Event()
    first_target = threading.Event()
    arm._set_angles.side_effect = lambda *args, **kwargs: first_target.set()
    errors = []

    def home():
        try:
            arm.home_cancellable(cancel)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=home)
    worker.start()
    try:
        assert first_target.wait(1)
        # SDK stop serializes with any already admitted target batch.
        cancel.set()
        arm.disable()
        count = arm._set_angles.call_count
        worker.join(1)
        assert not worker.is_alive()
        assert not errors
        assert arm._set_angles.call_count == count
        assert not arm.is_moving()
        if isinstance(arm, P7):
            arm.set_velocities.assert_called_with([0.5] * 7)
            arm.set_accelerations.assert_called_with([1.0] * 7)
    finally:
        cancel.set()
        arm._motion_timer.cancel()
        worker.join(1)


def test_new_home_after_cancel_can_submit_normally(arm):
    cancel = threading.Event()
    cancel.set()
    arm.home_cancellable(cancel)
    arm.get_angles = lambda: [0.0] * 7
    arm.home(blocking=True)
    assert arm._set_angles.call_count >= 1


@pytest.mark.parametrize("arm", [A7, A7lite], indirect=True)
def test_target_admission_failure_does_not_leave_motion_running(arm):
    arm._set_angles.side_effect = ValueError("target rejected")
    with pytest.raises(ValueError, match="target rejected"):
        arm.home(blocking=False)
    assert not arm.is_moving()


@pytest.mark.parametrize("arm", [A7, A7lite], indirect=True)
def test_target_validation_precedes_duration_reads(arm):
    arm.get_angles = Mock(side_effect=AssertionError("must validate first"))
    with pytest.raises(ValidationError, match="finite"):
        arm.move_j([float("nan")] * 7)
    arm._set_angles.assert_not_called()
    arm.get_angles.assert_not_called()
    assert not arm.is_moving()
