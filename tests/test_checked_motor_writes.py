"""Physical send failures through both built-in CAN workers, without hardware."""

import threading
import time
import uuid

import can
import pytest

from linkerbot_arm import A7, P7, A7lite, CANError, TimeoutError
from linkerbot_arm._transport.can import ManagedCANDispatcher
from linkerbot_arm.arm.a7.motor import A7Motor
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.common import ControlMode
from linkerbot_arm.arm.common.model import AngleState, VelocityState
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from linkerbot_arm.comm.can import CANMessageDispatcher
from linkerbot_arm.motion_timer import MotionTimer
from tests.test_motion_batches import QueuedDispatcher


@pytest.fixture(params=["dispatcher", "cantransport"])
def connection(request):
    adapters, peers = [], []

    def create(kind):
        channel = "checked-motor-" + uuid.uuid4().hex
        peer = can.Bus(interface="virtual", channel=channel)
        peers.append(peer)
        model = {A7Motor: "a7", A7liteMotor: "a7_lite", MotorV2: "p7"}[kind]
        adapter = (
            CANMessageDispatcher(channel, "virtual")
            if request.param == "dispatcher"
            else ManagedCANDispatcher(channel, "virtual", model, "left")
        )
        adapters.append(adapter)
        backend = (
            adapter if request.param == "dispatcher" else adapter._transport._dispatcher
        )
        return adapter, backend, peer

    try:
        yield create
    finally:
        for adapter in adapters:
            adapter.stop()
            assert not adapter._recv_thread.is_alive()
            assert not adapter._tx.get_health().running
        for peer in peers:
            peer.shutdown()


WRITE_CASES = [
    (A7Motor, "enable", ()),
    (A7Motor, "disable", ()),
    (A7Motor, "reset_error", ()),
    (A7Motor, "calibrate_zero", ()),
    (A7Motor, "_save_params", ()),
    (A7Motor, "set_control_mode", (ControlMode.PP,)),
    (A7Motor, "set_velocity", (0.5,)),
    (A7Motor, "set_acceleration", (2.0,)),
    (A7Motor, "set_deceleration", (2.0,)),
    (A7Motor, "set_position_kp", (2.0,)),
    (A7Motor, "set_velocity_kp", (2.0,)),
    (A7Motor, "set_velocity_ki", (2.0,)),
    (A7liteMotor, "enable", ()),
    (A7liteMotor, "disable", ()),
    (A7liteMotor, "reset_error", ()),
    (A7liteMotor, "calibrate_zero", ()),
    (A7liteMotor, "_save_params", ()),
    (A7liteMotor, "start_reporting", ()),
    (A7liteMotor, "set_control_mode", (ControlMode.PP,)),
    (A7liteMotor, "set_limit_spd", (0.5,)),
    (A7liteMotor, "set_velocity", (0.5,)),
    (A7liteMotor, "set_acceleration", (2.0,)),
    (A7liteMotor, "set_position_kp", (2.0,)),
    (A7liteMotor, "set_velocity_kp", (2.0,)),
    (A7liteMotor, "set_velicity_ki", (2.0,)),
    (A7liteMotor, "set_velocity_filt_gain", (2.0,)),
    (MotorV2, "enable", ()),
    (MotorV2, "disable", ()),
    (MotorV2, "reset_error", ()),
    (MotorV2, "calibrate_zero", ()),
    (MotorV2, "_write_flash_param", (11, bytes(4))),
    (MotorV2, "_save_params", ()),
]


@pytest.mark.parametrize("kind,method,args", WRITE_CASES)
def test_physical_write_failure_raises_and_preserves_cache(
    connection, monkeypatch, kind, method, args
):
    adapter, backend, _ = connection(kind)
    motor = kind(67 if kind is MotorV2 else 61, adapter)
    motor._enabled = method != "enable"
    motor._angle = AngleState(angle=0.2, timestamp=1)
    motor._control_angle = AngleState(angle=0.1, timestamp=1)
    motor._control_velocity = VelocityState(velocity=0.1, timestamp=1)
    original = motor.__dict__.copy()
    attempted = []

    def fail(message, **kwargs):
        attempted.append(message)
        raise can.CanOperationError("physical write rejected")

    monkeypatch.setattr(backend._bus, "send", fail)
    with pytest.raises(CANError, match="physical write rejected"):
        getattr(motor, method)(*args)
    assert len(attempted) == 1
    if kind is MotorV2 and method == "enable":
        # Public caches stay unchanged, but unsafe idle holds stay paused.
        original["_heartbeat_ready"] = False
    assert motor.__dict__ == original
    # A single rejected frame must be reported even before the fatal threshold.
    assert adapter._tx.get_health().running


