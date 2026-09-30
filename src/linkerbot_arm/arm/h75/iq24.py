"""Weiyi IQ24 / IQ8 fixed-point helpers (big-endian on the wire)."""

from __future__ import annotations

import math
import struct

_IQ24_SCALE = 1 << 24
_IQ8_SCALE = 1 << 8
_INT32_MIN = -(1 << 31)
_INT32_MAX = (1 << 31) - 1

# H75: position on wire is motor-shaft revolutions (R).
# Trapezoid max velocity 0x1F: IQ24 = motor_RPM / rpm_full_scale.
# Trapezoid accel/decel 0x20/0x21: IQ24 = (motor RPM/s) / rpm_full_scale.
# SDK surface uses joint rad / rad/s / rad/s².
DEFAULT_GEAR_RATIO = 100.0
DEFAULT_RPM_FULL_SCALE = 6000.0

# Firmware trapezoid cruise is empirically ~1/π of the datasheet 0x1F mapping
# (candump IQ correct; encoder ω ≈ ω_cmd/π). Host multiplies before encode so
# commanded joint rad/s matches measured motion. Set to 1.0 after vendor fix.
PROFILE_VELOCITY_SCALE = math.pi


def float_to_iq24_be(value: float) -> bytes:
    """Encode a float as signed IQ24, big-endian (4 bytes)."""
    raw = int(round(value * _IQ24_SCALE))
    raw = max(_INT32_MIN, min(_INT32_MAX, raw))
    return struct.pack(">i", raw)


def iq24_be_to_float(data: bytes) -> float:
    """Decode big-endian IQ24 bytes to float."""
    if len(data) < 4:
        raise ValueError(f"IQ24 payload needs 4 bytes, got {len(data)}")
    raw = struct.unpack(">i", data[:4])[0]
    return raw / _IQ24_SCALE


def iq8_be_to_float(data: bytes) -> float:
    """Decode Weiyi type-2 IQ8 payload (value = raw / 2^8)."""
    if len(data) >= 4:
        raw = struct.unpack(">i", data[:4])[0]
    elif len(data) >= 2:
        raw = struct.unpack(">h", data[:2])[0]
    elif len(data) >= 1:
        raw = struct.unpack(">b", data[:1])[0]
    else:
        raise ValueError("IQ8 payload is empty")
    return raw / _IQ8_SCALE


def rad_to_rev(rad: float) -> float:
    """Convert radians to revolutions (no gear). Prefer joint_* helpers for H75."""
    return rad / (2.0 * math.pi)


def rev_to_rad(rev: float) -> float:
    """Convert revolutions to radians (no gear). Prefer joint_* helpers for H75."""
    return rev * (2.0 * math.pi)


def joint_rad_to_motor_rev(rad: float, gear_ratio: float) -> float:
    """Joint radians → motor-shaft revolutions (position ``0x0A``)."""
    if gear_ratio <= 0:
        raise ValueError(f"gear_ratio must be positive, got {gear_ratio}")
    return rad * gear_ratio / (2.0 * math.pi)


def motor_rev_to_joint_rad(rev: float, gear_ratio: float) -> float:
    """Motor-shaft revolutions → joint radians."""
    if gear_ratio <= 0:
        raise ValueError(f"gear_ratio must be positive, got {gear_ratio}")
    return rev * (2.0 * math.pi) / gear_ratio


def rpm_to_rad_s(rpm: float) -> float:
    return rpm * (2.0 * math.pi) / 60.0


def rad_s_to_rpm(rad_s: float) -> float:
    return rad_s * 60.0 / (2.0 * math.pi)


def joint_rad_s_to_motor_rpm(rad_s: float, gear_ratio: float) -> float:
    """Joint rad/s → motor-shaft RPM (for trapezoid ``0x1F`` before normalize)."""
    if gear_ratio <= 0:
        raise ValueError(f"gear_ratio must be positive, got {gear_ratio}")
    return rad_s_to_rpm(rad_s * gear_ratio)


def motor_rpm_to_joint_rad_s(rpm: float, gear_ratio: float) -> float:
    """Motor-shaft RPM (e.g. measured ``0x05`` after ×full-scale) → joint rad/s."""
    if gear_ratio <= 0:
        raise ValueError(f"gear_ratio must be positive, got {gear_ratio}")
    return rpm_to_rad_s(rpm) / gear_ratio


