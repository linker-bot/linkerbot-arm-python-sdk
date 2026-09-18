"""Concurrent queries use one worker without losing fast or delayed replies."""

import struct
import threading
import time

import can
import pytest

from linkerbot_arm.arm.a7.motor import A7Motor, SensorType
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.common.model import AngleState
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from linkerbot_arm.exceptions import ValidationError
from linkerbot_arm.periodic import PeriodicTask, scheduler_for
from linkerbot_arm.relay import DataRelay


class ReplyDispatcher:
    def __init__(self):
        self.callbacks = []
        self.sent = []
        self.quiet_ids = set()

    def subscribe(self, callback):
        self.callbacks.append(callback)

    def send(self, message):
        self.sent.append(message)
        if message.arbitration_id in self.quiet_ids or len(message.data) != 1:
            return
        # Deliver synchronously to expose the old send-before-wait race.
        reply = can.Message(
            arbitration_id=message.arbitration_id,
            is_extended_id=False,
            data=message.data + struct.pack("<f", 0.25),
        )
        for callback in self.callbacks:
            callback(reply)


def wait_for(predicate, timeout=1):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.001)


@pytest.mark.parametrize("model", ["a7", "p7"])
def test_one_worker_for_all_queries_and_heartbeats_with_a_silent_joint(model):
    dispatcher = ReplyDispatcher()
    motors = [A7Motor(i, dispatcher) for i in range(7 if model == "a7" else 5)]
    if model == "p7":
        motors += [MotorV2(i, dispatcher) for i in (5, 6)]
        for motor in motors[5:]:
            motor._control_angle = AngleState(angle=0.1, timestamp=0)
    dispatcher.quiet_ids.add(0)
    intervals = {sensor: 0.01 for sensor in SensorType}
    try:
        for motor in motors:
            motor.start_polling(intervals)
        scheduler = scheduler_for(dispatcher)
        worker = scheduler._thread
        wait_for(lambda: hasattr(motors[1], "_temperature"))
        assert worker.is_alive()
        assert len(scheduler._tasks) == 7
        assert all(
            not motor._poll_threads for motor in motors if isinstance(motor, A7Motor)
        )
        assert all(
            motor._heartbeat_thread is None
            for motor in motors
            if isinstance(motor, MotorV2)
        )
        before = len(dispatcher.sent)
        wait_for(lambda: len(dispatcher.sent) >= before + 20)
        assert motors[1].angle.angle == 0.25
        assert not hasattr(motors[0], "_angle")
        if model == "p7":
            assert {m.arbitration_id for m in dispatcher.sent if len(m.data) == 8} == {
                5,
                6,
            }
        # Reconfiguration replaces jobs instead of adding duplicate polling.
        for motor in motors:
            motor.start_polling({SensorType.POSITION: 0.02})
        assert scheduler._thread is worker
        assert sum(map(len, scheduler._tasks.values())) == 7
    finally:
        for motor in motors:
            motor.stop_polling()
    assert not worker.is_alive()
    assert all(
        not relay._waiters
        for motor in motors
        if isinstance(motor, A7Motor)
        for relay in motor._read_relays.values()
    )
    motors[1].start_polling({SensorType.POSITION: 0.01})
    try:
        assert scheduler._thread is not worker and scheduler._thread.is_alive()
    finally:
        scheduler.close()


def test_lite_reporting_does_not_create_a_query_scheduler():
    dispatcher = ReplyDispatcher()
    motors = [A7liteMotor(i, dispatcher) for i in range(7)]
    assert len(motors) == 7
    assert not hasattr(dispatcher, "_arm_periodic_scheduler")
    assert dispatcher.sent == []


def test_all_query_reads_capture_synchronous_responses():
    motor = A7Motor(1, ReplyDispatcher())
    assert motor._read_register_float(SensorType.POSITION, timeout_s=0) == 0.25


def test_nonblocking_relay_ownership_cancel_and_send_failure():
    relay = DataRelay()
    notified = threading.Event()
    pending = relay.try_request(lambda: None, notified.set)
    assert (
        relay.try_request(lambda: pytest.fail("busy relay sent twice"), notified.set)
        is None
    )
    relay.push(b"response")
    assert notified.is_set() and pending.done and pending.result() == b"response"
    pending.cancel()  # idempotent after result()
    pending = relay.try_request(lambda: None, notified.set)
    pending.cancel()
    assert not relay._waiters and not relay._notifications
    assert relay.request(lambda: relay.push(b"sync"), 0) == b"sync"

    def failed_send():
        raise RuntimeError("send failed")

    with pytest.raises(RuntimeError):
        relay.try_request(failed_send, notified.set)
    assert not relay._waiters and not relay._request_lock.locked()


def test_periodic_reservation_does_not_block_a_synchronous_reader():
    relay = DataRelay()
    started, release = threading.Event(), threading.Event()
    received = []

    def request():
        received.append(relay.request(started.set, 1))
        release.set()

    thread = threading.Thread(target=request)
    thread.start()
    assert started.wait(1)
    assert (
        relay.try_request(lambda: pytest.fail("overlapping read"), lambda: None) is None
    )
    relay.push(42)
    assert release.wait(1)
    thread.join(1)
    assert received == [42]


@pytest.mark.parametrize("interval", [0, -1, True, float("nan"), float("inf")])
def test_invalid_intervals_are_rejected_before_starting_threads(interval):
    with pytest.raises(ValidationError):
        PeriodicTask(interval, lambda notify: None)


def test_timeout_cadence_remains_timeout_plus_configured_interval():
    dispatcher = ReplyDispatcher()
    dispatcher.quiet_ids.add(1)
    motor = A7Motor(1, dispatcher)
    motor.start_polling({SensorType.POSITION: 0.1})
    try:
        wait_for(lambda: len(dispatcher.sent) == 1)
        time.sleep(0.13)
        assert len(dispatcher.sent) == 1
        wait_for(lambda: len(dispatcher.sent) == 2)
    finally:
        motor.stop_polling()


def test_close_seals_scheduler_and_releases_pending_relay():
    dispatcher = ReplyDispatcher()
    dispatcher.quiet_ids.add(1)
    motor = A7Motor(1, dispatcher)
    motor.start_polling({SensorType.POSITION: 1.0})
    wait_for(lambda: len(dispatcher.sent) == 1)
    scheduler = scheduler_for(dispatcher)
    scheduler.close()
    relay = motor._get_relay(int(SensorType.POSITION))
    assert not relay._request_lock.locked() and not relay._waiters
    with pytest.raises(RuntimeError, match="closed"):
        motor.start_polling({SensorType.POSITION: 1.0})


def test_concurrent_restart_and_stop_leave_no_duplicate_or_leaked_workers():
    dispatcher = ReplyDispatcher()
    motor = A7Motor(1, dispatcher)
    barrier = threading.Barrier(3)
    failures = []

    def cycle():
        try:
            barrier.wait(1)
            for _ in range(20):
                motor.start_polling({SensorType.POSITION: 0.01})
                motor.stop_polling()
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=cycle) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(1)
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    scheduler_for(dispatcher).close()
    assert failures == []
