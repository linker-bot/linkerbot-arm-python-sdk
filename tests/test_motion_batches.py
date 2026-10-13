"""Real motor encoders, whole-arm admission, age limits and heartbeat safety."""

import queue
import threading
import uuid
from types import SimpleNamespace

import can
import pytest
from linkerbot_transport import SendReceipt, TransmitArbiter, TransmitMode

from linkerbot_arm import A7, P7, A7lite, TimeoutError, ValidationError
from linkerbot_arm._transport.can import ManagedCANDispatcher
from linkerbot_arm._transport.targets import TargetQueueMixin
from linkerbot_arm.arm.a7.motor import A7Motor
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.common import ControlMode
from linkerbot_arm.arm.common.model import AccelerationState, AngleState, VelocityState
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from linkerbot_arm.comm.can import CANMessageDispatcher
from linkerbot_arm.motion_timer import MotionTimer


class QueuedDispatcher(TargetQueueMixin):
    def __init__(self, capacity=7, clock=None):
        self._init_target_queue()
        self.sent = []
        self._tx = TransmitArbiter(
            self.dispatch,
            fifo_capacity=capacity,
            mode=TransmitMode.CALLER,
            **({} if clock is None else {"monotonic": clock}),
        )
        self._tx.open(generation=1)

    def subscribe(self, callback):
        pass

    def send(self, message):
        self._tx.submit_fifo(message, endpoint_id="arm")

    def _submit_target_frames(self, frames, **options):
        return self._tx.submit_fifo_batch(frames, endpoint_id="arm", **options)

    def dispatch(self, message):
        self.sent.append(message)
        return SendReceipt.completed()


def make_arm(cls, dispatcher):
    arm = cls.__new__(cls)
    arm._can_dispatcher = dispatcher
    arm._motion_timer = MotionTimer()
    types = [A7liteMotor if cls is A7lite else A7Motor] * 7
    if cls is P7:
        types[5:] = [MotorV2, MotorV2]
    arm._motors = [motor_cls(51 + i, dispatcher) for i, motor_cls in enumerate(types)]
    for motor in arm._motors:
        motor._control_angle = AngleState(angle=0, timestamp=0)
        motor._angle = AngleState(angle=0, timestamp=0)
        motor._control_velocity = VelocityState(velocity=0.5, timestamp=0)
        motor._control_acceleration = AccelerationState(acceleration=1.0, timestamp=0)
    arm._kx = SimpleNamespace(get_joint_limits=lambda: [(-2, 2)] * 7)
    if cls is A7lite:
        arm._control_modes = None
    return arm


def command(arm, mode, values):
    if mode == "mit":
        arm._control_modes = [ControlMode.MIT] * 7
        arm.set_mits(values, kps=[10] * 7, kds=[1] * 7)
    elif mode == "mixed":
        arm._control_modes = [
            ControlMode.MIT,
            ControlMode.PP,
            ControlMode.CSP,
            ControlMode.PP,
            ControlMode.MIT,
            ControlMode.CSP,
            ControlMode.MIT,
        ]
        arm.stream_joint_targets(values, kps=[10] * 7, kds=[1] * 7)
    elif mode == "csp":
        arm._control_modes = [ControlMode.CSP] * 7
        arm.set_csp_angles(values)
    else:
        arm._set_angles(values)


MODELS = [
    (A7, "pp"),
    (P7, "pp"),
    (A7lite, "pp"),
    (A7lite, "mit"),
    (A7lite, "csp"),
    (A7lite, "mixed"),
]


@pytest.mark.parametrize("cls,mode", MODELS)
def test_seven_joint_capacity_rejection_changes_no_targets(cls, mode):
    dispatcher = QueuedDispatcher()
    arm = make_arm(cls, dispatcher)
    dispatcher.send(can.Message(arbitration_id=1))
    values = [0.1 * i for i in range(7)]
    try:
        with pytest.raises(queue.Full):
            command(arm, mode, values)
        assert arm.get_motion_health().queue.pending_fifo == 1
        assert [m.control_angle.angle for m in arm._motors] == [0] * 7
        assert all(getattr(m, "_mit_kp", None) is None for m in arm._motors)
        dispatcher._tx.drain()
        command(arm, mode, values)
        expected = [0.0] * 7 if cls is P7 else values
        assert [m.control_angle.angle for m in arm._motors] == expected
        assert arm.get_motion_health().queue.pending_fifo == 7
        dispatcher._tx.drain()
        health = arm.get_motion_health()
        assert health.last_frame_count == health.last_sent_frames == 7
        assert [m.arbitration_id & 0xFF for m in dispatcher.sent[1:]] == list(
            range(51, 58)
        )
    finally:
        dispatcher._tx.close()


