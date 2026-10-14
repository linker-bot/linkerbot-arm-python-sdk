import logging
import math
import struct
import threading
import time
from dataclasses import replace
from enum import Enum, IntEnum

import can

from linkerbot_arm._transport.targets import (
    PreparedTarget,
    submit_targets,
)
from linkerbot_arm.arm.common import ControlMode
from linkerbot_arm.arm.common.model import (
    AccelerationState,
    AngleState,
    TemperatureState,
    TorqueState,
    VelocityState,
)
from linkerbot_arm.comm import CANMessageDispatcher
from linkerbot_arm.exceptions import TimeoutError
from linkerbot_arm.feedback import JointFeedback
from linkerbot_arm.periodic import PeriodicTask, scheduler_for
from linkerbot_arm.relay import DataRelay

logger = logging.getLogger(__name__)


class SensorType(IntEnum):
    """Sensor types that support background polling."""

    POSITION = 0x06
    TORQUE = 0x03
    VELOCITY = 0x05
    TEMPERATURE = 0x5F


_FEEDBACK_FIELDS = {
    SensorType.POSITION: "angle",
    SensorType.VELOCITY: "velocity",
    SensorType.TORQUE: "torque",
}


class InternalSensorType(IntEnum):
    ENABLED = 0x2B
    CONTROL_VELOCITY = 0x1C
    ACCELERATION = 0x1D
    POSITION_KP = 0x19
    VELOCITY_KP = 0x17
    VELOCITY_KI = 0x18
    HANDSHAKE = 0x01


class _ControlModeValue(int, Enum):
    PP = 0x05


_CONTROL_MODE_MAP = {
    ControlMode.PP: _ControlModeValue.PP,
}


