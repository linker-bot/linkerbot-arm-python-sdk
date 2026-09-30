"""Unit tests for H75 Weiyi IQ24 motor driver (no hardware)."""

from __future__ import annotations

import math
import time
from collections.abc import Callable

import can
import pytest

from linkerbot_arm.arm.common import ControlMode
from linkerbot_arm.arm.h75.iq24 import (
    DEFAULT_GEAR_RATIO,
    DEFAULT_RPM_FULL_SCALE,
    PROFILE_VELOCITY_SCALE,
    float_to_iq24_be,
    iq24_be_to_float,
    joint_rad_s2_to_motor_rpm_s,
    joint_rad_s2_to_profile_accel_iq,
    joint_rad_s_to_motor_rpm,
    joint_rad_s_to_profile_velocity_iq,
    joint_rad_to_motor_rev,
    motor_rev_to_joint_rad,
    motor_rpm_to_joint_rad_s,
    profile_accel_iq_to_joint_rad_s2,
    profile_velocity_iq_to_joint_rad_s,
    rad_to_rev,
    rev_to_rad,
)
from linkerbot_arm.arm.h75.motor import H75Motor, InternalSensorType, SensorType
from linkerbot_arm.exceptions import ValidationError

pytestmark = pytest.mark.h75


class _FakeDispatcher:
    def __init__(self) -> None:
        self.sent: list[can.Message] = []
        self._subscribers: list[Callable[[can.Message], None]] = []
        self.enabled_by_id = {}

    def subscribe(self, callback: Callable[[can.Message], None]) -> None:
        self._subscribers.append(callback)

    def send(self, msg: can.Message) -> None:
        self.sent.append(msg)
        data = bytes(msg.data)
        if len(data) == 2 and data[0] == 0x2A:
            self.enabled_by_id[msg.arbitration_id] = data[1]
        elif data == b"\x2b":
            self.push_response(
                msg.arbitration_id,
                0x2B,
                bytes([self.enabled_by_id.get(msg.arbitration_id, 0)]),
            )

    def _send_checked(self, message, *, timeout_s=1.0):
        self.send(message)

    def push_response(self, motor_id: int, cmd: int, payload: bytes) -> None:
        msg = can.Message(
            arbitration_id=motor_id,
            data=bytes([cmd]) + payload,
            is_extended_id=False,
        )
        for cb in self._subscribers:
            cb(msg)


def _make_motor(
    motor_id: int = 51,
) -> tuple[H75Motor, _FakeDispatcher]:
    dispatcher = _FakeDispatcher()
    motor = H75Motor(motor_id, dispatcher)  # type: ignore[arg-type]
    return motor, dispatcher