@pytest.mark.parametrize("cls", [A7, A7lite, P7])
def test_late_joint_encoding_failure_sends_nothing(cls):
    dispatcher = QueuedDispatcher()
    arm = make_arm(cls, dispatcher)
    # A7/P7 final V1 joint float32 overflow; A7lite validates all registers.
    values = [0.2] * 7
    values[4] = 1e100
    try:
        with pytest.raises((OverflowError, ValidationError)):
            arm._set_angles(values, check_limits=False)
        assert dispatcher._tx.get_health().pending_fifo == 0
        assert [m.control_angle.angle for m in arm._motors] == [0] * 7
    finally:
        dispatcher._tx.close()


@pytest.mark.parametrize("cls,mode", MODELS)
def test_age_rejects_new_groups_and_expires_unstarted_groups(monkeypatch, cls, mode):
    now = [10.0]
    monkeypatch.setattr(
        "linkerbot_arm._transport.targets.time",
        SimpleNamespace(monotonic=lambda: now[0]),
    )
    dispatcher = QueuedDispatcher(capacity=21, clock=lambda: now[0])
    arm = make_arm(cls, dispatcher)
    arm.set_motion_queue_policy(max_target_age_s=0.05)
    try:
        command(arm, mode, [0.1] * 7)
        now[0] += 0.1
        with pytest.raises(TimeoutError):
            command(arm, mode, [0.2] * 7)
        expected = [0.0] * 7 if cls is P7 else [0.1] * 7
        assert [m.control_angle.angle for m in arm._motors] == expected
        dispatcher._tx.drain()
        health = arm.get_motion_health()
        assert dispatcher.sent == []
        assert health.queue.expired == health.queue.rejected_stale == 1
        assert health.last_sent_frames == 0 and health.last_error
        if cls is P7:
            for motor in arm._motors[5:]:
                motor._heartbeat_once(None)
            dispatcher._tx.drain()
            assert dispatcher.sent == []  # expired targets never revived
        arm.set_motion_queue_policy()  # original capacity-only FIFO
        command(arm, mode, [0.3] * 7)
        now[0] += 60
        dispatcher._tx.drain()
        assert len(dispatcher.sent) == 7
        assert arm.get_motion_health().last_error is None
    finally:
        dispatcher._tx.close()


def test_p7_heartbeat_is_ordered_with_concurrent_targets():
    dispatcher = QueuedDispatcher(capacity=30)
    arm = make_arm(P7, dispatcher)
    try:
        arm._set_angles([0.1] * 7)
        first_target = arm._motors[5].control_angle.angle
        arm._motors[5]._heartbeat_once(None)  # still pending: skip
        assert dispatcher._tx.get_health().pending_fifo == 7
        dispatcher._tx.drain()
        arm._motors[5]._heartbeat_once(None)
        arm._set_angles([0.2] * 7)
        arm._motors[5]._heartbeat_once(None)  # newer pending target: skip
        assert dispatcher._tx.get_health().pending_fifo == 8
        dispatcher._tx.drain()
        assert len(dispatcher.sent) == 15
        assert bytes(dispatcher.sent[7].data) == arm._motors[5]._build_ptm_frame(
            first_target, 0
        )
    finally:
        dispatcher._tx.close()


@pytest.mark.parametrize("backend", ["dispatcher", "cantransport"])
def test_real_backends_share_atomic_admission_and_close_cleanly(monkeypatch, backend):
    cls = CANMessageDispatcher if backend == "dispatcher" else ManagedCANDispatcher
    monkeypatch.setattr(cls, "SEND_QUEUE_SIZE", 8)
    name = "arm-batch-" + uuid.uuid4().hex
    dispatcher = (
        cls(name, "virtual")
        if backend == "dispatcher"
        else cls(name, "virtual", "a7", "right")
    )
    arm = make_arm(A7, dispatcher)
    started, release = threading.Event(), threading.Event()
    dispatch = dispatcher._tx._dispatch

    def blocked(message):
        started.set()
        assert release.wait(2)
        return dispatch(message)

    dispatcher._tx._dispatch = blocked
    try:
        dispatcher.send(can.Message(arbitration_id=1))
        assert started.wait(1)
        dispatcher.send(can.Message(arbitration_id=2))
        dispatcher.send(can.Message(arbitration_id=3))
        with pytest.raises(queue.Full):
            arm._set_angles([0.1] * 7)
        assert [m.control_angle.angle for m in arm._motors] == [0] * 7
        assert dispatcher.get_motion_health().queue.pending_fifo == 2
    finally:
        release.set()
        dispatcher.stop()
    assert dispatcher._tx._worker is None
    with pytest.raises(RuntimeError):
        arm._set_angles([0.1] * 7)


