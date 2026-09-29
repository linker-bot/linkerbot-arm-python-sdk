"""P7 PTM wire contract, Flash migration and failure cleanup without hardware."""

import importlib
import threading

import can
import pytest

from linkerbot_arm import P7, ControlMode, StateError, TimeoutError
from linkerbot_arm.arm.p7 import motor_v2
from linkerbot_arm.arm.p7.motor_v2 import MotorV2

from . import test_arm_transport_lifecycle as lifecycle
from .test_transport_frames import FakeDispatcher

constructed_arm = lifecycle.constructed_arm


def ptm_velocity(frame):
    raw = int.from_bytes(frame.data[2:4], "big") >> 4
    return -10.0 + raw * 20.0 / 4095


@pytest.mark.parametrize(
    "angle,velocity,kp,kd,torque,payload",
    [
        (0.0, 0.0, 4.0, 15.0, 0.0, "80008000424cc800"),
        (-12.5, -10.0, 0.0, 0.0, -50.0, "0000000000000000"),
        (12.5, 10.0, 250.0, 50.0, 50.0, "ffffffffffffffff"),
        (-20.0, -20.0, -1.0, -1.0, -60.0, "0000000000000000"),
        (20.0, 20.0, 300.0, 60.0, 60.0, "ffffffffffffffff"),
    ],
)
def test_ptm_golden_frames(angle, velocity, kp, kd, torque, payload):
    motor = MotorV2(66, FakeDispatcher())
    motor.set_position_kp(kp)
    motor._position_kd = kd
    motor.set_torque_ref(torque)
    assert motor._build_ptm_frame(angle, velocity) == bytes.fromhex(payload)


def test_profile_and_velocity_loop_settings_do_not_become_ptm_feedforward():
    dispatcher = FakeDispatcher()
    motor = MotorV2(66, dispatcher)
    motor.set_velocity(50.0)  # temporary streaming profile maximum
    motor.set_acceleration(50.0)
    motor.set_velocity_kp(200.0)
    motor.set_velocity_ki(0.04)
    motor.set_angle(0.0)
    assert bytes(dispatcher.sent[-1].data) == bytes.fromhex("80008000424cc800")
    assert motor.control_velocity.velocity == 50.0
    assert motor.control_acceleration.acceleration == 50.0
    assert motor.velocity_kp == motor.velocity_ki == 0.0


def test_signed_feedforward_uses_last_accepted_target_and_heartbeat_holds(monkeypatch):
    dispatcher = FakeDispatcher()
    motor = MotorV2(66, dispatcher)
    monkeypatch.setattr(motor_v2, "_DEFAULT_V_REF", 0.75)
    for angle, expected_velocity in [
        (0.0, 0.0),
        (0.2, 0.75),
        (-0.1, -0.75),
        (-0.1, 0.0),
    ]:
        motor.set_angle(angle)
        assert ptm_velocity(dispatcher.sent[-1]) == pytest.approx(
            expected_velocity, abs=0.003
        )
    motor.set_torque_ref(50.0)
    motor._heartbeat_once(None)
    heartbeat = dispatcher.sent[-1]
    assert ptm_velocity(heartbeat) == pytest.approx(0.0, abs=0.003)
    assert int.from_bytes(heartbeat.data[-2:], "big") & 0xFFF == 0xFFF
    assert motor.control_angle.angle == -0.1


def test_failed_submission_does_not_change_feedforward_direction(monkeypatch):
    dispatcher = FakeDispatcher()
    motor = MotorV2(66, dispatcher)
    motor.set_angle(0.0)
    send = dispatcher.send
    monkeypatch.setattr(motor_v2, "_DEFAULT_V_REF", 1.0)

    def reject(message):
        raise RuntimeError("rejected")

    monkeypatch.setattr(dispatcher, "send", reject)
    with pytest.raises(RuntimeError, match="rejected"):
        motor.set_angle(0.5)
    assert motor.control_angle.angle == 0.0
    monkeypatch.setattr(dispatcher, "send", send)
    motor.set_angle(0.25)
    assert ptm_velocity(dispatcher.sent[-1]) == pytest.approx(1.0, abs=0.003)


@pytest.mark.parametrize("mode", [ControlMode.MIT, ControlMode.CSP])
def test_ptm_preserves_pp_only_public_mode(mode):
    dispatcher = FakeDispatcher()
    motor = MotorV2(66, dispatcher)
    motor.set_control_mode(ControlMode.PP)
    with pytest.raises(ValueError, match="P-T-M"):
        motor.set_control_mode(mode)
    assert not dispatcher.sent


