"""H75 joint motor driver (Weiyi CAN protocol, IQ24 big-endian).

Public surface mirrors :class:`linkerbot_arm.arm.a7.motor.A7Motor` so the arm
class can loop over motors uniformly. Wire encoding follows the Weiyi V1.02
manual (not A7's IEEE float little-endian firmware fork).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from enum import Enum, IntEnum

import can

from linkerbot_arm._transport.targets import PreparedTarget, submit_targets
from linkerbot_arm.arm.common import ControlMode
from linkerbot_arm.arm.common._diagnostics import describe_motor
from linkerbot_arm.arm.common.model import (
    AccelerationState,
    AngleState,
    TemperatureState,
    VelocityState,
)
from linkerbot_arm.arm.h75.iq24 import (
    DEFAULT_GEAR_RATIO,
    DEFAULT_RPM_FULL_SCALE,
    PROFILE_VELOCITY_SCALE,
    float_to_iq24_be,
    iq8_be_to_float,
    iq24_be_to_float,
    joint_rad_s2_to_profile_accel_iq,
    joint_rad_s_to_profile_velocity_iq,
    joint_rad_to_motor_rev,
    motor_rev_to_joint_rad,
    motor_rpm_to_joint_rad_s,
    profile_accel_iq_to_joint_rad_s2,
    profile_velocity_iq_to_joint_rad_s,
)
from linkerbot_arm.comm import CANMessageDispatcher
from linkerbot_arm.exceptions import StateError, TimeoutError, ValidationError
from linkerbot_arm.periodic import PeriodicTask, scheduler_for
from linkerbot_arm.relay import DataRelay

from .model import CurrentState, H75MotorConfig

logger = logging.getLogger(__name__)

# Placeholder current full-scale from Weiyi manual examples until per-joint table.
_DEFAULT_CURRENT_FULL_SCALE_A = 33.0


class SensorType(IntEnum):
    """Sensor types that support background polling."""

    POSITION = 0x06
    CURRENT = 0x04
    VELOCITY = 0x05
    TEMPERATURE = 0x5F


class InternalSensorType(IntEnum):
    ENABLED = 0x2B
    ACCELERATION = 0x1D
    POSITION_KP = 0x19
    VELOCITY_KP = 0x17
    VELOCITY_KI = 0x18
    # Weiyi handshake / heartbeat (A7 customized this to 0x01).
    HANDSHAKE = 0x00


class _ControlModeValue(int, Enum):
    """Weiyi mode table (appendix B).

    ``PP`` → ``0x06`` position trapezoid (S-curve).
    ``CSP`` → ``0x03`` ordinary position (no drive-side profile; streaming).
    """

    POSITION = 0x03
    PP = 0x06


_CONTROL_MODE_MAP = {
    ControlMode.PP: _ControlModeValue.PP,
    ControlMode.CSP: _ControlModeValue.POSITION,
}


class H75Motor:
    def __init__(
        self,
        id: int,
        dispatcher: CANMessageDispatcher,
        *,
        gear_ratio: float = DEFAULT_GEAR_RATIO,
        rpm_full_scale: float = DEFAULT_RPM_FULL_SCALE,
        current_full_scale_a: float = _DEFAULT_CURRENT_FULL_SCALE_A,
        profile_velocity_scale: float = PROFILE_VELOCITY_SCALE,
    ) -> None:
        self.config = H75MotorConfig(
            gear_ratio, rpm_full_scale, current_full_scale_a, profile_velocity_scale
        )
        self._id = id
        self._dispatcher = dispatcher
        self._gear_ratio = gear_ratio
        self._rpm_full_scale = rpm_full_scale
        self._current_full_scale_a = current_full_scale_a
        self._profile_velocity_scale = profile_velocity_scale

        self._angle: AngleState
        self._velocity: VelocityState
        self._current: CurrentState
        self._temperature: TemperatureState

        self._enabled: bool | None = None
        self._control_angle: AngleState
        self._control_velocity: VelocityState | None = None
        self._control_deceleration: AccelerationState | None = None
        self._control_acceleration: AccelerationState
        self._position_kp: float
        self._velocity_kp: float
        self._velocity_ki: float

        self._read_relays: dict[int, DataRelay[bytes]] = {}
        self._relays_lock = threading.Lock()
        self._parameter_lock = threading.RLock()
        self._stop_event = threading.Event()

        self._dispatcher.subscribe(self._on_message)

    @property
    def gear_ratio(self) -> float:
        return self._gear_ratio

    @property
    def angle(self) -> AngleState:
        return self._angle

    @property
    def velocity(self) -> VelocityState:
        return self._velocity

    @property
    def current(self) -> CurrentState:
        return self._current

    @property
    def temperature(self) -> TemperatureState:
        return self._temperature

    @property
    def control_angle(self) -> AngleState:
        return self._control_angle

    @property
    def control_velocity(self) -> VelocityState:
        with self._parameter_lock:
            if self._control_velocity is None:
                raise StateError(
                    "H75 profile velocity unknown; call set_velocities() before motion"
                )
            return self._control_velocity

    @property
    def control_deceleration(self) -> AccelerationState:
        with self._parameter_lock:
            if self._control_deceleration is None:
                raise StateError(
                    "H75 profile deceleration unknown; call set_accelerations() or set_decelerations() before motion"
                )
            return self._control_deceleration

    @property
    def torque(self):
        raise StateError("H75 torque is unavailable; current feedback is in amperes")

    @property
    def control_acceleration(self) -> AccelerationState:
        with self._parameter_lock:
            return self._control_acceleration

    @property
    def enabled(self) -> bool:
        if self._enabled is None:
            raise StateError(
                f"{describe_motor(self._id)} enable state is unknown; read back or disable before continuing"
            )
        return self._enabled

    @property
    def position_kp(self) -> float:
        with self._parameter_lock:
            return self._position_kp

    @property
    def velocity_kp(self) -> float:
        with self._parameter_lock:
            return self._velocity_kp

    @property
    def velocity_ki(self) -> float:
        with self._parameter_lock:
            return self._velocity_ki

    def _send(self, data: bytes) -> None:
        msg = can.Message(
            arbitration_id=self._id,
            data=data,
            is_extended_id=False,
        )
        self._dispatcher.send(msg)

    def _send_checked(self, data: bytes, timeout_s: float = 1.0) -> None:
        sender = getattr(self._dispatcher, "_send_checked", None)
        if sender is None:
            raise StateError(
                "H75 lifecycle requires a dispatcher with checked-send support"
            )
        sender(
            can.Message(arbitration_id=self._id, data=data, is_extended_id=False),
            timeout_s=timeout_s,
        )

    def _read_enabled(self, timeout_s: float = 1.0) -> bool:
        value = self._read_register(InternalSensorType.ENABLED, timeout_s)[0]
        if value not in (0, 1):
            self._enabled = None
            raise StateError(
                f"{describe_motor(self._id)} returned invalid enable state {value}"
            )
        self._enabled = bool(value)
        return self._enabled

    def _on_message(self, msg: can.Message) -> None:
        if (
            msg.arbitration_id != self._id
            or msg.is_extended_id
            or msg.is_remote_frame
            or msg.is_error_frame
            or msg.is_fd
            or msg.dlc != len(msg.data)
            or not 2 <= len(msg.data) <= 8
        ):
            return
        cmd = msg.data[0]
        if cmd == SensorType.TEMPERATURE:
            if len(msg.data) not in (2, 3, 5, 8):
                return
        elif (
            cmd not in (InternalSensorType.HANDSHAKE, InternalSensorType.ENABLED)
            and len(msg.data) < 5
        ):
            return
        with self._relays_lock:
            relay = self._read_relays.get(cmd)
        if relay is not None:
            relay.push(bytes(msg.data[1:]))

    def _get_relay(self, cmd: int) -> DataRelay[bytes]:
        with self._relays_lock:
            relay = self._read_relays.get(cmd)
            if relay is None:
                relay = self._read_relays[cmd] = DataRelay()
            return relay

    def _read_register(self, cmd: int, timeout_s: float = 1.0) -> bytes:
        relay = self._get_relay(cmd)
        try:
            return relay.request(lambda: self._send(bytes([cmd])), timeout_s)
        except TimeoutError as error:
            raise TimeoutError(
                f"{describe_motor(self._id)} register 0x{cmd:02X} read timed out ({timeout_s}s)"
            ) from error

    def _read_iq24(self, cmd: int, timeout_s: float = 1.0) -> float:
        return iq24_be_to_float(self._read_register(cmd, timeout_s))

    def _decode_sensor(self, sensor_type: SensorType, data: bytes) -> float:
        match sensor_type:
            case SensorType.POSITION:
                return motor_rev_to_joint_rad(iq24_be_to_float(data), self._gear_ratio)
            case SensorType.VELOCITY:
                frac = iq24_be_to_float(data)
                motor_rpm = frac * self._rpm_full_scale
                return motor_rpm_to_joint_rad_s(motor_rpm, self._gear_ratio)
            case SensorType.CURRENT:
                frac = iq24_be_to_float(data)
                return frac * self._current_full_scale_a
            case SensorType.TEMPERATURE:
                return iq8_be_to_float(data)
        raise ValidationError(f"Unsupported sensor type: {sensor_type!r}")

    def _save_params(self) -> None:
        self._send_checked(bytes([0x0D]))
        time.sleep(0.001)

    def set_control_mode(self, mode: ControlMode) -> None:
        if mode not in _CONTROL_MODE_MAP:
            raise ValidationError(
                "H75Motor only supports ControlMode.PP (Weiyi 0x06 S-curve) "
                f"and ControlMode.CSP (Weiyi 0x03 position); got {mode!r}"
            )
        mode_byte = _CONTROL_MODE_MAP[mode]
        self._send_checked(bytes([0x07, int(mode_byte)]))

    def enable(self) -> None:
        self._enabled = None
        self._send_checked(bytes([0x2A, 0x01]))
        if not self._read_enabled():
            raise StateError(f"{describe_motor(self._id)} did not confirm enable")

    def disable(self) -> None:
        self._enabled = None
        self._send_checked(bytes([0x2A, 0x00]))
        if self._read_enabled():
            raise StateError(f"{describe_motor(self._id)} did not confirm disable")

    def release_brake(self) -> None:
        """Open brake (Weiyi ``0xF4 01``; 2.X series with brake only)."""
        self._send_checked(bytes([0xF4, 0x01]))

    def lock_brake(self) -> None:
        """Lock brake (Weiyi ``0xF4 00``; 2.X series with brake only)."""
        self._send_checked(bytes([0xF4, 0x00]))

    def calibrate_zero(self) -> None:
        self._send_checked(bytes([0x87]))
        self._save_params()

    def reset_error(self) -> None:
        self._send_checked(bytes([0xFE]))

    def _encode_angle(self, angle: float) -> bytes:
        self._finite(angle, "angle")
        revolutions = joint_rad_to_motor_rev(angle, self._gear_ratio)
        if not -(1 << 7) <= revolutions <= ((1 << 31) - 1) / (1 << 24):
            raise ValidationError("angle exceeds the signed IQ24 position range")
        return float_to_iq24_be(revolutions)

    @staticmethod
    def _finite(value: float, name: str) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
        ):
            raise ValidationError(f"{name} must be a finite number")

    def _encode_profile(self, value: float, *, velocity: bool) -> tuple[bytes, float]:
        self._finite(value, "velocity" if velocity else "acceleration")
        maximum = self.config.max_velocity if velocity else self.config.max_acceleration
        minimum = 0.0 if velocity else 1e-4
        if not minimum <= value <= maximum:
            raise ValidationError(
                f"profile value {value} outside [{minimum}, {maximum}]"
            )
        options = (
            {"profile_velocity_scale": self._profile_velocity_scale} if velocity else {}
        )
        encode = (
            joint_rad_s_to_profile_velocity_iq
            if velocity
            else joint_rad_s2_to_profile_accel_iq
        )
        decode = (
            profile_velocity_iq_to_joint_rad_s
            if velocity
            else profile_accel_iq_to_joint_rad_s2
        )
        data = float_to_iq24_be(
            encode(value, self._gear_ratio, self._rpm_full_scale, **options)
        )
        effective = decode(
            iq24_be_to_float(data), self._gear_ratio, self._rpm_full_scale, **options
        )
        if not velocity and effective < minimum:
            data = (int.from_bytes(data, "big", signed=True) + 1).to_bytes(
                4, "big", signed=True
            )
            effective = decode(
                iq24_be_to_float(data),
                self._gear_ratio,
                self._rpm_full_scale,
                **options,
            )
        if value > 0 and effective <= 0:
            raise ValidationError("profile value is below the IQ24 resolution")
        return data, effective

    def set_angle(self, angle: float) -> None:
        submit_targets((self._prepare_angle(angle),), enforce_age=False)

    def _prepare_angle(self, angle: float) -> PreparedTarget:
        message = can.Message(
            arbitration_id=self._id,
            is_extended_id=False,
            data=bytes([0x0A]) + self._encode_angle(angle),
        )
        return PreparedTarget(
            self,
            message,
            {"_control_angle": AngleState(angle=angle, timestamp=time.time())},
        )

    def set_velocity(self, velocity: float) -> None:
        with self._parameter_lock:
            data, effective = self._encode_profile(velocity, velocity=True)
            self._send(bytes([0x1F]) + data)
            self._control_velocity = VelocityState(
                velocity=effective, timestamp=time.time()
            )

    def set_acceleration(self, acceleration: float) -> None:
        with self._parameter_lock:
            data, effective = self._encode_profile(acceleration, velocity=False)
            self._send(bytes([0x20]) + data)
            self._control_acceleration = AccelerationState(
                acceleration=effective, timestamp=time.time()
            )

    def set_deceleration(self, deceleration: float) -> None:
        with self._parameter_lock:
            data, effective = self._encode_profile(deceleration, velocity=False)
            self._send(bytes([0x21]) + data)
            self._control_deceleration = AccelerationState(
                acceleration=effective, timestamp=time.time()
            )

    def _encode_gain(self, value: float) -> bytes:
        self._finite(value, "gain")
        if not 0 <= value <= ((1 << 31) - 1) / (1 << 24):
            raise ValidationError("gain exceeds the nonnegative signed IQ24 range")
        return float_to_iq24_be(value)

    def set_velocity_kp(self, kp: float) -> None:
        with self._parameter_lock:
            data = self._encode_gain(kp)
            self._send(bytes([0x10]) + data)
            self._velocity_kp = iq24_be_to_float(data)

    def set_velocity_ki(self, ki: float) -> None:
        with self._parameter_lock:
            data = self._encode_gain(ki)
            self._send(bytes([0x11]) + data)
            self._velocity_ki = iq24_be_to_float(data)

    def set_position_kp(self, kp: float) -> None:
        with self._parameter_lock:
            data = self._encode_gain(kp)
            self._send(bytes([0x12]) + data)
            self._position_kp = iq24_be_to_float(data)

    def read_initial_state(self, timeout_s: float = 1.0) -> None:
        for sensor in SensorType:
            self._consume_poll(sensor, self._read_register(sensor, timeout_s))
        now = time.time()
        self._read_enabled(timeout_s)
        self._control_angle = AngleState(angle=self._angle.angle, timestamp=now)
        # No verified profile velocity/deceleration read registers in the source
        # branch. Require explicit configuration instead of guessing from feedback.
        self._control_velocity = None
        self._control_deceleration = None
        self._control_acceleration = AccelerationState(
            acceleration=profile_accel_iq_to_joint_rad_s2(
                self._read_iq24(InternalSensorType.ACCELERATION, timeout_s),
                self._gear_ratio,
                self._rpm_full_scale,
            ),
            timestamp=now,
        )
        self._position_kp = self._read_iq24(InternalSensorType.POSITION_KP, timeout_s)
        self._velocity_kp = self._read_iq24(InternalSensorType.VELOCITY_KP, timeout_s)
        self._velocity_ki = self._read_iq24(InternalSensorType.VELOCITY_KI, timeout_s)

    def has_initial_data(self) -> bool:
        return all(
            hasattr(self, a)
            for a in (
                "_angle",
                "_velocity",
                "_current",
                "_temperature",
                "_enabled",
                "_control_angle",
                "_control_velocity",
                "_control_acceleration",
                "_position_kp",
                "_velocity_kp",
                "_velocity_ki",
            )
        )

    def check_alive(self, timeout_s: float = 0.02) -> bool:
        try:
            self._read_register(InternalSensorType.HANDSHAKE, timeout_s)
            return True
        except TimeoutError:
            return False

    def start_polling(self, intervals: dict[SensorType, float]) -> None:
        tasks = []
        for sensor_type, interval_s in intervals.items():
            sensor_type = SensorType(sensor_type)
            cmd = int(sensor_type)
            relay = self._get_relay(cmd)
            tasks.append(
                PeriodicTask(
                    interval_s,
                    lambda notify, relay=relay, cmd=cmd: relay.try_request(
                        lambda: self._send(bytes([cmd])), notify
                    ),
                    lambda data, sensor_type=sensor_type: self._consume_poll(
                        sensor_type, data
                    ),
                )
            )
        self._stop_event.clear()
        scheduler_for(self._dispatcher).replace(self, tasks)

    def stop_polling(self) -> None:
        self._stop_event.set()
        scheduler = getattr(self._dispatcher, "_arm_periodic_scheduler", None)
        if scheduler is not None:
            scheduler.remove(self)

    def _consume_poll(self, sensor_type: SensorType, data: bytes) -> None:
        value = self._decode_sensor(sensor_type, data)
        now = time.time()
        match sensor_type:
            case SensorType.POSITION:
                self._angle = AngleState(angle=value, timestamp=now)
            case SensorType.VELOCITY:
                self._velocity = VelocityState(velocity=value, timestamp=now)
            case SensorType.CURRENT:
                self._current = CurrentState(current=value, timestamp=now)
            case SensorType.TEMPERATURE:
                self._temperature = TemperatureState(temperature=value, timestamp=now)