@pytest.mark.parametrize("budget", [True, 0, -1, float("nan"), float("inf"), "0.1"])
def test_invalid_age_budget_rejected(budget):
    dispatcher = QueuedDispatcher()
    try:
        with pytest.raises(ValidationError):
            dispatcher.set_motion_queue_policy(max_target_age_s=budget)
    finally:
        dispatcher._tx.close()


def test_unsupported_transport_source_fails_before_opening_can(monkeypatch):
    from linkerbot_arm import StateError

    monkeypatch.delattr(TransmitArbiter, "submit_fifo_batch")
    monkeypatch.setattr(
        can, "Bus", lambda **kwargs: pytest.fail("opened CAN before capability check")
    )
    for factory in (
        lambda: CANMessageDispatcher("unused"),
        lambda: ManagedCANDispatcher("unused", "socketcan", "a7", "left"),
    ):
        with pytest.raises(StateError, match="requirements/transport.txt"):
            factory()


@pytest.mark.parametrize("cls", [A7, A7lite, P7])
def test_concurrent_producers_never_interleave_joint_groups(cls):
    dispatcher = QueuedDispatcher(capacity=140)
    arm = make_arm(cls, dispatcher)
    barrier = threading.Barrier(3)
    failures = []

    def submit(value):
        try:
            barrier.wait(1)
            for _ in range(10):
                arm._set_angles([value] * 7)
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=submit, args=(value,)) for value in (0.1, 0.2)]
    for thread in threads:
        thread.start()
    barrier.wait(1)
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    try:
        assert failures == []
        assert len({motor.control_angle.angle for motor in arm._motors}) == 1
        dispatcher._tx.drain()
        assert len(dispatcher.sent) == 140
        for index in range(0, 140, 7):
            group = dispatcher.sent[index : index + 7]
            assert [frame.arbitration_id & 0xFF for frame in group] == list(
                range(51, 58)
            )
            # Motors of the same protocol must all carry the same target bytes.
            assert len({bytes(frame.data) for frame in group[:5]}) == 1
    finally:
        dispatcher._tx.close()


@pytest.mark.parametrize("close_in_callback", [False, True])
def test_legacy_fatal_send_aborts_pending_work_and_allows_callback_close(
    monkeypatch, close_in_callback
):
    from linkerbot_arm import CANError

    notified = threading.Event()
    faults = []

    def on_error(error):
        faults.append(error)
        if close_in_callback:
            dispatcher.stop()
        notified.set()

    dispatcher = CANMessageDispatcher(
        "fault-" + uuid.uuid4().hex,
        "virtual",
        on_bus_error=on_error,
        max_consecutive_errors=1,
    )
    arm = make_arm(A7, dispatcher)

    def fail(message, **kwargs):
        raise OSError("simulated backend write failure")

    monkeypatch.setattr(dispatcher._bus, "send", fail)
    try:
        arm._set_angles([0.1] * 7)
        assert notified.wait(1)
        dispatcher._tx._worker.join(1)
        assert not dispatcher._tx._worker.is_alive()
        health = arm.get_motion_health()
        assert health.last_sent_frames == 0 and health.last_error
        assert not health.queue.running and health.queue.pending_total == 0
        assert len(faults) == 1
        with pytest.raises(CANError):
            arm._set_angles([0.2] * 7)
    finally:
        dispatcher.stop()


def test_legacy_close_interrupts_backend_before_retrying_transmit_join(monkeypatch):
    monkeypatch.setattr("linkerbot_transport.can.can.THREAD_JOIN_TIMEOUT_S", 0.02)
    dispatcher = CANMessageDispatcher("blocked-" + uuid.uuid4().hex, "virtual")
    dispatcher._tx._join_timeout_s = 0.02
    entered, release = threading.Event(), threading.Event()
    shutdown = dispatcher._bus.shutdown

    def block(message, **kwargs):
        entered.set()
        assert release.wait(1)

    def close():
        release.set()
        shutdown()

    monkeypatch.setattr(dispatcher._bus, "send", block)
    monkeypatch.setattr(dispatcher._bus, "shutdown", close)
    try:
        make_arm(A7, dispatcher)._set_angles([0.1] * 7)
        assert entered.wait(1)
        dispatcher.stop()
        assert dispatcher._tx._worker is None
        assert not dispatcher._recv_thread.is_alive()
        assert dispatcher.get_motion_health().last_sent_frames == 1
    finally:
        release.set()
        dispatcher.stop()
