"""H75-specific current feedback and motor scaling configuration."""

import math
from dataclasses import dataclass

from pydantic import BaseModel

from linkerbot_arm.exceptions import ValidationError

from .iq24 import DEFAULT_GEAR_RATIO, DEFAULT_RPM_FULL_SCALE, PROFILE_VELOCITY_SCALE


class CurrentState(BaseModel):
    current: float  # A, not joint torque
    timestamp: float


@dataclass(frozen=True)
class H75MotorConfig:
    """Scaling defaults from upstream H75 commit 9041b05; verify for the hardware.

    The velocity compensation applies only to the PP command, not measured
    velocity or acceleration. A vendor-fixed firmware may require scale=1.0.
    """

    gear_ratio: float = DEFAULT_GEAR_RATIO
    rpm_full_scale: float = DEFAULT_RPM_FULL_SCALE
    current_full_scale_a: float = 33.0
    profile_velocity_scale: float = PROFILE_VELOCITY_SCALE

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValidationError(f"{name} must be finite and positive")

        if any(
            not math.isfinite(value) or value <= 0
            for value in (self.max_velocity, self.max_acceleration)
        ):
            raise ValidationError("motor scaling produces unusable profile bounds")

    @property
    def max_velocity(self) -> float:
        """Joint rad/s at normalized PP velocity 1; not a safe operating rating."""
        return (
            self.rpm_full_scale
            * 2
            * math.pi
            / 60
            / self.gear_ratio
            / self.profile_velocity_scale
        )

    @property
    def max_acceleration(self) -> float:
        """Joint rad/s² at normalized acceleration 1."""
        return self.rpm_full_scale * 2 * math.pi / 60 / self.gear_ratio
