"""Soft-limit and Cartesian planner boundary checks without Pinocchio or CAN."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from linkerbot_arm import Pose, StateError, ValidationError
from linkerbot_arm.arm.common._motion import validate_target


@pytest.fixture
def kinetix(kinetix_module):
    kx = kinetix_module.ArmKinetix.__new__(kinetix_module.ArmKinetix)
    kx._model = SimpleNamespace(nq=3)
    kx._joint_limits = [(-3.0, 3.0)] * 3
    return kx


@pytest.mark.parametrize(
    "limits",
    [
        [(-1, 1), (-1, 1), (2, 1)],
        [(-1, 1), (-1, 1), (float("nan"), 1)],
        [(-1, 1), (-1, 1), (-1, float("nan"))],
        [(-1, 1), (-1, 1), ("a", "z")],
        [(-1, 1), (-1, 1), (0,)],
        [(-1, 1)] * 2,
        [(-1, 1)] * 4,
    ],
)
def test_failed_limit_update_keeps_all_previous_bounds(kinetix, limits):
    before = kinetix.get_joint_limits()
    with pytest.raises(ValueError):
        kinetix.set_joint_limits(limits)
    assert kinetix.get_joint_limits() == before


def test_limit_count_uses_custom_model_dimensions(kinetix):
    # A previously damaged limits list must not redefine the model's dimensions.
    kinetix._joint_limits.clear()
    with pytest.raises(ValueError, match="Expected 3"):
        kinetix.set_joint_limits([])
    kinetix.set_joint_limits([(-1, 1)] * 3)
    assert len(kinetix.get_joint_limits()) == 3


def test_limit_updates_and_snapshots_do_not_expose_mutable_bounds(kinetix):
    supplied = [[-1, 1], [-2, 2], [-3, 3]]
    kinetix.set_joint_limits(supplied)
    supplied[0][0] = -99
    snapshot = kinetix.get_joint_limits()
    snapshot[1] = (-99, 99)
    snapshot.clear()
    assert kinetix.get_joint_limits() == [(-1, 1), (-2, 2), (-3, 3)]


def test_equal_and_unbounded_limits_remain_supported(kinetix):
    limits = [(0, 0), (-float("inf"), float("inf")), (-1, 1)]
    kinetix.set_joint_limits(limits)
    assert kinetix.get_joint_limits() == limits


@pytest.mark.parametrize("count", [0, 2, 4])
def test_target_rejects_missing_or_extra_joint_bounds(count):
    arm = SimpleNamespace(
        _motors=[object()] * 3,
        _kx=SimpleNamespace(get_joint_limits=lambda: [(-1, 1)] * count),
    )
    with pytest.raises(StateError, match="limit count"):
        validate_target(arm, [0.0] * 3)


def test_target_limit_bypass_remains_explicit():
    getter = Mock(side_effect=AssertionError("limits should not be read"))
    arm = SimpleNamespace(
        _motors=[object()] * 3, _kx=SimpleNamespace(get_joint_limits=getter)
    )
    validate_target(arm, [0.0] * 3, check_limits=False)
    getter.assert_not_called()


def plan(kx, **overrides):
    args = dict(
        current_pose=Pose.from_list([0.0] * 6),
        current_angles=[0.0] * 3,
        target_pose=Pose.from_list([0.02, 0, 0, 0, 0, 0]),
        max_velocity=0.4,
        acceleration=0.8,
        max_angular_velocity=0.4,
        angular_acceleration=0.8,
        waypoint_interval=0.1,
    )
    args.update(overrides)
    return kx.plan_move_l(**args)


@pytest.mark.parametrize(
    "parameter",
    [
        "waypoint_interval",
        "max_velocity",
        "acceleration",
        "max_angular_velocity",
        "angular_acceleration",
    ],
)
@pytest.mark.parametrize("value", [0, -0.1, float("nan"), float("inf"), None, True])
def test_invalid_profile_rejected_before_path_generation(kinetix, parameter, value):
    # Fail immediately if old code reaches its potentially unbounded loop.
    kinetix._trap_params = Mock(side_effect=AssertionError("profile was used"))
    with pytest.raises(ValidationError, match=parameter):
        next(plan(kinetix, **{parameter: value}))
    kinetix._trap_params.assert_not_called()


@pytest.mark.parametrize("parameter", ["current_pose", "target_pose"])
@pytest.mark.parametrize("component", range(6))
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_pose_rejected_before_path_generation(
    kinetix, parameter, component, value
):
    coordinates = [0.0] * 6
    coordinates[component] = value
    kinetix._trap_params = Mock(side_effect=AssertionError("pose was used"))
    with pytest.raises(ValidationError, match=parameter):
        next(plan(kinetix, **{parameter: Pose.from_list(coordinates)}))
    kinetix._trap_params.assert_not_called()


def test_finite_inputs_cannot_produce_an_infinite_planning_duration(kinetix):
    kinetix._trap_s = Mock(side_effect=AssertionError("unbounded plan started"))
    with pytest.raises(ValidationError, match="duration"):
        next(plan(kinetix, max_velocity=1e-320))
    kinetix._trap_s.assert_not_called()


def test_nan_rotation_duration_cannot_be_hidden_by_stationary_translation(kinetix):
    kinetix._trap_s = Mock(side_effect=AssertionError("invalid plan started"))
    with pytest.raises(ValidationError, match="duration"):
        next(
            plan(
                kinetix,
                target_pose=Pose.from_list([0, 0, 0, 0.2, 0, 0]),
                max_angular_velocity=1e308,
                angular_acceleration=5e-324,
            )
        )
    kinetix._trap_s.assert_not_called()


def test_finite_pose_with_overflowing_distance_is_rejected(kinetix):
    kinetix._trap_params = Mock(side_effect=AssertionError("distance was used"))
    with np.errstate(over="ignore"), pytest.raises(ValidationError, match="distance"):
        next(plan(kinetix, target_pose=Pose.from_list([1e300, 0, 0, 0, 0, 0])))
    kinetix._trap_params.assert_not_called()


def test_planning_stops_if_the_time_step_cannot_advance(kinetix):
    class RoundedInterval(float):
        def __radd__(self, elapsed):
            # Simulate a rounded-away addition after one step without having
            # to generate enough waypoints to exhaust float precision.
            return float(self) if elapsed == 0 else elapsed

    kinetix._trap_s = Mock(return_value=0.1)
    with pytest.raises(ValidationError, match="advance planning time"):
        next(plan(kinetix, waypoint_interval=RoundedInterval(0.1)))
    assert kinetix._trap_s.call_count == 2


def test_zero_displacement_keeps_one_zero_duration_waypoint(kinetix):
    target = Pose.from_list([0.0] * 6)
    kinetix.inverse_kinematics_result = Mock(side_effect=AssertionError("IK was used"))
    waypoints = list(plan(kinetix, target_pose=target))
    assert len(waypoints) == 1
    assert waypoints[0].pose == target
    assert waypoints[0].duration == 0
    assert waypoints[0].angles == [0.0] * 3
    kinetix.inverse_kinematics_result.assert_not_called()


def test_zero_displacement_still_requires_valid_motion_parameters(kinetix):
    with pytest.raises(ValidationError, match="max_velocity"):
        next(plan(kinetix, target_pose=Pose.from_list([0.0] * 6), max_velocity=0))


def test_valid_small_plan_reaches_exact_target(kinetix, kinetix_module):
    kinetix.inverse_kinematics_result = Mock(
        return_value=kinetix_module.IKResult(joint_angles=[0.1, 0.2, 0.3])
    )
    target = Pose.from_list([0.02, 0, 0, 0, 0, 0])
    waypoints = list(plan(kinetix, target_pose=target))
    assert len(waypoints) == 4
    assert waypoints[-1].pose == target
    assert all(point.duration == 0.1 for point in waypoints)
    assert [point.pose.x for point in waypoints] == sorted(
        point.pose.x for point in waypoints
    )
    assert kinetix.inverse_kinematics_result.call_count == len(waypoints)
