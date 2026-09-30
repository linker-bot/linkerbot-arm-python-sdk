"""H75 public motion and brake lifecycle against real motor encoders."""

import importlib
import threading
from types import SimpleNamespace

import pytest

from linkerbot_arm import H75, ControlMode, Pose, StateError, ValidationError
from linkerbot_arm.arm.common.model import (
    AccelerationState,
    AngleState,
    TemperatureState,
    VelocityState,
)
from linkerbot_arm.arm.h75 import CurrentState, H75Motor, H75MotorConfig
from linkerbot_arm.motion_timer import MotionTimer
from tests.test_transport_frames import FakeDispatcher


@pytest.fixture
def arm():
    bus = FakeDispatcher()
    obj = H75.__new__(H75)
    obj._can_dispatcher = bus
    obj._motors = [H75Motor(mid, bus) for mid in range(61, 68)]
    for motor in obj._motors:
        motor._enabled = False
        motor._angle = AngleState(angle=0, timestamp=1)
        motor._control_angle = motor._angle
        motor._velocity = VelocityState(velocity=0, timestamp=1)
        motor._current = CurrentState(current=1, timestamp=1)
        motor._temperature = TemperatureState(temperature=25, timestamp=1)
        motor._control_acceleration = AccelerationState(acceleration=0.1, timestamp=1)
    obj._control_mode = None
    obj._motion_timer = MotionTimer()
    for motor in obj._motors:
        motor._parameter_lock = obj._motion_timer._lock
    obj._closed = obj._polling = obj._closing = False
    obj._close_lock = threading.Lock()
    obj._kx = SimpleNamespace(
        get_joint_limits=lambda: [(-3, 3)] * 7,
        forward_kinematics=lambda _: Pose(x=0, y=0, z=0, rx=0, ry=0, rz=0),
        plan_move_l=lambda *a, **k: [SimpleNamespace(angles=[0.01] * 7)],
    )
    yield obj
    obj._motion_timer.cancel()


def configure(arm):
    arm.set_velocities([0.1] * 7)
    arm.set_accelerations([0.15] * 7)
    arm.set_decelerations([0.2] * 7)
    arm.set_control_mode(ControlMode.PP)
    arm._can_dispatcher.sent.clear()


def frames(arm):
    return [(m.arbitration_id, bytes(m.data)) for m in arm._can_dispatcher.sent]


def test_public_identity():
    from linkerbot_arm.arm import H75 as ArmH75
    from linkerbot_arm.arm.h75 import H75 as ModelH75

    assert H75 is ArmH75 is ModelH75


def lifecycle_frames(arm):
    return [(mid, payload) for mid, payload in frames(arm) if payload != b"\x2b"]


def test_enable_and_brake_order(arm, monkeypatch):
    monkeypatch.setattr("linkerbot_arm.arm.h75.h75.time.sleep", lambda _: None)
    arm.enable()
    values = lifecycle_frames(arm)
    assert values[:7] == [(mid, b"\xfe") for mid in range(61, 68)]
    assert values[7:14] == [(mid, b"\x07\x06") for mid in range(61, 68)]
    assert values[14:21] == [(mid, b"\x2a\x01") for mid in range(61, 68)]
    assert values[21:] == [(61, b"\xf4\x01"), (62, b"\xf4\x01")]
    arm._can_dispatcher.sent.clear()
    arm.disable()
    assert lifecycle_frames(arm) == [(61, b"\xf4\x00"), (62, b"\xf4\x00")] + [
        (mid, b"\x2a\x00") for mid in range(61, 68)
    ]


@pytest.mark.parametrize("fail_at", [15, 21, 22])
def test_partial_enable_attempts_brakes_and_disable_preserving_error(arm, fail_at):
    bus = arm._can_dispatcher
    send = bus.send
    count = 0
    original = RuntimeError("enable interrupted")

    def fail(message):
        nonlocal count
        count += 1
        if count == fail_at:
            raise original
        send(message)

    bus.send = fail
    with pytest.raises(RuntimeError) as exc:
        arm.enable()
    assert exc.value is original
    assert lifecycle_frames(arm)[-9:] == [(61, b"\xf4\x00"), (62, b"\xf4\x00")] + [
        (mid, b"\x2a\x00") for mid in range(61, 68)
    ]
    assert all(not m.enabled for m in arm._motors)


