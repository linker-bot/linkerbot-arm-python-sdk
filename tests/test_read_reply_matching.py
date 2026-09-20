"""Address correlation through both real virtual-CAN backends and direct callbacks."""

import struct
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import can
import pytest

from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from linkerbot_arm.exceptions import TimeoutError
from tests.test_transport_frames import FakeDispatcher
from tests.test_transport_frames import link as link


def read(motor, address, timeout=1):
    operation = (
        motor._read_register
        if isinstance(motor, A7liteMotor)
        else motor._read_flash_param
    )
    return operation(address, timeout_s=timeout)


def reply(cls, address, value=1.25):
    if cls is A7liteMotor:
        return can.Message(
            arbitration_id=0x11003DFD,
            is_extended_id=True,
            data=struct.pack("<HHf", address, 0, value),
        )
    return can.Message(
        arbitration_id=0x642,
        is_extended_id=False,
        data=bytes([66, address]) + struct.pack("<f", value) + b"\x00\xff",
    )


def watch_sends(dispatcher, monkeypatch):
    sent = Queue()
    original = dispatcher.send

    def send(message):
        original(message)
        sent.put(message)

    monkeypatch.setattr(dispatcher, "send", send)
    return sent


@pytest.mark.parametrize("cls", [A7liteMotor, MotorV2])
def test_late_other_address_cannot_complete_new_read(link, cls, monkeypatch):
    dispatcher, receive, feedback = link
    motor = cls(61 if cls is A7liteMotor else 66, dispatcher)
    addresses = (0x7016, 0x7024) if cls is A7liteMotor else (0x01, 0x0B)
    sent = watch_sends(dispatcher, monkeypatch)
    with pytest.raises(TimeoutError):
        read(motor, addresses[0], 0)
    sent.get(timeout=1)
    assert receive() is not None
    with ThreadPoolExecutor() as pool:
        future = pool.submit(read, motor, addresses[1])
        sent.get(timeout=1)
        assert receive() is not None
        feedback(reply(cls, addresses[0]))
        assert not future.done()
        feedback(reply(cls, addresses[1], 2.5))
        assert future.result(1) == struct.pack("<f", 2.5)


@pytest.mark.parametrize("cls", [A7liteMotor, MotorV2])
def test_concurrent_different_addresses_accept_reordered_replies(
    link, cls, monkeypatch
):
    dispatcher, receive, feedback = link
    motor = cls(61 if cls is A7liteMotor else 66, dispatcher)
    sent = watch_sends(dispatcher, monkeypatch)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(read, motor, 1)
        sent.get(timeout=1)
        receive()
        second = pool.submit(read, motor, 2)
        sent.get(timeout=1)
        receive()
        feedback(reply(cls, 2, 2.5))
        assert second.result(1) == struct.pack("<f", 2.5)
        assert not first.done()
        feedback(reply(cls, 1))
        assert first.result(1) == struct.pack("<f", 1.25)


@pytest.mark.parametrize("cls", [A7liteMotor, MotorV2])
def test_same_address_serialization_timeout_cleanup_and_fast_reply(
    link, cls, monkeypatch
):
    dispatcher, receive, feedback = link
    motor = cls(61 if cls is A7liteMotor else 66, dispatcher)
    sent = watch_sends(dispatcher, monkeypatch)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(read, motor, 1)
        sent.get(timeout=1)
        receive()
        second = pool.submit(read, motor, 1)
        feedback(reply(cls, 1))
        assert first.result(1) == struct.pack("<f", 1.25)
        sent.get(timeout=1)
        receive()
        assert not second.done()
        feedback(reply(cls, 1, 2.5))
        assert second.result(1) == struct.pack("<f", 2.5)
    with pytest.raises(TimeoutError):
        read(motor, 1, 0)
    relays = motor._read_relays if cls is A7liteMotor else motor._flash_relays
    assert not relays[1]._waiters
    # Immediate response during send, including a retry after a timeout.
    monkeypatch.setattr(
        dispatcher, "send", lambda message: motor._on_message(reply(cls, 1))
    )
    assert read(motor, 1, 0) == struct.pack("<f", 1.25)


@pytest.mark.parametrize("cls", [A7liteMotor, MotorV2])
@pytest.mark.parametrize(
    "invalid",
    [
        "motor",
        "address",
        "type",
        "remote",
        "error",
        "fd",
        "short",
        "long",
        "dlc",
        "status",
    ],
)
def test_malformed_or_unrelated_reply_is_ignored(cls, invalid):
    dispatcher = FakeDispatcher()
    motor = cls(61 if cls is A7liteMotor else 66, dispatcher)
    message = reply(cls, 1)
    if invalid == "motor":
        message.arbitration_id += 0x100 if cls is A7liteMotor else 1
    elif invalid == "address":
        message = reply(cls, 2)
    elif invalid == "type":
        message.is_extended_id = not message.is_extended_id
    elif invalid in ("remote", "error"):
        setattr(message, f"is_{invalid}_frame", True)
    elif invalid == "fd":
        message.is_fd = True
    elif invalid == "short":
        message.data = message.data[:7]
    elif invalid == "long":
        message.data += b"\x00"
    elif invalid == "dlc":
        message.dlc = 7
    elif cls is A7liteMotor:
        message.arbitration_id |= 1 << 16
    else:
        message.data[6] = 1
    dispatcher.send = lambda request: dispatcher.feedback(message)
    with pytest.raises(TimeoutError):
        read(motor, 1, 0)
    # The rejected frame must not prevent the next valid read.
    dispatcher.send = lambda request: dispatcher.feedback(reply(cls, 1))
    assert read(motor, 1, 0) == struct.pack("<f", 1.25)


@pytest.mark.parametrize("cls", [A7liteMotor, MotorV2])
def test_send_failure_does_not_leave_a_waiter(cls):
    motor = cls(61 if cls is A7liteMotor else 66, FakeDispatcher())

    def fail(message):
        raise RuntimeError("send failed")

    motor._dispatcher.send = fail
    with pytest.raises(RuntimeError, match="send failed"):
        read(motor, 1)
    motor._dispatcher.send = lambda request: motor._on_message(reply(cls, 1))
    assert read(motor, 1, 0) == struct.pack("<f", 1.25)


@pytest.mark.parametrize("invalid", ["master", "command", "payload_motor", "footer"])
def test_protocol_specific_fields_cannot_complete_a_read(invalid):
    cls = A7liteMotor if invalid in ("master", "command") else MotorV2
    dispatcher = FakeDispatcher()
    motor = cls(61 if cls is A7liteMotor else 66, dispatcher)
    message = reply(cls, 1)
    if invalid == "master":
        message.arbitration_id ^= 1
    elif invalid == "command":
        message.arbitration_id = (message.arbitration_id & 0xFFFFFF) | (18 << 24)
    elif invalid == "payload_motor":
        message.data[0] += 1
    else:
        message.data[7] = 0
    dispatcher.send = lambda request: dispatcher.feedback(message)
    with pytest.raises(TimeoutError):
        read(motor, 1, 0)