class TestIq24Codec:
    def test_doc_example_position_5_rev(self) -> None:
        # Weiyi manual: 5.0 R → 0x05 00 00 00
        assert float_to_iq24_be(5.0) == bytes([0x05, 0x00, 0x00, 0x00])
        assert iq24_be_to_float(bytes([0x05, 0x00, 0x00, 0x00])) == pytest.approx(5.0)

    def test_roundtrip_zero_and_negative(self) -> None:
        for value in (0.0, -1.0, 0.25, 12.5, -0.125):
            encoded = float_to_iq24_be(value)
            assert iq24_be_to_float(encoded) == pytest.approx(value, abs=1e-7)

    def test_rad_rev_roundtrip(self) -> None:
        for rad in (0.0, math.pi / 2, -math.pi, 2.79):
            assert rev_to_rad(rad_to_rev(rad)) == pytest.approx(rad)

    def test_joint_motor_roundtrip_with_gear(self) -> None:
        gear = DEFAULT_GEAR_RATIO
        for rad in (0.0, math.pi / 2, -0.3, 2.79):
            rev = joint_rad_to_motor_rev(rad, gear)
            assert motor_rev_to_joint_rad(rev, gear) == pytest.approx(rad)
            assert rev == pytest.approx(rad * gear / (2.0 * math.pi))

    def test_joint_rad_s_to_motor_rpm(self) -> None:
        gear = DEFAULT_GEAR_RATIO
        # 0.1 rad/s joint → 10 rad/s motor → ≈95.49 RPM
        rpm = joint_rad_s_to_motor_rpm(0.1, gear)
        assert rpm == pytest.approx(0.1 * gear * 60.0 / (2.0 * math.pi))
        assert motor_rpm_to_joint_rad_s(rpm, gear) == pytest.approx(0.1)

    def test_profile_velocity_iq_is_motor_rpm_over_full_scale(self) -> None:
        gear = DEFAULT_GEAR_RATIO
        # Datasheet mapping (no firmware scale): 100 motor RPM → 100/6000 IQ
        assert joint_rad_s_to_profile_velocity_iq(
            motor_rpm_to_joint_rad_s(100.0, gear),
            gear,
            DEFAULT_RPM_FULL_SCALE,
            profile_velocity_scale=1.0,
        ) == pytest.approx(100.0 / 6000.0)
        # Default scale≈π: 0.1 rad/s → ≈95.49*π/6000 ≈ 0.0500
        iq = joint_rad_s_to_profile_velocity_iq(0.1, gear, DEFAULT_RPM_FULL_SCALE)
        assert iq == pytest.approx(
            joint_rad_s_to_motor_rpm(0.1 * PROFILE_VELOCITY_SCALE, gear)
            / DEFAULT_RPM_FULL_SCALE
        )
        assert profile_velocity_iq_to_joint_rad_s(iq, gear) == pytest.approx(0.1)
        # Saturate at ±1.0
        assert joint_rad_s_to_profile_velocity_iq(1000.0, gear) == pytest.approx(1.0)

    def test_profile_accel_iq_is_motor_rpm_s_over_full_scale(self) -> None:
        gear = DEFAULT_GEAR_RATIO
        # 0.15 rad/s² → ≈143.24 RPM/s → IQ ≈ 0.02387
        iq = joint_rad_s2_to_profile_accel_iq(0.15, gear, DEFAULT_RPM_FULL_SCALE)
        assert iq == pytest.approx(
            joint_rad_s2_to_motor_rpm_s(0.15, gear) / DEFAULT_RPM_FULL_SCALE
        )
        assert 0.02 < abs(iq) < 0.03
        assert profile_accel_iq_to_joint_rad_s2(iq, gear) == pytest.approx(0.15)
        # Must NOT be old R/s² encoding (~2.387)
        assert abs(iq) < 0.1
        assert joint_rad_s2_to_profile_accel_iq(1000.0, gear) == pytest.approx(1.0)


