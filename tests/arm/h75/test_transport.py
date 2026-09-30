"""H75 routing, correlated reads, shared polling and atomic target admission."""

import math
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

import can
import pytest

from linkerbot_arm._transport.targets import submit_targets
from linkerbot_arm.arm.common.model import AngleState
from linkerbot_arm.arm.h75 import H75Motor, SensorType
from linkerbot_arm.arm.h75.iq24 import float_to_iq24_be
from linkerbot_arm.exceptions import StateError, TimeoutError
from tests.test_motion_batches import QueuedDispatcher
from tests.test_transport_frames import FakeDispatcher
from tests.test_transport_frames import link as link

pytestmark = pytest.mark.h75


def response(cmd=0x06, value=0.5):
    return can.Message(
        arbitration_id=61,
        is_extended_id=False,
        data=bytes([cmd]) + float_to_iq24_be(value),
    )


@pytest.mark.parametrize("cls", [H75Motor])
def test_position_wire_frame_on_both_backends(link, cls):
    dispatcher, receive, _ = link
    motor = cls(61, dispatcher)
    motor.set_angle(2 * math.pi / 100)
    frame = receive()
    assert frame.arbitration_id == 61 and not frame.is_extended_id
    assert bytes(frame.data) == bytes.fromhex("0a01000000")


@pytest.mark.parametrize("cls", [H75Motor])
def test_late_different_register_and_fast_reply(link, cls, monkeypatch):
    dispatcher, receive, feedback = link
    motor = cls(61, dispatcher)
    with pytest.raises(TimeoutError):
        motor._read_register(0x06, timeout_s=0)
    receive()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(motor._read_register, 0x05)
        assert receive() is not None
        feedback(response(0x06))
        assert not future.done()
        feedback(response(0x05, 0.25))
        assert future.result(1) == float_to_iq24_be(0.25)
    monkeypatch.setattr(
        dispatcher, "send", lambda message: motor._on_message(response(message.data[0]))
    )
    assert motor._read_register(0x06, timeout_s=0) == float_to_iq24_be(0.5)


@pytest.mark.parametrize(
    "invalid", ["motor", "command", "extended", "remote", "error", "fd", "short", "dlc"]
)
def test_invalid_reply_cannot_complete_read(invalid):
    dispatcher = FakeDispatcher()
    motor = H75Motor(61, dispatcher)
    frame = response()
    if invalid == "motor":
        frame.arbitration_id = 62
    elif invalid == "command":
        frame.data[0] = 5
    elif invalid == "extended":
        frame.is_extended_id = True
    elif invalid in ("remote", "error"):
        setattr(frame, f"is_{invalid}_frame", True)
    elif invalid == "fd":
        frame.is_fd = True
    elif invalid == "short":
        frame.data = frame.data[:3]
        frame.dlc = 3
    else:
        frame.dlc = 8
    dispatcher.send = lambda _: dispatcher.feedback(frame)
    with pytest.raises(TimeoutError):
        motor._read_register(6, timeout_s=0)
    dispatcher.send = lambda _: dispatcher.feedback(response())
    assert motor._read_register(6, timeout_s=0) == float_to_iq24_be(0.5)


def test_initial_state_keeps_unknown_profiles_separate_from_measured_speed():
    dispatcher = FakeDispatcher()
    motor = H75Motor(61, dispatcher)
    dispatcher.send = lambda message: dispatcher.feedback(
        response(message.data[0], 0.25)
    )
    motor.read_initial_state(timeout_s=0)
    assert motor.has_initial_data()
    assert motor.velocity.velocity > 0
    assert motor.current.current == pytest.approx(8.25)
    for name in ("control_velocity", "control_deceleration"):
        with pytest.raises(StateError, match="unknown"):
            getattr(motor, name)


def test_one_periodic_worker_for_seven_motors_and_no_orphan_waiters():
    dispatcher = FakeDispatcher()
    motors = [H75Motor(mid, dispatcher) for mid in range(61, 68)]
    before = set(threading.enumerate())
    received = threading.Event()
    seen = set()

    def send(message):
        frame = response(message.data[0])
        frame.arbitration_id = message.arbitration_id
        dispatcher.feedback(frame)
        seen.add(message.arbitration_id)
        if len(seen) == 7:
            received.set()

    dispatcher.send = send
    try:
        for motor in motors:
            motor.start_polling({SensorType.POSITION: 0.01})
        assert received.wait(1)
        workers = set(threading.enumerate()) - before
        assert len(workers) == 1
        assert next(iter(workers)).name == "LinkerbotArm.periodic"
    finally:
        for motor in motors:
            motor.stop_polling()
    assert not set(threading.enumerate()) - before
    assert all(not motor._get_relay(6)._waiters for motor in motors)


def test_rejected_seven_joint_batch_keeps_all_target_caches():
    dispatcher = QueuedDispatcher(capacity=7)
    motors = [H75Motor(mid, dispatcher) for mid in range(61, 68)]
    for motor in motors:
        motor._control_angle = AngleState(angle=0, timestamp=0)
    try:
        dispatcher.send(can.Message(arbitration_id=1))
        with pytest.raises(queue.Full):
            submit_targets(m._prepare_angle(0.1) for m in motors)
        assert [m.control_angle.angle for m in motors] == [0] * 7
        dispatcher._tx.drain()
        submit_targets(m._prepare_angle(0.1) for m in motors)
        assert [m.control_angle.angle for m in motors] == [0.1] * 7
        dispatcher._tx.drain()
        assert [m.arbitration_id for m in dispatcher.sent[1:]] == list(range(61, 68))
    finally:
        dispatcher._tx.close()