class A7Motor:
    def __init__(self, id: int, dispatcher: CANMessageDispatcher) -> None:
        self._feedback = JointFeedback()
        self._id = id
        self._dispatcher = dispatcher

        # Sensor state (populated by polling)
        self._angle: AngleState
        self._velocity: VelocityState
        self._torque: TorqueState
        self._temperature: TemperatureState

        # Control state (read at init, updated on set)
        self._enabled: bool
        self._control_angle: AngleState
        self._control_velocity: VelocityState
        self._control_acceleration: AccelerationState
        self._position_kp: float
        self._velocity_kp: float
        self._velocity_ki: float

        # One DataRelay per read command byte
        self._read_relays: dict[int, DataRelay[bytes]] = {}
        self._read_relays_lock = threading.Lock()

        # Polling
        self._poll_threads: list[threading.Thread] = []
        self._stop_event = threading.Event()

        self._dispatcher.subscribe(self._on_message)

    @property
    def angle(self) -> AngleState:
        return self._angle

    @property
    def velocity(self) -> VelocityState:
        return self._velocity

    @property
    def torque(self) -> TorqueState:
        return self._torque

    @property
    def temperature(self) -> TemperatureState:
        return self._temperature

    @property
    def control_angle(self) -> AngleState:
        return self._control_angle

    @property
    def control_velocity(self) -> VelocityState:
        return self._control_velocity

    @property
    def control_acceleration(self) -> AccelerationState:
        return self._control_acceleration

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def position_kp(self) -> float:
        return self._position_kp

    @property
    def velocity_kp(self) -> float:
        return self._velocity_kp

    @property
    def velocity_ki(self) -> float:
        return self._velocity_ki

    def _send(self, data: bytes) -> None:
        msg = can.Message(
            arbitration_id=self._id,
            data=data,
            is_extended_id=False,
        )
        self._dispatcher.send(msg)

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
        if cmd not in (InternalSensorType.HANDSHAKE, InternalSensorType.ENABLED):
            if len(msg.data) < 5:
                return
            value = struct.unpack("<f", msg.data[1:5])[0]
            field = _FEEDBACK_FIELDS.get(cmd)
            if field is not None:
                # Invalidate a nonfinite measurement before rejecting it from
                # legacy register replies; the previous sample is no longer current.
                self._feedback = replace(
                    self._feedback,
                    **{field: value, field + "_received_at": time.monotonic()},
                )
            if not math.isfinite(value):
                return
        with self._read_relays_lock:
            relay = self._read_relays.get(cmd)
        if relay is not None:
            relay.push(bytes(msg.data[1:]))

    def _get_relay(self, cmd: int) -> DataRelay[bytes]:
        with self._read_relays_lock:
            relay = self._read_relays.get(cmd)
            if relay is None:
                relay = self._read_relays[cmd] = DataRelay()
            return relay

    def _read_register(self, cmd: int, timeout_s: float = 1.0) -> bytes:
        relay = self._get_relay(cmd)
        return relay.request(lambda: self._send(bytes([cmd])), timeout_s)

    def _read_register_float(self, cmd: int, timeout_s: float = 1.0) -> float:
        data = self._read_register(cmd, timeout_s)
        return struct.unpack("<f", data[:4])[0]

    def _save_params(self) -> None:
        self._send(bytes([0x0D]))
        time.sleep(0.001)

    def set_control_mode(self, mode: ControlMode) -> None:
        mode_byte = _CONTROL_MODE_MAP[mode]
        self._send(bytes([0x07, mode_byte]))

    def enable(self) -> None:
        self._enabled = True
        self._send(bytes([0x2A, 0x01]))

    def disable(self) -> None:
        self._enabled = False
        self._send(bytes([0x2A, 0x00]))

    def calibrate_zero(self) -> None:
        self._send(bytes([0x87]))
        self._save_params()

    def reset_error(self) -> None:
        self._send(bytes([0xFE]))

    def set_angle(self, angle: float) -> None:
        submit_targets((self._prepare_angle(angle),), enforce_age=False)

    def _prepare_angle(self, angle: float) -> PreparedTarget:
        message = can.Message(
            arbitration_id=self._id,
            is_extended_id=False,
            data=bytes([0x0A]) + struct.pack("<f", angle),
        )
        return PreparedTarget(
            self,
            message,
            {
                "_control_angle": AngleState(angle=angle, timestamp=time.time()),
            },
        )

    def set_velocity(self, velocity: float) -> None:
        self._send(bytes([0x1F]) + struct.pack("<f", velocity))
        self._control_velocity = VelocityState(velocity=velocity, timestamp=time.time())

    def set_acceleration(self, acceleration: float) -> None:
        self._send(bytes([0x20]) + struct.pack("<f", acceleration))
        self._control_acceleration = AccelerationState(
            acceleration=acceleration, timestamp=time.time()
        )

    def set_deceleration(self, deceleration: float) -> None:
        self._send(bytes([0x21]) + struct.pack("<f", deceleration))

    def set_velocity_kp(self, kp: float) -> None:
        self._velocity_kp = kp
        self._send(bytes([0x10]) + struct.pack("<f", kp))

    def set_velocity_ki(self, ki: float) -> None:
        self._velocity_ki = ki
        self._send(bytes([0x11]) + struct.pack("<f", ki))

    def set_position_kp(self, kp: float) -> None:
        self._position_kp = kp
        self._send(bytes([0x12]) + struct.pack("<f", kp))

    def read_initial_state(self, timeout_s: float = 1.0) -> None:
        now = time.time()
        self._angle = AngleState(
            angle=self._read_register_float(SensorType.POSITION, timeout_s),
            timestamp=now,
        )
        self._velocity = VelocityState(
            velocity=self._read_register_float(SensorType.VELOCITY, timeout_s),
            timestamp=now,
        )
        self._torque = TorqueState(
            torque=self._read_register_float(SensorType.TORQUE, timeout_s),
            timestamp=now,
        )
        self._temperature = TemperatureState(
            temperature=self._read_register_float(SensorType.TEMPERATURE, timeout_s),
            timestamp=now,
        )
        self._enabled = bool(
            self._read_register(InternalSensorType.ENABLED, timeout_s)[0]
        )
        self._control_angle = AngleState(
            angle=self._read_register_float(SensorType.POSITION, timeout_s),
            timestamp=now,
        )
        self._control_velocity = VelocityState(
            velocity=self._read_register_float(
                InternalSensorType.CONTROL_VELOCITY, timeout_s
            ),
            timestamp=now,
        )
        self._control_acceleration = AccelerationState(
            acceleration=self._read_register_float(
                InternalSensorType.ACCELERATION, timeout_s
            ),
            timestamp=now,
        )
        self._position_kp = self._read_register_float(
            InternalSensorType.POSITION_KP, timeout_s
        )
        self._velocity_kp = self._read_register_float(
            InternalSensorType.VELOCITY_KP, timeout_s
        )
        self._velocity_ki = self._read_register_float(
            InternalSensorType.VELOCITY_KI, timeout_s
        )

    def has_initial_data(self) -> bool:
        return all(
            hasattr(self, a)
            for a in (
                "_angle",
                "_velocity",
                "_torque",
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
        self._stop_event.clear()
        scheduler = scheduler_for(self._dispatcher)
        tasks = []
        for sensor_type, interval_s in intervals.items():
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
        scheduler.replace(self, tasks)

    def stop_polling(self) -> None:
        self._stop_event.set()
        scheduler = getattr(self._dispatcher, "_arm_periodic_scheduler", None)
        if scheduler is not None:
            scheduler.remove(self)

    def _consume_poll(self, sensor_type: SensorType, data: bytes) -> None:
        value = struct.unpack("<f", data[:4])[0]
        now = time.time()
        match sensor_type:
            case SensorType.POSITION:
                self._angle = AngleState(angle=value, timestamp=now)
            case SensorType.VELOCITY:
                self._velocity = VelocityState(velocity=value, timestamp=now)
            case SensorType.TORQUE:
                self._torque = TorqueState(torque=value, timestamp=now)
            case SensorType.TEMPERATURE:
                self._temperature = TemperatureState(temperature=value, timestamp=now)

    def _poll_sensor(self, sensor_type: SensorType, interval_s: float) -> None:
        """Legacy private loop; normal polling uses the shared scheduler."""
        relay = self._get_relay(int(sensor_type))
        while not self._stop_event.is_set():
            try:
                data = relay.request(
                    lambda: self._send(bytes([int(sensor_type)])), interval_s
                )
                self._consume_poll(sensor_type, data)
            except TimeoutError:
                pass
            except Exception:
                logger.exception(
                    "Poll error for %s on motor %d", sensor_type.name, self._id
                )
            self._stop_event.wait(interval_s)
