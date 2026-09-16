"""Exercise mode transitions and validate complete commands before sending."""

import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from linkerbot_arm import A7lite, ControlMode, StateError, ValidationError
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.motion_timer import MotionTimer


@pytest.fixture
def device():
    dispatcher = Mock()
    arm = A7lite.__new__(A7lite)
    arm._motors = [A7liteMotor(i, dispatcher) for i in range(61, 68)]
    arm._control_modes = None
    arm._kx = SimpleNamespace(get_joint_limits=lambda: [(-1.0, 1.0)] * 7)
    arm._motion_timer = MotionTimer()
    yield arm, dispatcher
    arm._motion_timer.cancel()


def messages(dispatcher):
    return [call.args[0] for call in dispatcher.send.call_args_list]


@pytest.mark.parametrize(
    "values,arbitration_id,payload",
    [
        ((-12.57, -33.0, 0.0, 0.0, -14.0), 0x0100003D, "0000000000000000"),
        ((12.57, 33.0, 500.0, 5.0, 14.0), 0x01FFFF3D, "ffffffffffffffff"),
        ((0.0, 0.0, 20.0, 1.0, 0.0), 0x017FFF3D, "7fff7fff0a3d3333"),
    ],
)
def test_mit_protocol_golden_frames(device, values, arbitration_id, payload):
    arm, dispatcher = device
    arm._motors[0].set_mit(*values)
    (msg,) = messages(dispatcher)
    assert msg.arbitration_id == arbitration_id
    assert bytes(msg.data) == bytes.fromhex(payload)
    assert msg.is_extended_id and not msg.is_fd


def test_mode_transition_stops_all_joints_before_writing_modes(device):
    arm, dispatcher = device
    modes = [ControlMode.MIT, ControlMode.CSP] + [ControlMode.PP] * 5
    arm.set_control_modes(modes)
    sent = messages(dispatcher)
    assert [m.arbitration_id for m in sent[:7]] == [
        0x0400FD00 | i for i in range(61, 68)
    ]
    assert [m.arbitration_id for m in sent[7:]] == [
        0x1200FD00 | i for i in range(61, 68)
    ]
    assert [bytes(m.data) for m in sent[:7]] == [bytes(8)] * 7
    assert [struct.unpack("<HHI", bytes(m.data)) for m in sent[7:]] == [
        (0x7005, 0, value) for value in [0, 5, 1, 1, 1, 1, 1]
    ]
    modes[0] = ControlMode.PP
    snapshot = arm.control_modes
    snapshot[1] = ControlMode.PP
    assert arm.control_modes[:2] == [ControlMode.MIT, ControlMode.CSP]


@pytest.mark.parametrize(
    "modes,error",
    [
        ([ControlMode.PP] * 6, ValueError),
        ([ControlMode.PP] * 6 + ["MIT"], ValidationError),
    ],
)
def test_invalid_modes_do_not_stop_or_reconfigure_any_motor(device, modes, error):
    arm, dispatcher = device
    with pytest.raises(error):
        arm.set_control_modes(modes)
    dispatcher.send.assert_not_called()
    assert arm.control_modes is None


@pytest.mark.parametrize("mode", [None, ControlMode.MIT, ControlMode.CSP])
def test_enable_defaults_to_pp_or_preserves_selected_mode(device, monkeypatch, mode):
    arm, dispatcher = device
    monkeypatch.setattr("linkerbot_arm.arm.a7_lite.a7_lite.time.sleep", lambda _: None)
    if mode is not None:
        arm.set_control_mode(mode)
        dispatcher.reset_mock()
    arm.enable()
    assert arm.control_modes == [mode or ControlMode.PP] * 7
    sent = messages(dispatcher)
    assert len(sent) == 28  # reset, stop, write mode, enable
    assert [m.arbitration_id >> 24 for m in sent] == [4] * 14 + [18] * 7 + [3] * 7


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("set_mits", {"kps": [20.0] * 7, "kds": [1.0] * 7}),
        ("set_csp_angles", {}),
        ("stream_joint_targets", {}),
    ],
)
def test_streaming_requires_matching_explicit_mode(device, method, kwargs):
    arm, dispatcher = device
    with pytest.raises(StateError):
        getattr(arm, method)([0.0] * 7, **kwargs)
    dispatcher.send.assert_not_called()


def test_mit_rejects_legacy_register_angle_command(device):
    arm, dispatcher = device
    arm._control_modes = [ControlMode.MIT] + [ControlMode.PP] * 6
    with pytest.raises(StateError):
        arm._set_angles([0.0] * 7)
    dispatcher.send.assert_not_called()


@pytest.mark.parametrize("bad", [-0.1, 33.1, float("nan"), float("inf")])
def test_invalid_last_csp_speed_sends_no_partial_command(device, bad):
    arm, dispatcher = device
    with pytest.raises(ValidationError):
        arm.set_limit_spds([2.0] * 6 + [bad])
    dispatcher.send.assert_not_called()


@pytest.mark.parametrize(
    "field,bad",
    [
        ("positions", 12.58),
        ("velocities", 33.1),
        ("kps", 501.0),
        ("kds", 5.1),
        ("torques", 14.1),
        ("kps", float("nan")),
    ],
)
def test_invalid_last_mit_joint_sends_no_partial_command(device, field, bad):
    arm, dispatcher = device
    arm._control_modes = [ControlMode.MIT] * 7
    values = {
        "positions": [0.0] * 7,
        "velocities": [0.0] * 7,
        "kps": [20.0] * 7,
        "kds": [1.0] * 7,
        "torques": [0.0] * 7,
    }
    values[field][-1] = bad
    with pytest.raises(ValidationError):
        arm.set_mits(**values, check_limits=False)
    dispatcher.send.assert_not_called()


def test_csp_stream_and_speed_limit_use_separate_registers(device):
    arm, dispatcher = device
    arm._control_modes = [ControlMode.CSP] * 7
    arm.set_limit_spds([2.0] * 7)
    arm.set_csp_angles([0.25] * 7)
    assert arm.get_limit_spds() == [2.0] * 7
    assert [struct.unpack("<HHf", bytes(m.data)) for m in messages(dispatcher)] == (
        [(0x7017, 0, 2.0)] * 7 + [(0x7016, 0, 0.25)] * 7
    )
    assert not arm.is_moving()


def test_mixed_stream_enforces_joint_limits_before_any_send(device):
    arm, dispatcher = device
    arm._control_modes = [ControlMode.MIT, ControlMode.CSP] + [ControlMode.PP] * 5
    with pytest.raises(ValidationError):
        arm.stream_joint_targets([0.0] * 6 + [1.1])
    dispatcher.send.assert_not_called()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 1e100, "invalid"])
@pytest.mark.parametrize("method", ["stream_joint_targets", "set_csp_angles"])
def test_invalid_float32_target_never_partially_sends(device, bad, method):
    arm, dispatcher = device
    arm._control_modes = [ControlMode.CSP] * 7
    if method == "stream_joint_targets":
        arm._control_modes[0] = ControlMode.MIT
    with pytest.raises(ValidationError):
        getattr(arm, method)([0.0] * 6 + [bad], check_limits=False)
    dispatcher.send.assert_not_called()
