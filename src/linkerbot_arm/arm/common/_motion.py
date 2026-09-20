"""Shared validation and timing for arm motion commands."""

import math
import struct

from linkerbot_arm.arm.common import ControlMode
from linkerbot_arm.exceptions import StateError, ValidationError


def validate_target(arm, angles, *, check_limits=True):
    """Validate without submitting or modifying accepted-target caches."""
    modes = getattr(arm, "_control_modes", None)
    if modes is not None and ControlMode.MIT in modes:
        raise StateError(
            "Register angle command is unavailable while any joint is in "
            "MIT mode; use set_mits() or stream_joint_targets()"
        )
    if len(angles) != len(arm._motors):
        raise ValueError(f"Angles count must be {len(arm._motors)}, got {len(angles)}")
    for i, angle in enumerate(angles):
        try:
            if not math.isfinite(angle):
                raise ValueError("non-finite angle")
            struct.pack("<f", angle)
        except (TypeError, ValueError, OverflowError, struct.error) as error:
            raise ValidationError(
                f"Joint {i} angle must be a finite float32 value"
            ) from error
    if check_limits:
        for i, (angle, (lo, hi)) in enumerate(zip(angles, arm._kx.get_joint_limits())):
            if not lo <= angle <= hi:
                raise ValidationError(
                    f"Joint {i} angle {angle:.4f} rad out of range [{lo:.4f}, {hi:.4f}]"
                )


def trapezoidal_duration(distance, speed, acceleration):
    if not math.isfinite(distance) or distance < 0:
        raise StateError("Motion distance must be finite and non-negative")
    if distance < 1e-12:
        return 0.0
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
        for value in (speed, acceleration)
    ):
        raise StateError(
            "Nonzero motion requires finite positive control velocity and acceleration; "
            "set_velocities() and set_accelerations() before moving"
        )
    # Compare times to avoid squaring a very large velocity limit.
    t_ramp = math.sqrt(distance) / math.sqrt(acceleration)
    if speed / acceleration >= t_ramp:
        duration = 2 * t_ramp
    else:
        duration = distance / speed + speed / acceleration
    if not math.isfinite(duration):
        raise StateError("Motion duration is not finite; check control parameters")
    return duration


def joint_duration(current, target, speeds, accelerations):
    if not (len(current) == len(target) == len(speeds) == len(accelerations)):
        raise StateError("Motion state and parameter counts must match the joint count")
    durations = []
    for i, (cur, tgt, speed, acceleration) in enumerate(
        zip(current, target, speeds, accelerations), 1
    ):
        if not math.isfinite(cur) or not math.isfinite(tgt):
            raise StateError(f"Joint {i} motion position must be finite")
        try:
            durations.append(trapezoidal_duration(abs(tgt - cur), speed, acceleration))
        except StateError as error:
            raise StateError(f"Joint {i}: {error}") from error
    return max(durations, default=0.0)


def point_duration(arm, target):
    try:
        return arm._move_duration(
            arm.get_angles(),
            target,
            arm.get_control_velocities(),
            arm.get_control_acceleration(),
        )
    except AttributeError as error:
        raise StateError(
            "Motion feedback or control parameters are unavailable; "
            "read initial state and set_velocities()/set_accelerations() before moving"
        ) from error