def test_disable_attempts_other_joints_after_a_brake_failure(arm):
    bus = arm._can_dispatcher
    send = bus.send

    def fail(message):
        if message.arbitration_id == 61 and message.data == b"\xf4\x00":
            raise RuntimeError("brake failed")
        send(message)

    bus.send = fail
    with pytest.raises(RuntimeError, match="brake failed"):
        arm.disable()
    assert lifecycle_frames(arm)[-6:] == [(mid, b"\x2a\x00") for mid in range(62, 68)]
    assert (61, b"\x2a\x00") not in lifecycle_frames(arm)


def test_mode_requires_disabled_and_partial_write_becomes_unknown(arm):
    configure(arm)
    arm._motors[0]._enabled = True
    with pytest.raises(StateError, match="Disable"):
        arm.set_control_mode(ControlMode.CSP)
    assert not frames(arm)
    arm._motors[0]._enabled = False
    bus = arm._can_dispatcher
    send = bus.send

    def fail(message):
        if message.arbitration_id == 63:
            raise RuntimeError("mode write failed")
        send(message)

    bus.send = fail
    with pytest.raises(RuntimeError):
        arm.set_control_mode(ControlMode.CSP)
    assert arm._control_mode is None
    with pytest.raises(StateError, match="unknown"):
        arm._set_angles([0] * 7)


@pytest.mark.parametrize("method", ["home", "move_j", "move_p"])
def test_csp_does_not_pretend_to_provide_pp_motion(arm, method):
    arm.set_control_mode(ControlMode.CSP)
    arm._can_dispatcher.sent.clear()
    args = [] if method == "home" else [[0.1] * 7]
    with pytest.raises(StateError, match="require PP"):
        getattr(arm, method)(*args)
    assert not frames(arm)
    arm._set_angles([0.01] * 7)
    assert len(frames(arm)) == 7


def test_unknown_profile_rejects_point_motion_before_target(arm):
    arm.set_control_mode(ControlMode.PP)
    arm._can_dispatcher.sent.clear()
    with pytest.raises(StateError, match="unknown"):
        arm.move_j([0.1] * 7)
    assert not frames(arm)


def test_slow_deceleration_is_included_in_duration(arm, monkeypatch):
    configure(arm)
    arm.set_decelerations([0.01] * 7)
    durations = []
    monkeypatch.setattr(arm._motion_timer, "start", durations.append)
    arm.move_j([0.01] * 7, blocking=False)
    assert durations[0] == pytest.approx(2.0, abs=1e-4)


@pytest.mark.parametrize(
    "method",
    ["set_velocities", "set_accelerations", "set_decelerations", "set_position_kps"],
)
def test_invalid_last_parameter_changes_no_joint(arm, method):
    with pytest.raises(ValidationError):
        getattr(arm, method)([0.1] * 6 + [float("nan")])
    assert not frames(arm)


def test_snapshot_is_available_without_profiles_and_exposes_no_false_torque(arm):
    state = arm.get_state()
    assert state.joint_torques is None
    assert state.joint_control_velocities == []
    assert arm.get_currents() == [1] * 7
    assert arm.get_current_states()[0].timestamp == 1
    with pytest.raises(StateError, match="amperes"):
        arm.get_torques()


@pytest.mark.parametrize("mode", [ControlMode.PP, ControlMode.CSP])
def test_linear_motion_accepts_small_acceleration_and_restores_deceleration(arm, mode):
    configure(arm)
    arm.set_control_mode(mode)
    arm.set_accelerations([0.0001] * 7)
    arm.set_decelerations([0.002] * 7)
    saved = (
        arm.get_control_velocities(),
        arm.get_control_acceleration(),
        arm.get_control_decelerations(),
    )
    arm.move_l(Pose(x=0.01, y=0, z=0, rx=0, ry=0, rz=0))
    assert arm.get_control_velocities() == saved[0]
    assert arm.get_control_acceleration() == saved[1]
    assert arm.get_control_decelerations() == saved[2]
    assert not arm.is_moving()


def test_plan_failure_changes_no_profile_or_target(arm):
    configure(arm)

    def fail(*a, **k):
        raise RuntimeError("IK failed")

    arm._kx.plan_move_l = fail
    with pytest.raises(RuntimeError, match="IK failed"):
        arm.move_l(Pose(x=0.01, y=0, z=0, rx=0, ry=0, rz=0))
    assert not frames(arm)
    assert not arm.is_moving()


