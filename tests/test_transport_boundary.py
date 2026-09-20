"""Arm's observable contract over Transport 1.x, without physical hardware."""

import builtins
import pickle
import queue
import threading
import uuid
from dataclasses import FrozenInstanceError

import can
import pytest
from linkerbot_transport import TransmitArbiter, errors
from linkerbot_transport.can.types import CanInterface as TransportInterface

from linkerbot_arm import exceptions
from linkerbot_arm.comm.can import CanInterface, CANMessageDispatcher


@pytest.mark.parametrize(
    "name,category",
    [
        ("LinkerbotError", errors.LinkerbotError),
        ("TimeoutError", errors.TimeoutError),
        ("CANError", errors.TransportError),
        ("ValidationError", errors.ValidationError),
        ("StateError", errors.DeviceStateError),
    ],
)
@pytest.mark.parametrize("args", [(), ("failure",), ("failure", 42, "detail")])
def test_legacy_exceptions_keep_arguments_identity_and_transport_category(
    name, category, args
):
    cls = getattr(exceptions, name)
    error = cls(*args)
    assert isinstance(error, exceptions.LinkerbotError)
    assert isinstance(error, category)
    assert error.code == category.code
    baseline = (
        builtins.TimeoutError(*args) if name == "TimeoutError" else Exception(*args)
    )
    assert error.args == baseline.args
    assert str(error) == str(baseline)
    restored = pickle.loads(pickle.dumps(error))
    assert type(restored) is cls
    assert restored.args == baseline.args
    assert str(restored) == str(baseline)


def test_can_interface_alias_keeps_constructor_and_frozen_value_semantics():
    assert CanInterface is TransportInterface
    interface = CanInterface("vcan0", "socketcan")
    assert interface == CanInterface(interface_name="vcan0", interface_type="socketcan")
    assert pickle.loads(pickle.dumps(interface)) == interface
    with pytest.raises(FrozenInstanceError):
        interface.interface_name = "changed"


def test_send_discards_receipt_without_waiting(monkeypatch):
    class UnusableReceipt:
        def result(self, *args, **kwargs):
            pytest.fail("arm must not wait for physical-send receipts")

    sent = []

    def send(self, message, *, endpoint_id):
        sent.append(message)
        return UnusableReceipt()

    monkeypatch.setattr(TransmitArbiter, "submit_fifo", send)
    dispatcher = CANMessageDispatcher.__new__(CANMessageDispatcher)
    dispatcher._error_lock = threading.Lock()
    dispatcher._running = True
    dispatcher._bus_error = None
    dispatcher._tx = TransmitArbiter(lambda message: None)
    message = can.Message(arbitration_id=61, data=b"\x06", is_extended_id=False)
    assert dispatcher.send(message) is None
    assert sent == [message]


@pytest.mark.parametrize(
    "error,expected",
    [
        (errors.QueueFullError("full"), queue.Full),
        (errors.TransportError("bus unavailable"), exceptions.CANError),
        (RuntimeError("stopped"), RuntimeError),
    ],
)
def test_send_preserves_legacy_error_types(monkeypatch, error, expected):
    def send(self, message, *, endpoint_id):
        raise error

    monkeypatch.setattr(TransmitArbiter, "submit_fifo", send)
    dispatcher = CANMessageDispatcher.__new__(CANMessageDispatcher)
    dispatcher._error_lock = threading.Lock()
    dispatcher._running = True
    dispatcher._bus_error = None
    dispatcher._tx = TransmitArbiter(lambda message: None)
    with pytest.raises(expected) as caught:
        dispatcher.send(can.Message(arbitration_id=61))
    assert type(caught.value) is expected
    if expected is queue.Full:
        assert caught.value.args == ()
    else:
        assert caught.value.args == error.args


def test_concurrent_failed_shutdown_is_visible_and_can_retry(monkeypatch):
    dispatcher = CANMessageDispatcher("arm-shutdown-" + uuid.uuid4().hex, "virtual")
    shutdown = dispatcher._bus.shutdown
    calls = []

    def fail_shutdown():
        calls.append(1)
        raise OSError("shutdown failure")

    monkeypatch.setattr(dispatcher._bus, "shutdown", fail_shutdown)
    barrier = threading.Barrier(3)
    failures = []

    def stop():
        barrier.wait()
        try:
            dispatcher.stop()
        except Exception as error:
            failures.append(error)

    callers = [threading.Thread(target=stop) for _ in range(2)]
    for thread in callers:
        thread.start()
    barrier.wait()
    for thread in callers:
        thread.join(2)
        assert not thread.is_alive()
    assert len(failures) == 2
    assert all("shutdown failure" in str(error) for error in failures)
    assert calls == [1, 1]
    assert not dispatcher._shutdown_complete
    assert not dispatcher._bus._is_shutdown
    monkeypatch.setattr(dispatcher._bus, "shutdown", shutdown)
    dispatcher.stop()
    dispatcher.stop()
    assert dispatcher._shutdown_complete
    assert dispatcher._bus._is_shutdown
    assert not dispatcher._recv_thread.is_alive()
    assert not dispatcher._send_thread.is_alive()
