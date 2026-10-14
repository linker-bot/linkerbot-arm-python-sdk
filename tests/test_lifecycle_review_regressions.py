"""Lifecycle completion ordering and safe heartbeat recovery without hardware."""

import threading

import can
import pytest

from linkerbot_arm import A7, P7, CANError, TimeoutError
from linkerbot_arm.arm.a7.motor import A7Motor
from linkerbot_arm.arm.common.model import AngleState
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from linkerbot_arm.motion_timer import MotionTimer
from tests.test_checked_motor_writes import connection as connection


class ContendedLock:
    """Observe an actual competing lifecycle acquisition without sleeps."""

    def __init__(self, lock):
        self.lock = lock
        self.contended = threading.Event()

    def __enter__(self):
        if self.lock.locked():
            self.contended.set()
        self.lock.acquire()
        return self

    def __exit__(self, *args):
        self.lock.release()


def lifecycle_frame(kind, operation):
    if kind is A7Motor:
        return bytes([0x2A, operation == "enable"])
    return bytes([0xFF] * 7 + [0xFC if operation == "enable" else 0xFD])


def test_inflight_enable_timeout_keeps_heartbeat_paused_until_recovery(
    connection, monkeypatch
):
    adapter, backend, _ = connection(MotorV2)
    motor = MotorV2(67, adapter)
    motor._angle = AngleState(angle=0.8, timestamp=1)
    motor._control_angle = AngleState(angle=-0.4, timestamp=1)
    entered, release, recovered_hold = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    enter_frame = lifecycle_frame(MotorV2, "enable")
    physical = []

    def slow_backend(message, **kwargs):
        data = bytes(message.data)
        if data == enter_frame and not entered.is_set():
            entered.set()
            assert release.wait(3)
        physical.append(data)
        if data == motor._build_ptm_frame(0.8, 0.0):
            recovered_hold.set()

    monkeypatch.setattr(backend._bus, "send", slow_backend)
    try:
        # Keep the production one-second timeout and model a backend ignoring
        # its shorter send timeout. The enable has already started physically.
        with pytest.raises(TimeoutError):
            motor.enable()
        assert entered.is_set()
        assert motor._pending_enables == 0
        assert motor.enabled is False
        motor._heartbeat_once(None)
        assert adapter._tx.get_health().pending_fifo == 0
        release.set()

        # A newer explicit target still admits without reopening idle holds.
        motor.set_angle(0.6)
        motor._target_receipt.result(timeout=1)
        motor._heartbeat_once(None)
        assert adapter._tx.get_health().pending_fifo == 0
        assert physical == [enter_frame, motor._build_ptm_frame(0.6, 0.0)]
        assert not motor._heartbeat_ready

        motor.enable()
        assert motor.enabled is True
        assert motor.control_angle.angle == 0.8
        motor._heartbeat_once(None)
        assert recovered_hold.wait(1)
        assert physical == [
            enter_frame,
            motor._build_ptm_frame(0.6, 0.0),
            enter_frame,
            motor._build_ptm_frame(0.8, 0.0),
        ]
    finally:
        release.set()


@pytest.mark.parametrize("error", [CANError("enable rejected"), KeyboardInterrupt()])
def test_enable_error_or_interrupt_requires_explicit_recovery(
    connection, monkeypatch, error
):
    adapter, _, _ = connection(MotorV2)
    motor = MotorV2(67, adapter)
    motor._angle = AngleState(angle=0.8, timestamp=1)
    previous_target = motor._control_angle = AngleState(angle=-0.4, timestamp=1)

    def fail(data):
        raise error

    monkeypatch.setattr(motor, "_send_control", fail)
    with pytest.raises(type(error)):
        motor.enable()
    accepted = adapter._tx.get_health().accepted
    motor._heartbeat_once(None)
    assert adapter._tx.get_health().accepted == accepted
    assert motor._control_angle is previous_target
    assert motor.enabled is False
    assert motor._pending_enables == 0
    assert not motor._lifecycle_lock.locked()


@pytest.mark.parametrize("kind", [A7Motor, MotorV2])
@pytest.mark.parametrize("first,second", [("enable", "disable"), ("disable", "enable")])
def test_lifecycle_cache_follows_serialized_physical_order(
    connection, monkeypatch, kind, first, second
):
    adapter, backend, _ = connection(kind)
    motor = kind(67 if kind is MotorV2 else 61, adapter)
    motor._enabled = first == "disable"
    motor._angle = AngleState(angle=0.8, timestamp=1)
    motor._control_angle = AngleState(angle=-0.4, timestamp=1)
    gate = motor._lifecycle_lock = ContendedLock(motor._lifecycle_lock)
    first_sent, resume = threading.Event(), threading.Event()
    physical, errors = [], []
    original = adapter._send_checked
    first_frame = lifecycle_frame(kind, first)

    def delayed_completion(message):
        original(message)
        if bytes(message.data) == first_frame:
            first_sent.set()
            assert resume.wait(2)

    def physical_send(message, **kwargs):
        physical.append(bytes(message.data))

    def run(operation):
        try:
            getattr(motor, operation)()
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(adapter, "_send_checked", delayed_completion)
    monkeypatch.setattr(backend._bus, "send", physical_send)
    owner = threading.Thread(target=run, args=(first,))
    follower = threading.Thread(target=run, args=(second,))
    owner.start()
    try:
        assert first_sent.wait(1)
        follower.start()
        assert gate.contended.wait(1)
        assert physical == [first_frame]
        assert follower.is_alive()
        resume.set()
        owner.join(1)
        follower.join(1)
        assert not owner.is_alive() and not follower.is_alive()
        assert errors == []
        assert physical == [first_frame, lifecycle_frame(kind, second)]
        assert motor.enabled is (second == "enable")
    finally:
        resume.set()
        owner.join(2)
        if follower.ident is not None:
            follower.join(2)


@pytest.mark.parametrize("kind,arm_kind", [(A7Motor, A7), (MotorV2, P7)])
def test_fatal_send_releases_lifecycle_lock_before_arm_fault_callback(
    connection, monkeypatch, kind, arm_kind
):
    adapter, backend, _ = connection(kind)
    motor = kind(67 if kind is MotorV2 else 61, adapter)
    motor._enabled = True
    arm = arm_kind.__new__(arm_kind)
    arm._motion_timer = MotionTimer()
    arm._motors = [motor]
    gate = motor._lifecycle_lock = ContendedLock(motor._lifecycle_lock)
    adapter._on_bus_error = lambda error: arm._motion_timer.cancel()
    adapter.MAX_CONSECUTIVE_ERRORS = 1
    backend._max_consecutive_errors = 1
    entered, release = threading.Event(), threading.Event()
    errors = []

    def fail(message, **kwargs):
        entered.set()
        assert release.wait(2)
        raise can.CanOperationError("fatal physical write failure")

    def run(action):
        try:
            action()
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(backend._bus, "send", fail)
    enabler = threading.Thread(target=run, args=(motor.enable,))
    disabler = threading.Thread(target=run, args=(arm.disable,))
    enabler.start()
    try:
        assert entered.wait(1)
        disabler.start()
        assert gate.contended.wait(1)
        release.set()
        enabler.join(1)
        disabler.join(1)
        assert not enabler.is_alive() and not disabler.is_alive()
        assert len(errors) == 2 and all(isinstance(e, CANError) for e in errors)
        assert motor.enabled is True
    finally:
        release.set()
        enabler.join(2)
        if disabler.ident is not None:
            disabler.join(2)