def joint_rad_s2_to_motor_rpm_s(rad_s2: float, gear_ratio: float) -> float:
    """Joint rad/s² → motor-shaft RPM/s (for trapezoid ``0x20``/``0x21``)."""
    if gear_ratio <= 0:
        raise ValueError(f"gear_ratio must be positive, got {gear_ratio}")
    return rad_s_to_rpm(rad_s2 * gear_ratio)


def motor_rpm_s_to_joint_rad_s2(rpm_s: float, gear_ratio: float) -> float:
    """Motor-shaft RPM/s → joint rad/s²."""
    if gear_ratio <= 0:
        raise ValueError(f"gear_ratio must be positive, got {gear_ratio}")
    return rpm_to_rad_s(rpm_s) / gear_ratio


def joint_rad_s_to_profile_velocity_iq(
    rad_s: float,
    gear_ratio: float = DEFAULT_GEAR_RATIO,
    rpm_full_scale: float = DEFAULT_RPM_FULL_SCALE,
    *,
    profile_velocity_scale: float = PROFILE_VELOCITY_SCALE,
) -> float:
    """Joint rad/s → Weiyi ``0x1F`` IQ24 fraction in approximately [-1, 1].

    Per Weiyi V1.02 appendix D: ``IQ = RPM / full_scale`` (example 6000 RPM).
    Trapezoid max speed uses **motor-shaft** RPM (same gear as position ``0x0A``):
    ``IQ = (ω_joint × scale × gear × 60 / 2π) / rpm_full_scale``.

    ``profile_velocity_scale`` (default :data:`PROFILE_VELOCITY_SCALE`) compensates
    for firmware cruise being slower than the datasheet mapping.
    """
    if rpm_full_scale <= 0:
        raise ValueError(f"rpm_full_scale must be positive, got {rpm_full_scale}")
    if profile_velocity_scale <= 0:
        raise ValueError(
            f"profile_velocity_scale must be positive, got {profile_velocity_scale}"
        )
    frac = (
        joint_rad_s_to_motor_rpm(rad_s * profile_velocity_scale, gear_ratio)
        / rpm_full_scale
    )
    return max(-1.0, min(1.0, frac))


def profile_velocity_iq_to_joint_rad_s(
    iq_frac: float,
    gear_ratio: float = DEFAULT_GEAR_RATIO,
    rpm_full_scale: float = DEFAULT_RPM_FULL_SCALE,
    *,
    profile_velocity_scale: float = PROFILE_VELOCITY_SCALE,
) -> float:
    """Weiyi ``0x1F`` IQ fraction → user-facing joint rad/s (undoes scale)."""
    if rpm_full_scale <= 0:
        raise ValueError(f"rpm_full_scale must be positive, got {rpm_full_scale}")
    if profile_velocity_scale <= 0:
        raise ValueError(
            f"profile_velocity_scale must be positive, got {profile_velocity_scale}"
        )
    return (
        motor_rpm_to_joint_rad_s(iq_frac * rpm_full_scale, gear_ratio)
        / profile_velocity_scale
    )


def joint_rad_s2_to_profile_accel_iq(
    rad_s2: float,
    gear_ratio: float = DEFAULT_GEAR_RATIO,
    rpm_full_scale: float = DEFAULT_RPM_FULL_SCALE,
) -> float:
    """Joint rad/s² → Weiyi ``0x20``/``0x21`` IQ24 fraction in approximately [-1, 1].

    Vendor unit is motor-shaft **RPM/s**, normalized like velocity:
    ``IQ = (α_joint × gear × 60 / 2π) / rpm_full_scale``.
    """
    if rpm_full_scale <= 0:
        raise ValueError(f"rpm_full_scale must be positive, got {rpm_full_scale}")
    frac = joint_rad_s2_to_motor_rpm_s(rad_s2, gear_ratio) / rpm_full_scale
    return max(-1.0, min(1.0, frac))


def profile_accel_iq_to_joint_rad_s2(
    iq_frac: float,
    gear_ratio: float = DEFAULT_GEAR_RATIO,
    rpm_full_scale: float = DEFAULT_RPM_FULL_SCALE,
) -> float:
    """Weiyi ``0x20``/``0x21`` IQ fraction → joint rad/s²."""
    if rpm_full_scale <= 0:
        raise ValueError(f"rpm_full_scale must be positive, got {rpm_full_scale}")
    return motor_rpm_s_to_joint_rad_s2(iq_frac * rpm_full_scale, gear_ratio)