def test_cancel_linear_motion_restores_profiles_and_stops_new_targets(arm, monkeypatch):
    configure(arm)
    arm._kx.plan_move_l = lambda *a, **k: [
        SimpleNamespace(angles=[v] * 7) for v in (0.01, 0.02, 0.03)
    ]
    saved = arm.get_control_acceleration(), arm.get_control_decelerations()
    submit = arm._set_angles
    seen = []

    def stop(angles, **kwargs):
        seen.append(angles)
        submit(angles, **kwargs)
        arm.disable()

    monkeypatch.setattr(arm, "_set_angles", stop)
    arm.move_l(Pose(x=0.01, y=0, z=0, rx=0, ry=0, rz=0))
    assert len(seen) == 1
    assert arm.get_control_acceleration() == saved[0]
    assert arm.get_control_decelerations() == saved[1]
    assert not arm.is_moving()


def test_calibration_refuses_enabled_arm(arm):
    arm._motors[0]._enabled = True
    with pytest.raises(StateError, match="Disable"):
        arm.calibrate_zero()
    assert not frames(arm)


def test_precancelled_home_submits_no_target(arm):
    configure(arm)
    cancel = threading.Event()
    cancel.set()
    arm.home_cancellable(cancel)
    assert not frames(arm)


def test_config_validation_happens_before_opening_can(monkeypatch):
    module = importlib.import_module(H75.__module__)

    def unexpected(*a, **k):
        pytest.fail("must not open CAN")

    monkeypatch.setattr(module, "arm_dispatcher", unexpected)
    with pytest.raises(ValidationError):
        H75("left", "can0", motor_configs=[H75MotorConfig()])


def test_restore_deceleration_even_when_acceleration_restore_fails(arm, monkeypatch):
    configure(arm)
    old_deceleration = arm.get_control_decelerations()
    set_acceleration = arm.set_accelerations
    calls = 0

    def fail_second(values):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("acceleration restore failed")
        set_acceleration(values)

    monkeypatch.setattr(arm, "set_accelerations", fail_second)
    with pytest.raises(RuntimeError, match="acceleration restore failed"):
        arm.move_l(Pose(x=0.01, y=0, z=0, rx=0, ry=0, rz=0))
    assert arm.get_control_decelerations() == old_deceleration
    assert not arm.is_moving()


def test_original_motion_failure_survives_deceleration_restore_failure(
    arm, monkeypatch, caplog
):
    configure(arm)
    original = RuntimeError("target admission failed")

    def reject(*a, **k):
        raise original

    def fail_restore(*a, **k):
        raise RuntimeError("deceleration restore failed")

    monkeypatch.setattr(arm, "_set_angles", reject)
    monkeypatch.setattr(arm, "set_decelerations", fail_restore)
    with pytest.raises(RuntimeError) as exc:
        arm.move_l(Pose(x=0.01, y=0, z=0, rx=0, ry=0, rz=0))
    assert exc.value is original
    assert "deceleration restore failed" in caplog.text
    assert not arm.is_moving()


def test_mode_changed_during_ik_is_rechecked_before_point_admission(arm, monkeypatch):
    configure(arm)

    def solve(*a, **k):
        arm.set_control_mode(ControlMode.CSP)
        return [0.01] * 7

    monkeypatch.setattr(arm, "inverse_kinematics", solve)
    with pytest.raises(StateError, match="Disable"):
        arm.move_p(Pose(x=0.01, y=0, z=0, rx=0, ry=0, rz=0))
    assert not any(payload[0] == 0x0A for _, payload in frames(arm))


def test_enable_does_not_report_success_after_async_bus_fault(arm, monkeypatch):
    monkeypatch.setattr(
        "linkerbot_arm.arm.h75.h75.time.sleep", lambda _: setattr(arm, "_closed", True)
    )
    with pytest.raises(StateError, match="closed"):
        arm.enable()
    assert lifecycle_frames(arm)[-9:] == [(61, b"\xf4\x00"), (62, b"\xf4\x00")] + [
        (mid, b"\x2a\x00") for mid in range(61, 68)
    ]
