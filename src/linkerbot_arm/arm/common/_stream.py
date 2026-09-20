"""Ordered host trajectories with no catch-up bursts after planning or stalls."""

import logging
import math
import time

from linkerbot_arm.arm.common._motion import validate_target
from linkerbot_arm.exceptions import StateError

logger = logging.getLogger(__name__)
WAYPOINT_INTERVAL = 0.01


def plan_linear(arm, current_pose, current_angles, target_pose, **kwargs):
    """Finish and validate the whole plan before modifying drive parameters."""
    waypoints = []
    for waypoint in arm._kx.plan_move_l(
        current_pose,
        current_angles,
        target_pose,
        waypoint_interval=WAYPOINT_INTERVAL,
        **kwargs,
    ):
        if arm._motion_timer._wait_cancelled(0):
            return []
        angles = list(waypoint.angles)
        validate_target(arm, angles)
        waypoints.append(angles)
    return waypoints


def _read_limits(arm, max_velocity, max_acceleration):
    try:
        velocities = arm.get_control_velocities()
        accelerations = arm.get_control_acceleration()
    except AttributeError as error:
        raise StateError(
            "Control limits unavailable; read or set them before motion"
        ) from error
    for name, values, minimum, maximum in (
        ("velocity", velocities, 0, max_velocity),
        ("acceleration", accelerations, 1, max_acceleration),
    ):
        if len(values) != len(arm._motors) or any(
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not minimum <= value <= maximum
            for value in values
        ):
            raise StateError(
                f"Cannot restore invalid control {name}; set valid limits before motion"
            )
    return list(velocities), list(accelerations)


def stream_targets(arm, waypoints, *, max_velocity, max_acceleration, settle=True):
    """Execute in an owned MotionTimer._stream_scope; preserve every waypoint.

    Wait one interval after each submission completes, including the initial
    configuration. Slow submission/scheduling stretches time instead of sending
    overdue points back-to-back. SDK admission is not physical completion.
    """
    timer = arm._motion_timer
    if timer._wait_cancelled(0):
        return
    velocities, accelerations = _read_limits(arm, max_velocity, max_acceleration)
    changed_velocity = changed_acceleration = False
    original_error = None
    try:
        with timer._lock:
            if timer._wait_cancelled(0):
                return
            # Set the flag first: a per-joint configuration can fail partway.
            changed_velocity = True
            arm.set_velocities([max_velocity] * len(arm._motors))
            if timer._wait_cancelled(0):
                return
            changed_acceleration = True
            arm.set_accelerations([max_acceleration] * len(arm._motors))
        for angles in waypoints:
            deadline = time.perf_counter() + WAYPOINT_INTERVAL
            while True:
                if timer._wait_cancelled(max(0.0, deadline - time.perf_counter())):
                    return
                if time.perf_counter() >= deadline:
                    break
            if not timer._run_unless_cancelled(
                lambda: arm._set_angles(angles, check_limits=False)
            ):
                return
        if settle:
            timer._wait_cancelled(WAYPOINT_INTERVAL)
    except BaseException as error:
        original_error = error
        raise
    finally:
        # Stop/disable use the same lock. In particular, an A7lite stop's
        # temporary zero-speed hold must not be overwritten midway by cleanup.
        errors = []
        with timer._lock:
            for changed, restore, values in (
                (changed_velocity, arm.set_velocities, velocities),
                (changed_acceleration, arm.set_accelerations, accelerations),
            ):
                if changed:
                    try:
                        restore(values)
                    except BaseException as error:
                        errors.append(error)
                        logger.error("Failed to restore motion parameters: %s", error)
        if errors and original_error is None:
            raise errors[0]