class FlashDispatcher(FakeDispatcher):
    def __init__(self, mode, *, sticky=False, drop_read=None):
        super().__init__()
        self.mode = mode
        self.sticky = sticky
        self.drop_read = drop_read
        self.read_count = 0

    def send(self, message):
        super().send(message)
        if message.arbitration_id != 0x642:
            return
        data = bytes(message.data)
        if data[1] == 0x0B and data[6] == 0x15 and not self.sticky:
            self.mode = int.from_bytes(data[2:6], "little", signed=True)
        if data[6] == 0x04:
            self.read_count += 1
            if self.read_count == self.drop_read:
                return
            self.feedback(
                can.Message(
                    arbitration_id=0x642,
                    is_extended_id=False,
                    data=bytes([66, data[1]])
                    + self.mode.to_bytes(4, "little", signed=True)
                    + b"\x00\xff",
                )
            )


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
def test_discovery_only_reads_flash_in_any_mode(mode):
    dispatcher = FlashDispatcher(mode)
    motor = MotorV2(66, dispatcher)
    assert motor.check_alive()
    assert [bytes(m.data).hex() for m in dispatcher.sent] == ["670b000000000476"]


def test_already_ptm_skips_rest_write_and_save(monkeypatch):
    dispatcher = FlashDispatcher(2)
    motor = MotorV2(66, dispatcher)
    waits = []
    monkeypatch.setattr(motor_v2.time, "sleep", waits.append)
    motor.ensure_ptm_mode()
    assert [bytes(m.data).hex() for m in dispatcher.sent] == ["670b000000000476"]
    assert waits == []


def test_mode_migration_orders_rest_write_save_and_readback(monkeypatch):
    dispatcher = FlashDispatcher(1)
    motor = MotorV2(66, dispatcher)
    waits = []
    monkeypatch.setattr(motor_v2.time, "sleep", waits.append)
    motor.ensure_ptm_mode()
    assert [(m.arbitration_id, bytes(m.data).hex()) for m in dispatcher.sent] == [
        (0x642, "670b000000000476"),
        (66, "fffffffffffffffd"),
        (0x642, "670b020000001576"),
        (0x642, "6700000000001576"),
        (0x642, "670b000000000476"),
    ]
    assert waits == [1.0]
    assert dispatcher.mode == 2
    dispatcher.sent.clear()
    motor.ensure_ptm_mode()
    assert len(dispatcher.sent) == 1  # repeated construction does not wear Flash


def test_mode_readback_mismatch_identifies_joint(monkeypatch):
    dispatcher = FlashDispatcher(1, sticky=True)
    motor = MotorV2(66, dispatcher)
    monkeypatch.setattr(motor_v2.time, "sleep", lambda _: None)
    with pytest.raises(StateError, match=r"Left arm joint 6.*66.*Flash Control Mode=1"):
        motor.ensure_ptm_mode()


@pytest.mark.parametrize("drop_read", [1, 2])
def test_mode_read_timeout_propagates_without_control_frames(monkeypatch, drop_read):
    dispatcher = FlashDispatcher(1, drop_read=drop_read)
    motor = MotorV2(66, dispatcher)
    monkeypatch.setattr(motor_v2.time, "sleep", lambda _: None)
    with pytest.raises(TimeoutError):
        motor.ensure_ptm_mode(timeout_s=0)
    runtime = [bytes(m.data) for m in dispatcher.sent if m.arbitration_id == 66]
    assert runtime == ([] if drop_read == 1 else [bytes.fromhex("fffffffffffffffd")])


@pytest.mark.parametrize("constructed_arm", [P7], indirect=True)
@pytest.mark.parametrize("backend", ["dispatcher", "cantransport"])
@pytest.mark.parametrize("joint", [66, 67])
@pytest.mark.parametrize("error_type", [StateError, TimeoutError])
def test_failed_mode_migration_closes_before_feedback_or_heartbeat(
    constructed_arm, monkeypatch, backend, joint, error_type
):
    cls, construct, events = constructed_arm
    module = importlib.import_module(cls.__module__)
    monkeypatch.setenv("LINKERBOT_ARM_TRANSPORT", backend)
    original = error_type("PTM initialization failed")

    def ensure(self, timeout_s=0.2):
        events.append(("ptm", self._id))
        if self._id == joint:
            raise original

    monkeypatch.setattr(module.MotorV2, "ensure_ptm_mode", ensure)
    before = set(threading.enumerate())
    with pytest.raises(error_type) as exc:
        construct("left")
    assert exc.value is original
    assert not set(threading.enumerate()) - before
    assert [event for event in events if event[0] == "ptm"] == [
        ("ptm", mid) for mid in range(66, joint + 1)
    ]
    assert not any(event[0] in ("initial", "poll") for event in events)