class TestH75MotorFrames:
    def test_set_control_mode_pp_is_weiyi_0x06(self) -> None:
        motor, dispatcher = _make_motor()
        motor.set_control_mode(ControlMode.PP)
        assert len(dispatcher.sent) == 1
        assert bytes(dispatcher.sent[0].data) == bytes([0x07, 0x06])

    def test_set_control_mode_csp_is_weiyi_0x03(self) -> None:
        motor, dispatcher = _make_motor()
        motor.set_control_mode(ControlMode.CSP)
        assert len(dispatcher.sent) == 1
        assert bytes(dispatcher.sent[0].data) == bytes([0x07, 0x03])

    def test_set_control_mode_rejects_mit(self) -> None:
        motor, _dispatcher = _make_motor()
        with pytest.raises(ValidationError):
            motor.set_control_mode(ControlMode.MIT)

    def test_enable_disable(self) -> None:
        motor, dispatcher = _make_motor()
        motor.enable()
        motor.disable()
        assert bytes(dispatcher.sent[0].data) == bytes([0x2A, 0x01])
        assert [bytes(m.data) for m in dispatcher.sent] == [
            b"\x2a\x01",
            b"\x2b",
            b"\x2a\x00",
            b"\x2b",
        ]
        assert motor.enabled is False

    def test_release_and_lock_brake(self) -> None:
        motor, dispatcher = _make_motor()
        motor.release_brake()
        motor.lock_brake()
        assert [bytes(m.data) for m in dispatcher.sent] == [
            bytes([0xF4, 0x01]),
            bytes([0xF4, 0x00]),
        ]

    def test_calibrate_zero_home_then_save(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        motor, dispatcher = _make_motor()
        motor.calibrate_zero()
        assert [bytes(m.data) for m in dispatcher.sent] == [
            bytes([0x87]),
            bytes([0x0D]),
        ]

    def test_reset_error(self) -> None:
        motor, dispatcher = _make_motor()
        motor.reset_error()
        assert bytes(dispatcher.sent[0].data) == bytes([0xFE])

    def test_set_angle_iq24_big_endian_motor_revolutions(self) -> None:
        motor, dispatcher = _make_motor()
        # Joint 2π/gear rad → 1 motor revolution → IQ24 0x01 00 00 00
        motor.set_angle(2.0 * math.pi / DEFAULT_GEAR_RATIO)
        assert bytes(dispatcher.sent[0].data) == bytes([0x0A, 0x01, 0x00, 0x00, 0x00])
        assert motor.control_angle.angle == pytest.approx(
            2.0 * math.pi / DEFAULT_GEAR_RATIO
        )

    def test_set_angle_five_motor_revolutions_matches_manual(self) -> None:
        motor, dispatcher = _make_motor()
        # Weiyi manual 5.0 R is motor-shaft; joint rad = 5 * 2π / gear
        motor.set_angle(5.0 * 2.0 * math.pi / DEFAULT_GEAR_RATIO)
        assert bytes(dispatcher.sent[0].data) == bytes([0x0A, 0x05, 0x00, 0x00, 0x00])

    def test_set_velocity_encodes_normalized_motor_rpm_iq(self) -> None:
        motor, dispatcher = _make_motor()
        motor.set_velocity(0.1)
        assert dispatcher.sent[0].data[0] == 0x1F
        iq = iq24_be_to_float(bytes(dispatcher.sent[0].data[1:5]))
        expected = joint_rad_s_to_profile_velocity_iq(
            0.1, DEFAULT_GEAR_RATIO, DEFAULT_RPM_FULL_SCALE
        )
        assert iq == pytest.approx(expected, abs=1e-7)
        # With PROFILE_VELOCITY_SCALE≈π: ~0.050 — not ~0.0159 (scale=1) / missing gear
        assert 0.04 < abs(iq) < 0.06
        assert motor.control_velocity.velocity == pytest.approx(0.1)

    def test_set_acceleration_encodes_normalized_motor_rpm_s_iq(self) -> None:
        motor, dispatcher = _make_motor()
        motor.set_acceleration(0.15)
        assert dispatcher.sent[0].data[0] == 0x20
        iq = iq24_be_to_float(bytes(dispatcher.sent[0].data[1:5]))
        expected = joint_rad_s2_to_profile_accel_iq(
            0.15, DEFAULT_GEAR_RATIO, DEFAULT_RPM_FULL_SCALE
        )
        assert iq == pytest.approx(expected, abs=1e-7)
        # ~0.0239 — not ~2.39 (old R/s² direct IQ)
        assert 0.02 < abs(iq) < 0.03
        assert motor.control_acceleration.acceleration == pytest.approx(0.15, abs=2e-7)

    def test_check_alive_uses_weiyi_handshake_0x00(self) -> None:
        motor, dispatcher = _make_motor(51)

        def _respond_on_send(msg: can.Message) -> None:
            if msg.data and msg.data[0] == InternalSensorType.HANDSHAKE:
                dispatcher.push_response(51, InternalSensorType.HANDSHAKE, b"\x01")

        original_send = dispatcher.send

        def send_and_respond(msg: can.Message) -> None:
            original_send(msg)
            _respond_on_send(msg)

        dispatcher.send = send_and_respond  # type: ignore[method-assign]
        assert motor.check_alive(timeout_s=0.1) is True
        assert bytes(dispatcher.sent[0].data) == bytes([0x00])

    def test_read_position_decodes_to_joint_radians(self) -> None:
        motor, dispatcher = _make_motor(51)

        original_send = dispatcher.send

        def send_and_respond(msg: can.Message) -> None:
            original_send(msg)
            cmd = msg.data[0]
            if cmd == SensorType.POSITION:
                # 0.5 motor revolution → π/gear joint rad
                dispatcher.push_response(51, cmd, float_to_iq24_be(0.5))

        dispatcher.send = send_and_respond  # type: ignore[method-assign]
        data = motor._read_register(SensorType.POSITION, timeout_s=0.1)
        angle = motor._decode_sensor(SensorType.POSITION, data)
        assert angle == pytest.approx(math.pi / DEFAULT_GEAR_RATIO)

    def test_arbitration_id_is_motor_id(self) -> None:
        motor, dispatcher = _make_motor(57)
        motor.enable()
        assert dispatcher.sent[0].arbitration_id == 57
        assert dispatcher.sent[0].is_extended_id is False


@pytest.mark.parametrize(
    "name",
    ["gear_ratio", "rpm_full_scale", "current_full_scale_a", "profile_velocity_scale"],
)
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True])
def test_scaling_configuration_rejects_invalid_values(name, value):
    from linkerbot_arm.arm.h75 import H75MotorConfig

    with pytest.raises(ValidationError):
        H75MotorConfig(**{name: value})


