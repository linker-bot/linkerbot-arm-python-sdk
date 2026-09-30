from __future__ import annotations

from linkerbot_arm.arm.h75.iq24 import DEFAULT_GEAR_RATIO, PROFILE_VELOCITY_SCALE
from linkerbot_arm.arm.h75.model import H75MotorConfig
from linkerbot_arm.arm.h75.motor import SensorType

NUM_JOINTS = 7

# Proximal joints (Weiyi 2.X) have a brake; distal joints do not.
# enable/disable only send 0xF4 to these indices.
BRAKE_JOINT_INDICES: tuple[int, ...] = (0, 1)

MIN_VELOCITY = 0.0
MAX_VELOCITY = H75MotorConfig().max_velocity

# Weiyi PP has no documented trapezoid accel floor. Keep a tiny positive
# minimum so 0/negative are still rejected; allow slow ramps for bench tests.
MIN_ACCELERATION = 1e-4
MAX_ACCELERATION = H75MotorConfig().max_acceleration

# Weiyi manual example placeholders until per-joint model table is filled in.
DEFAULT_RPM_FULL_SCALE = 6000.0
DEFAULT_CURRENT_FULL_SCALE_A = 33.0

DEFAULT_POLL_INTERVALS: dict[SensorType, float] = {
    SensorType.POSITION: 0.05,  # 20 Hz — leave bus headroom for set_angles
    SensorType.VELOCITY: 0.1,  # 10 Hz
    SensorType.CURRENT: 0.2,  # 5 Hz
    SensorType.TEMPERATURE: 2.0,  # 0.5 Hz
}

MOVE_L_MAX_MAX_VELOCITY = 0.4
MOVE_L_DEFAULT_MAX_VELOCITY = 0.05
MOVE_L_MAX_MAX_ANGULAR_VELOCITY = 3.0
MOVE_L_DEFAULT_MAX_ANGULAR_VELOCITY = 0.3

MOVE_L_MAX_ACCELERATION = 1.0
MOVE_L_DEFAULT_ACCELERATION = 0.1
MOVE_L_MAX_ANGULAR_ACCELERATION = 1.0
MOVE_L_DEFAULT_ANGULAR_ACCELERATION = 0.1

__all__ = [
    "DEFAULT_GEAR_RATIO",
    "PROFILE_VELOCITY_SCALE",
    "NUM_JOINTS",
    "BRAKE_JOINT_INDICES",
    "MIN_VELOCITY",
    "MAX_VELOCITY",
    "MIN_ACCELERATION",
    "MAX_ACCELERATION",
    "DEFAULT_RPM_FULL_SCALE",
    "DEFAULT_CURRENT_FULL_SCALE_A",
    "DEFAULT_POLL_INTERVALS",
    "MOVE_L_MAX_MAX_VELOCITY",
    "MOVE_L_DEFAULT_MAX_VELOCITY",
    "MOVE_L_MAX_MAX_ANGULAR_VELOCITY",
    "MOVE_L_DEFAULT_MAX_ANGULAR_VELOCITY",
    "MOVE_L_MAX_ACCELERATION",
    "MOVE_L_DEFAULT_ACCELERATION",
    "MOVE_L_MAX_ANGULAR_ACCELERATION",
    "MOVE_L_DEFAULT_ANGULAR_ACCELERATION",
]
