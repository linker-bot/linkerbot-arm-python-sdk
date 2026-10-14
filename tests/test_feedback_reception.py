"""Delayed callbacks and queued frames must retain original reception time."""

import threading
import time
from unittest.mock import Mock

import pytest

from linkerbot_arm import ArmFeedback
from linkerbot_arm._transport.reception import feedback_received_at, reception_time
from linkerbot_arm.arm.a7.motor import A7Motor, SensorType
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from tests import test_managed_can
from tests.test_checked_motor_writes import connection as connection
from tests.test_feedback_freshness import frame

managed_connection = test_managed_can.connection


def frames(kind, mid):
    if kind is A7Motor:
        messages = []
        for cmd in (SensorType.POSITION, SensorType.VELOCITY, SensorType.TORQUE):
            message = frame(kind, mid)
            message.data[0] = cmd
            messages.append(message)
        return messages
    return [frame(kind, mid)]


@pytest.mark.parametrize("kind", [A7Motor, A7liteMotor, MotorV2])
def test_slow_subscriber_does_not_refresh_later_decoder(connection, kind):
    adapter, _, peer = connection(kind)
    mid = 67 if kind is MotorV2 else 61
    entered, release = threading.Event(), threading.Event()
    original_times = []
    done = threading.Event()

    def slow(message):
        original_times.append(feedback_received_at())
        entered.set()
        assert release.wait(2)

    adapter.subscribe(slow)
    motor = kind(mid, adapter)
    adapter.subscribe(lambda message: done.set())
    try:
        for message in frames(kind, mid):
            done.clear()
            entered.clear()
            release.clear()
            peer.send(message)
            assert entered.wait(1)
            # Hold a subscriber past the freshness budget before decoding.
            assert not release.wait(0.03)
            release.set()
            assert done.wait(1)
        sample = motor._feedback
        assert sample.angle_received_at == original_times[0]
        assert (
            sample.velocity_received_at == original_times[1 if kind is A7Motor else 0]
        )
        assert sample.torque_received_at == original_times[2 if kind is A7Motor else 0]
        assert not ArmFeedback((sample,), True).is_fresh(0.01)
    finally:
        release.set()


@pytest.mark.parametrize(
    "kind,model,mid",
    [(A7Motor, "a7", 61), (A7liteMotor, "a7_lite", 61), (MotorV2, "p7", 67)],
)
def test_managed_queue_retains_route_receive_time(managed_connection, kind, model, mid):
    adapter, backend = managed_connection(model)
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    expected = frames(kind, mid)
    delivered = []

    def block_once(message):
        if not entered.is_set():
            entered.set()
            assert release.wait(2)

    adapter.subscribe(block_once)
    motor = kind(mid, adapter)

    def observe(message):
        delivered.append(message)
        if len(delivered) == len(expected) + 1:
            done.set()

    adapter.subscribe(observe)
    try:
        # Block RX on an earlier frame, then queue measurements behind it.
        backend.emit(expected[0])
        assert entered.wait(1)
        adapter._transport._receive_router._monotonic = lambda: 50.0
        for message in expected:
            backend.emit(message)
        assert adapter._route.get_health().queue_depth == len(expected)
        release.set()
        assert done.wait(1)
        sample = motor._feedback
        assert (
            sample.angle_received_at,
            sample.velocity_received_at,
            sample.torque_received_at,
        ) == (50.0, 50.0, 50.0)
        assert not ArmFeedback((sample,), True).is_fresh(0.5, now=50.6)
    finally:
        release.set()


@pytest.mark.parametrize("kind", [A7Motor, A7liteMotor, MotorV2])
def test_reception_scope_is_nested_and_restored_after_failure(kind, monkeypatch):
    motor = kind(61, Mock())
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)
    with reception_time(10.0):
        with pytest.raises(RuntimeError):
            with reception_time(20.0):
                motor._on_message(frames(kind, 61)[0])
                assert motor._feedback.angle_received_at == 20.0
                raise RuntimeError("callback failed")
        motor._on_message(frames(kind, 61)[0])
        assert motor._feedback.angle_received_at == 10.0
    motor._on_message(frames(kind, 61)[0])
    assert motor._feedback.angle_received_at == 100.0
