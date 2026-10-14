"""Immutable, zero-I/O joint feedback with host monotonic reception times.

These times are recorded by the motor decoder, not by the device firmware.
They must never be interpreted as Unix timestamps or ROS clock timestamps.
"""

import math
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JointFeedback:
    """Latest measured values for one joint; missing values start as NaN.

    A7 fields arrive independently. A7lite and P7 V2 feedback frames replace
    all three fields together. Control writes do not update these samples.
    """

    angle: float = math.nan
    velocity: float = math.nan
    torque: float = math.nan
    angle_received_at: float | None = None
    velocity_received_at: float | None = None
    torque_received_at: float | None = None


@dataclass(frozen=True, slots=True)
class ArmFeedback:
    """Cached joint samples and connection state at the time of the read.

    This is not a synchronized measurement across joints. ``connected`` only
    says the SDK has not closed or reported a bus error; use ``is_fresh`` to
    check every field. An already returned object does not track later closes.
    """

    joints: tuple[JointFeedback, ...]
    connected: bool

    @property
    def oldest_received_at(self) -> float | None:
        """Oldest host monotonic reception time, or None for missing fields."""
        oldest = math.inf
        for joint in self.joints:
            for received in (
                joint.angle_received_at,
                joint.velocity_received_at,
                joint.torque_received_at,
            ):
                if received is None or not math.isfinite(received):
                    return None
                oldest = min(oldest, received)
        return oldest if self.joints else None

    def is_fresh(self, max_age_s: float, *, now: float | None = None) -> bool:
        """Check connection, completeness, finite values and all sample ages.

        ``now``, when supplied, must use the same ``time.monotonic()`` clock.
        Repeated reads cannot refresh these timestamps. Check a new snapshot
        each time, so a close or bus error is observed as well as elapsed age.
        """
        if (
            isinstance(max_age_s, bool)
            or not isinstance(max_age_s, (int, float))
            or not math.isfinite(max_age_s)
            or max_age_s <= 0
        ):
            raise ValueError("max_age_s must be a finite positive number")
        if not self.connected or not self.joints:
            return False
        now = time.monotonic() if now is None else now
        if not math.isfinite(now):
            return False
        for joint in self.joints:
            for value, received in (
                (joint.angle, joint.angle_received_at),
                (joint.velocity, joint.velocity_received_at),
                (joint.torque, joint.torque_received_at),
            ):
                if (
                    not math.isfinite(value)
                    or received is None
                    or not math.isfinite(received)
                    or not 0 <= now - received <= max_age_s
                ):
                    return False
        return True


def read_feedback(arm) -> ArmFeedback:
    """Share immutable per-motor samples; no CAN request, FK or health query."""
    joints = tuple(motor._feedback for motor in arm._motors)
    # Read lifecycle flags last so a close during the cache read invalidates it.
    connected = not arm._closed and getattr(arm, "_bus_error", None) is None
    return ArmFeedback(joints=joints, connected=connected)