@pytest.mark.parametrize("kind", [A7Motor, A7liteMotor, MotorV2])
def test_cache_changes_only_after_physical_completion(connection, monkeypatch, kind):
    adapter, backend, _ = connection(kind)
    motor = kind(67 if kind is MotorV2 else 61, adapter)
    motor._enabled = False
    entered, release = threading.Event(), threading.Event()
    errors = []

    def blocked(message, **kwargs):
        entered.set()
        assert release.wait(2)

    def enable():
        try:
            motor.enable()
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(backend._bus, "send", blocked)
    worker = threading.Thread(target=enable)
    worker.start()
    try:
        assert entered.wait(1)
        assert worker.is_alive()
        assert motor._enabled is False
        release.set()
        worker.join(1)
        assert not worker.is_alive()
        assert errors == []
        if kind is not A7liteMotor:  # A7lite has no enabled cache.
            assert motor._enabled is True
    finally:
        release.set()
        worker.join(2)


@pytest.mark.parametrize(
    "arm_kind,motor_kind", [(A7, A7Motor), (A7lite, A7liteMotor), (P7, MotorV2)]
)
def test_group_disable_attempts_other_joints_and_reports_failure(
    connection, monkeypatch, arm_kind, motor_kind
):
    adapter, backend, _ = connection(motor_kind)
    arm = arm_kind.__new__(arm_kind)
    arm._motion_timer = MotionTimer()
    arm._motors = [motor_kind(mid, adapter) for mid in range(61, 68)]
    for motor in arm._motors:
        motor._enabled = True
    attempted = []

    def fail_third(message, **kwargs):
        mid = message.arbitration_id & 0xFF
        attempted.append(mid)
        if mid == 63:
            raise can.CanOperationError("third joint send failed")

    monkeypatch.setattr(backend._bus, "send", fail_third)
    with pytest.raises(CANError, match="third joint send failed"):
        arm.disable()
    assert attempted == list(range(61, 68))
    assert arm._motors[2]._enabled is True
    if motor_kind is not A7liteMotor:
        assert all(not m._enabled for i, m in enumerate(arm._motors) if i != 2)


@pytest.mark.parametrize("kind", [A7Motor, A7liteMotor, MotorV2])
def test_unstarted_lifecycle_timeout_expires_without_cache_change(kind):
    adapter = QueuedDispatcher()
    motor = kind(61, adapter)
    motor._enabled = True
    original = adapter._send_checked
    adapter._send_checked = lambda message: original(message, timeout_s=0.01)
    try:
        with pytest.raises(TimeoutError):
            motor.disable()
        adapter._tx.drain()
        assert adapter.sent == []
        assert motor._enabled is True
    finally:
        adapter._tx.close()


@pytest.mark.parametrize("kind", [A7Motor, A7liteMotor, MotorV2])
def test_motion_target_admission_stays_nonblocking(connection, monkeypatch, kind):
    adapter, backend, _ = connection(kind)
    motor = kind(67 if kind is MotorV2 else 61, adapter)
    entered, release = threading.Event(), threading.Event()

    def blocked(message, **kwargs):
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(backend._bus, "send", blocked)
    try:
        motor.set_angle(0.1)
        assert entered.wait(1)
        assert not motor._target_receipt.done()
        assert motor.control_angle.angle == 0.1
    finally:
        release.set()


