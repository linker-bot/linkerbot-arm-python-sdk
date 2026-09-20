"""Bounded read-only startup probing; no physical CAN bus is opened."""

import struct
import threading
import uuid
from collections import Counter
from types import SimpleNamespace

import can
import pytest

from linkerbot_arm import A7, P7, A7lite
from linkerbot_arm._transport.can import ManagedCANDispatcher
from linkerbot_arm.arm.a7.motor import A7Motor
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.common import _discovery
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from linkerbot_arm.comm.can import CANMessageDispatcher
from linkerbot_arm.exceptions import StateError


@pytest.mark.parametrize("cls", [A7, A7lite, P7])
@pytest.mark.parametrize("backend", ["cantransport", "dispatcher"])
@pytest.mark.parametrize("scenario", ["delayed", "retry", "offline"])
def test_probe_delayed_or_missing_joint_on_both_backends(cls, backend, scenario):
    channel = "arm-discovery-" + uuid.uuid4().hex
    model = {A7: "a7", A7lite: "a7_lite", P7: "p7"}[cls]
    # Include P7's V2 joint, not only its shared A7 motors.
    affected = 66 if cls is P7 else 63
    stop = threading.Event()
    counts = Counter()
    failures = []
    timers = []
    with can.Bus(interface="virtual", channel=channel) as peer:
        factory = (
            ManagedCANDispatcher(channel, "virtual", model, "left")
            if backend == "cantransport"
            else CANMessageDispatcher(channel, "virtual")
        )
        with factory as dispatcher:
            arm = cls.__new__(cls)
            arm._motors = [
                (
                    A7liteMotor
                    if cls is A7lite
                    else MotorV2
                    if cls is P7 and mid >= 66
                    else A7Motor
                )(mid, dispatcher)
                for mid in range(61, 68)
            ]

            def respond():
                try:
                    while not stop.is_set():
                        message = peer.recv(0.01)
                        if message is None:
                            continue
                        if cls is A7lite:
                            assert message.arbitration_id >> 24 == 17
                            mid = message.arbitration_id & 0xFF
                            reply = can.Message(
                                arbitration_id=(17 << 24) | (mid << 8) | 0xFD,
                                is_extended_id=True,
                                data=message.data[:4] + struct.pack("<f", 0.25),
                            )
                        elif message.arbitration_id >= 0x600:
                            assert message.data[6] == 4  # Flash READ, never WRITE
                            mid = message.arbitration_id - 0x600
                            reply = can.Message(
                                arbitration_id=message.arbitration_id,
                                is_extended_id=False,
                                data=bytes([mid, message.data[1], 1, 0, 0, 0, 0, 255]),
                            )
                        else:
                            assert len(message.data) == 1
                            mid = message.arbitration_id
                            reply = can.Message(
                                arbitration_id=mid,
                                is_extended_id=False,
                                data=message.data[:1] + struct.pack("<f", 0.25),
                            )
                        counts[mid] += 1
                        if mid == affected:
                            if scenario == "offline" or (
                                scenario == "retry" and counts[mid] == 1
                            ):
                                continue
                            if scenario == "delayed":
                                timer = threading.Timer(0.04, peer.send, args=(reply,))
                                timers.append(timer)
                                timer.start()
                                continue
                        peer.send(reply)
                except BaseException as error:
                    failures.append(error)

            worker = threading.Thread(target=respond)
            worker.start()
            try:
                if scenario == "offline":
                    with pytest.raises(
                        StateError, match=f"Left arm joint {affected - 60} .*{affected}"
                    ):
                        arm._check_motors()
                else:
                    arm._check_motors()
            finally:
                stop.set()
                worker.join(1)
                for timer in timers:
                    timer.join(1)
            assert not worker.is_alive() and not failures
            assert counts == Counter(
                {
                    mid: 2 if mid == affected and scenario != "delayed" else 1
                    for mid in range(61, 68)
                }
            )


@pytest.mark.parametrize("side,first", [("left", 61), ("right", 51)])
def test_all_offline_have_bounded_budget_and_joint_diagnostics(
    monkeypatch, side, first
):
    clock = [0.0]
    monkeypatch.setattr(_discovery.time, "monotonic", lambda: clock[0])
    waits = []

    def offline(timeout_s):
        waits.append(timeout_s)
        clock[0] += timeout_s
        return False

    motors = [
        SimpleNamespace(_id=mid, check_alive=offline) for mid in range(first, first + 7)
    ]
    with pytest.raises(StateError) as exc:
        _discovery.check_motors(motors)
    assert clock[0] == pytest.approx(2.1)
    assert waits == [0.1] * 7 + [0.2] * 7
    assert "Expected 7 joints, 0 responded" in str(exc.value)
    for i in range(7):
        assert f"{side.title()} arm joint {i + 1} (CAN ID {first + i})" in str(
            exc.value
        )
        assert f"{first + i}=2" in str(exc.value)


def test_deadline_clips_wait_and_stops_new_probes(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(_discovery.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(_discovery, "_TOTAL_TIMEOUT", 0.15)
    waits = []

    def offline(timeout_s):
        waits.append(timeout_s)
        clock[0] += timeout_s
        return False

    with pytest.raises(StateError):
        _discovery.check_motors(
            [SimpleNamespace(_id=i, check_alive=offline) for i in range(7)]
        )
    assert waits == pytest.approx([0.1, 0.05])


def test_transport_failure_is_not_retried():
    calls = []
    original = RuntimeError("bus fault")

    def fault(timeout_s):
        calls.append(timeout_s)
        raise original

    with pytest.raises(RuntimeError) as exc:
        _discovery.check_motors([SimpleNamespace(_id=61, check_alive=fault)])
    assert exc.value is original
    assert calls == [0.1]