@pytest.mark.parametrize(
    "setter,value",
    [
        ("set_angle", float("nan")),
        ("set_angle", float("inf")),
        ("set_angle", 100.0),
        ("set_velocity", 2.01),
        ("set_acceleration", 7.0),
        ("set_deceleration", -1.0),
        ("set_position_kp", float("nan")),
        ("set_velocity_ki", 128.0),
    ],
)
def test_invalid_commands_send_nothing(setter, value):
    motor, dispatcher = _make_motor()
    with pytest.raises(ValidationError):
        getattr(motor, setter)(value)
    assert not dispatcher.sent


def test_current_is_amperes_and_not_a_torque_measurement():
    from linkerbot_arm.exceptions import StateError

    motor, _ = _make_motor()
    assert motor._decode_sensor(
        SensorType.CURRENT, float_to_iq24_be(0.5)
    ) == pytest.approx(16.5)
    with pytest.raises(StateError, match="torque is unavailable"):
        _ = motor.torque


@pytest.mark.parametrize(
    "setter,attribute,value",
    [
        ("set_velocity", "control_velocity", 0.1),
        ("set_acceleration", "control_acceleration", 0.15),
        ("set_deceleration", "control_deceleration", 0.2),
        ("set_position_kp", "position_kp", 0.5),
    ],
)
def test_rejected_write_preserves_previous_value(setter, attribute, value):
    motor, dispatcher = _make_motor()
    method = getattr(motor, setter)
    method() if value is None else method(value)
    before = getattr(motor, attribute)

    def fail(_message):
        raise RuntimeError("send failed")

    dispatcher.send = fail
    with pytest.raises(RuntimeError, match="send failed"):
        method() if value is None else method(value * 2)
    assert getattr(motor, attribute) == before


def test_velocity_cache_tracks_quantized_wire_value():
    motor, dispatcher = _make_motor()
    motor.set_velocity(0.123456789)
    iq = iq24_be_to_float(bytes(dispatcher.sent[-1].data[1:]))
    assert motor.control_velocity.velocity == profile_velocity_iq_to_joint_rad_s(iq)