@pytest.mark.parametrize(
    "kind,arm_kind", [(A7Motor, A7), (A7liteMotor, A7lite), (MotorV2, P7)]
)
def test_fatal_send_callback_does_not_deadlock_disable_motion_lock(
    connection, monkeypatch, kind, arm_kind
):
    adapter, backend, _ = connection(kind)
    arm = arm_kind.__new__(arm_kind)
    arm._motion_timer = MotionTimer()
    arm._motors = [kind(mid, adapter) for mid in range(61, 68)]
    adapter._on_bus_error = lambda error: arm._motion_timer.cancel()
    adapter.MAX_CONSECUTIVE_ERRORS = 1
    backend._max_consecutive_errors = 1

    def fail(message, **kwargs):
        raise can.CanOperationError("fatal physical write failure")

    monkeypatch.setattr(backend._bus, "send", fail)
    started = time.monotonic()
    with pytest.raises(CANError):
        arm.disable()
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize("kind", [A7Motor, A7liteMotor, MotorV2])
def test_close_wakes_lifecycle_waiter_while_backend_is_blocked(
    connection, monkeypatch, kind
):
    adapter, backend, _ = connection(kind)
    motor = kind(61, adapter)
    motor._enabled = True
    entered, release = threading.Event(), threading.Event()
    errors = []

    def blocked(message, **kwargs):
        entered.set()
        assert release.wait(2)

    def disable():
        try:
            motor.disable()
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(backend._bus, "send", blocked)
    worker = threading.Thread(target=disable)
    closer = threading.Thread(target=adapter.stop)
    worker.start()
    try:
        assert entered.wait(1)
        closer.start()
        worker.join(0.5)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], CANError)
        assert motor._enabled is True
    finally:
        release.set()
        worker.join(2)
        if closer.ident is not None:
            closer.join(3)
        assert not closer.is_alive()


def test_v2_heartbeat_after_enable_uses_new_hold_target(connection, monkeypatch):
    adapter, backend, _ = connection(MotorV2)
    motor = MotorV2(67, adapter)
    motor._angle = AngleState(angle=0.2, timestamp=1)
    motor._control_angle = AngleState(angle=0.1, timestamp=1)
    entered, release, heartbeat_started = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    sent, errors = [], []

    def blocked_enable(message, **kwargs):
        if bytes(message.data) == bytes.fromhex("fffffffffffffffc"):
            entered.set()
            assert release.wait(2)
        sent.append(bytes(message.data))

    def enable():
        try:
            motor.enable()
        except Exception as error:
            errors.append(error)

    def heartbeat():
        heartbeat_started.set()
        motor._heartbeat_once(None)

    monkeypatch.setattr(backend._bus, "send", blocked_enable)
    enabler = threading.Thread(target=enable)
    holder = threading.Thread(target=heartbeat)
    enabler.start()
    try:
        assert entered.wait(1)
        holder.start()
        assert heartbeat_started.wait(1)
        holder.join(0.5)
        assert not holder.is_alive()  # scheduler never waits on physical I/O
        assert sent == []
        release.set()
        enabler.join(1)
        motor._heartbeat_once(None)
        assert not enabler.is_alive() and not holder.is_alive()
        assert errors == []
        deadline = time.monotonic() + 1
        while len(sent) < 2 and time.monotonic() < deadline:
            time.sleep(0.001)
        assert sent == [
            bytes.fromhex("fffffffffffffffc"),
            motor._build_ptm_frame(0.2, 0.0),
        ]
    finally:
        release.set()
        enabler.join(2)
        if holder.ident is not None:
            holder.join(2)


def test_v2_target_admission_during_enable_stays_nonblocking(connection, monkeypatch):
    adapter, backend, _ = connection(MotorV2)
    motor = MotorV2(67, adapter)
    motor._angle = AngleState(angle=0.2, timestamp=1)
    motor._control_angle = AngleState(angle=0.1, timestamp=1)
    entered, release = threading.Event(), threading.Event()
    errors = []

    def blocked(message, **kwargs):
        if bytes(message.data) == bytes.fromhex("fffffffffffffffc"):
            entered.set()
            assert release.wait(2)

    def enable():
        try:
            motor.enable()
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(backend._bus, "send", blocked)
    worker = threading.Thread(target=enable)
    worker.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        motor.set_angle(0.3)
        assert time.monotonic() - started < 0.1
        assert not motor._target_receipt.done()
        release.set()
        worker.join(1)
        assert not worker.is_alive()
        assert errors == []
        assert motor.control_angle.angle == 0.3
        assert motor._pending_enables == 0
    finally:
        release.set()
        worker.join(2)
