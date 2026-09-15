import queue
import threading
import time
from collections.abc import Callable

import pytest

from linkerbot_arm.comm.canfd import CANFDMessage, CANFDMessageDispatcher
from linkerbot_arm.comm.canfd import dispatcher as dispatcher_module
from linkerbot_arm.exceptions import CANError, StateError, ValidationError


class FakeInterface:
    def __init__(self) -> None:
        self.incoming: queue.Queue[CANFDMessage | Exception] = queue.Queue()
        self.sent: list[CANFDMessage] = []
        self.closed = False
        self.close_calls = 0
        self.send_error: Exception | None = None
        self.receive_error: Exception | None = None

    def send(self, message: CANFDMessage, timeout_ms: int = 10) -> None:
        _ = timeout_ms
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(message)

    def receive(self, max_frames: int = 64, timeout_ms: int = 10) -> list[CANFDMessage]:
        if self.receive_error is not None:
            raise self.receive_error
        try:
            item = self.incoming.get(timeout=timeout_ms / 1000)
        except queue.Empty:
            return []
        if isinstance(item, Exception):
            raise item
        return [item]

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


def wait_until(predicate: Callable[[], bool], timeout_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError("condition was not met before timeout")


def test_subscriber_receives_incoming_message() -> None:
    interface = FakeInterface()
    dispatcher = CANFDMessageDispatcher(interface=interface)
    received: list[CANFDMessage] = []
    message = CANFDMessage(arbitration_id=1, data=b"abc")

    try:
        dispatcher.subscribe(received.append)
        interface.incoming.put(message)
        wait_until(lambda: received == [message])
    finally:
        dispatcher.stop()


def test_unsubscribe_prevents_future_callbacks() -> None:
    interface = FakeInterface()
    dispatcher = CANFDMessageDispatcher(interface=interface)
    received: list[CANFDMessage] = []
    message = CANFDMessage(arbitration_id=1, data=b"abc")

    try:
        dispatcher.subscribe(received.append)
        dispatcher.unsubscribe(received.append)
        interface.incoming.put(message)
        time.sleep(0.03)
        assert received == []
    finally:
        dispatcher.stop()


def test_send_queues_message_for_fake_interface() -> None:
    interface = FakeInterface()
    dispatcher = CANFDMessageDispatcher(interface=interface)
    message = CANFDMessage(arbitration_id=1, data=b"abc")

    try:
        receipt = dispatcher.send(message)
        assert receipt.cancel() is False
        assert receipt.result(timeout=1.0) is None
        assert interface.sent == [message]
    finally:
        dispatcher.stop()


def test_send_receipt_preserves_background_can_error() -> None:
    interface = FakeInterface()
    expected = CANError("invalid CANFD frame")
    interface.send_error = expected
    dispatcher = CANFDMessageDispatcher(interface=interface)

    try:
        receipt = dispatcher.send(CANFDMessage(arbitration_id=1, data=b"x"))
        with pytest.raises(CANError) as raised:
            receipt.result(timeout=1.0)
        assert raised.value is expected
    finally:
        dispatcher.stop()


def test_send_receipt_wraps_background_system_error() -> None:
    interface = FakeInterface()
    expected = OSError("write failed")
    interface.send_error = expected
    dispatcher = CANFDMessageDispatcher(interface=interface)

    try:
        receipt = dispatcher.send(CANFDMessage(arbitration_id=1, data=b"x"))
        with pytest.raises(CANError, match="background send failed") as raised:
            receipt.result(timeout=1.0)
        assert raised.value.__cause__ is expected
    finally:
        dispatcher.stop()


def test_fatal_send_failure_fails_current_and_queued_receipts() -> None:
    class GatedFailingInterface(FakeInterface):
        def __init__(self) -> None:
            super().__init__()
            self.send_started = threading.Event()
            self.release_send = threading.Event()

        def send(self, message: CANFDMessage, timeout_ms: int = 10) -> None:
            _ = message, timeout_ms
            self.send_started.set()
            assert self.release_send.wait(timeout=1.0)
            raise CANError("physical send failed")

    interface = GatedFailingInterface()
    dispatcher = CANFDMessageDispatcher(interface=interface, max_consecutive_errors=1)
    first = dispatcher.send(CANFDMessage(arbitration_id=1, data=b"a"))
    assert interface.send_started.wait(timeout=1.0)
    second = dispatcher.send(CANFDMessage(arbitration_id=2, data=b"b"))
    third = dispatcher.send(CANFDMessage(arbitration_id=3, data=b"c"))
    interface.release_send.set()

    try:
        for receipt in (first, second, third):
            with pytest.raises(CANError):
                receipt.result(timeout=1.0)
        wait_until(lambda: not dispatcher._running)
    finally:
        dispatcher.stop()


def test_stop_fails_in_flight_and_queued_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingSendInterface(FakeInterface):
        def __init__(self) -> None:
            super().__init__()
            self.send_started = threading.Event()
            self.release_send = threading.Event()

        def send(self, message: CANFDMessage, timeout_ms: int = 10) -> None:
            assert self.release_send.wait(timeout=1.0)
            super().send(message, timeout_ms)

    monkeypatch.setattr(dispatcher_module, "THREAD_JOIN_TIMEOUT_S", 0.01)
    interface = BlockingSendInterface()
    dispatcher = CANFDMessageDispatcher(interface=interface)
    first = dispatcher.send(CANFDMessage(arbitration_id=1, data=b"a"))
    second = dispatcher.send(CANFDMessage(arbitration_id=2, data=b"b"))

    try:
        dispatcher.stop()
        for receipt in (first, second):
            with pytest.raises(StateError, match="stopped before queued send"):
                receipt.result(timeout=0)
    finally:
        interface.release_send.set()
        dispatcher._send_thread.join(timeout=1.0)
        dispatcher.stop()


def test_callback_exception_does_not_stop_other_callbacks() -> None:
    interface = FakeInterface()
    dispatcher = CANFDMessageDispatcher(interface=interface)
    received: list[CANFDMessage] = []
    message = CANFDMessage(arbitration_id=1, data=b"abc")

    def broken_callback(message: CANFDMessage) -> None:
        raise RuntimeError("boom")

    try:
        dispatcher.subscribe(broken_callback)
        dispatcher.subscribe(received.append)
        interface.incoming.put(message)
        wait_until(lambda: received == [message])
    finally:
        dispatcher.stop()


def test_receive_errors_trigger_bus_error_once() -> None:
    interface = FakeInterface()
    errors: list[Exception] = []
    dispatcher = CANFDMessageDispatcher(
        interface=interface,
        on_bus_error=errors.append,
        max_consecutive_errors=2,
    )

    try:
        interface.incoming.put(CANError("rx1"))
        interface.incoming.put(CANError("rx2"))
        wait_until(lambda: len(errors) == 1)
        time.sleep(0.03)
        assert len(errors) == 1
    finally:
        dispatcher.stop()


def test_send_errors_trigger_bus_error_once() -> None:
    interface = FakeInterface()
    interface.send_error = CANError("tx")
    errors: list[Exception] = []
    dispatcher = CANFDMessageDispatcher(
        interface=interface,
        on_bus_error=errors.append,
        max_consecutive_errors=1,
    )

    try:
        dispatcher.send(CANFDMessage(arbitration_id=1, data=b""))
        wait_until(lambda: len(errors) == 1)
    finally:
        dispatcher.stop()


def test_send_after_fatal_bus_error_raises_can_error() -> None:
    interface = FakeInterface()
    interface.send_error = CANError("tx")
    dispatcher = CANFDMessageDispatcher(interface=interface, max_consecutive_errors=1)

    try:
        dispatcher.send(CANFDMessage(arbitration_id=1, data=b""))
        wait_until(lambda: not dispatcher._running)
        with pytest.raises(CANError, match="CANFD bus unavailable"):
            dispatcher.send(CANFDMessage(arbitration_id=1, data=b""))
    finally:
        dispatcher.stop()


def test_stop_closes_interface_and_is_idempotent() -> None:
    interface = FakeInterface()
    dispatcher = CANFDMessageDispatcher(interface=interface)

    dispatcher.stop()
    dispatcher.stop()

    assert interface.closed is True
    assert interface.close_calls == 1


def test_concurrent_fatal_errors_report_only_once() -> None:
    class SlowFalse:
        def __bool__(self) -> bool:
            # Release the GIL between the old check and assignment so both
            # callers would observe false without the fatal-transition lock.
            time.sleep(0.03)
            return False

    interface = FakeInterface()
    errors: list[Exception] = []
    dispatcher = CANFDMessageDispatcher(interface=interface, on_bus_error=errors.append)
    dispatcher._error_reported = SlowFalse()  # ty: ignore[invalid-assignment]
    start = threading.Barrier(3)

    def report_error(message: str) -> None:
        start.wait()
        dispatcher._handle_bus_error(CANError(message))

    threads = [
        threading.Thread(target=report_error, args=(f"error-{index}",))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=1.0)

    try:
        assert all(not thread.is_alive() for thread in threads)
        assert len(errors) == 1
    finally:
        dispatcher.stop()


def test_concurrent_stop_closes_interface_only_once() -> None:
    class SlowCloseInterface(FakeInterface):
        def close(self) -> None:
            time.sleep(0.03)
            super().close()

    interface = SlowCloseInterface()
    dispatcher = CANFDMessageDispatcher(interface=interface)
    start = threading.Barrier(3)

    def stop() -> None:
        start.wait()
        dispatcher.stop()

    threads = [threading.Thread(target=stop) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=2.0)

    assert all(not thread.is_alive() for thread in threads)
    assert interface.close_calls == 1


def test_context_manager_stops_dispatcher() -> None:
    interface = FakeInterface()

    with CANFDMessageDispatcher(interface=interface):
        pass

    assert interface.closed is True


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_error_threshold_is_rejected(value: object) -> None:
    with pytest.raises(ValidationError, match="positive int"):
        CANFDMessageDispatcher(
            interface=FakeInterface(),
            max_consecutive_errors=value,  # ty: ignore[invalid-argument-type]
        )


def test_falsy_backend_is_not_replaced_by_vendor_interface() -> None:
    class FalsyInterface(FakeInterface):
        def __bool__(self) -> bool:
            return False

    interface = FalsyInterface()

    with CANFDMessageDispatcher(interface=interface) as dispatcher:
        assert dispatcher.interface is interface


def test_unsubscribe_removes_fresh_bound_method_from_filtered_subscribers() -> None:
    class Receiver:
        def __init__(self) -> None:
            self.messages: list[CANFDMessage] = []

        def receive(self, message: CANFDMessage) -> None:
            self.messages.append(message)

    interface = FakeInterface()
    receiver = Receiver()
    dispatcher = CANFDMessageDispatcher(interface=interface)
    try:
        dispatcher.subscribe_filter(lambda _: True, receiver.receive)
        # Each attribute access creates a new bound-method object. Unsubscribe
        # must compare callbacks by equality, as plain subscriptions do.
        dispatcher.unsubscribe(receiver.receive)
        dispatcher._dispatch(CANFDMessage(arbitration_id=1, data=b"x"))
        assert receiver.messages == []
    finally:
        dispatcher.stop()


def test_send_after_stop_raises_runtime_error() -> None:
    interface = FakeInterface()
    dispatcher = CANFDMessageDispatcher(interface=interface)
    dispatcher.stop()

    with pytest.raises(RuntimeError, match="stopped"):
        dispatcher.send(CANFDMessage(arbitration_id=1, data=b""))


class _BatchInterface:
    """Dispatcher-level fake interface that records both ``send`` and
    ``send_batch`` calls so we can assert which path was taken."""

    def __init__(self) -> None:
        self.send_calls: list[CANFDMessage] = []
        self.batch_calls: list[list[CANFDMessage]] = []
        self._gate: threading.Event | None = None
        self._gate_count = 0
        self.closed = False
        self.incoming: queue.Queue = queue.Queue()

    def install_first_send_gate(self) -> threading.Event:
        """Block the first send/send_batch call until the test releases it.

        Used to keep the dispatcher's send thread busy while we queue more
        frames behind it, so the test can deterministically observe the
        batch on the next loop iteration.
        """
        self._gate = threading.Event()
        return self._gate

    def send(self, message: CANFDMessage, timeout_ms: int = 10) -> None:
        if self._gate is not None and self._gate_count == 0:
            self._gate_count += 1
            self._gate.wait(timeout=2.0)
        self.send_calls.append(message)

    def send_batch(self, messages: list[CANFDMessage], timeout_ms: int = 10) -> None:
        if self._gate is not None and self._gate_count == 0:
            self._gate_count += 1
            self._gate.wait(timeout=2.0)
        self.batch_calls.append(list(messages))

    def receive(self, max_frames: int = 64, timeout_ms: int = 10) -> list[CANFDMessage]:
        try:
            msg = self.incoming.get(timeout=timeout_ms / 1000.0)
        except queue.Empty:
            return []
        return [msg]

    def close(self) -> None:
        self.closed = True


def test_failed_batch_fails_every_frame_receipt() -> None:
    expected = CANError("batch outcome is unknown")

    class _FailingBatchInterface(_BatchInterface):
        def send_batch(
            self, messages: list[CANFDMessage], timeout_ms: int = 10
        ) -> None:
            _ = timeout_ms
            self.batch_calls.append(list(messages))
            raise expected

    interface = _FailingBatchInterface()
    gate = interface.install_first_send_gate()
    dispatcher = CANFDMessageDispatcher(interface=interface)

    try:
        primer = dispatcher.send(CANFDMessage(arbitration_id=0, data=b"primer"))
        deadline = time.monotonic() + 1.0
        while interface._gate_count == 0 and time.monotonic() < deadline:
            time.sleep(0.001)
        receipts = [
            dispatcher.send(CANFDMessage(arbitration_id=i, data=bytes([i])))
            for i in range(1, 4)
        ]
        gate.set()

        assert primer.result(timeout=1.0) is None
        for receipt in receipts:
            with pytest.raises(CANError) as raised:
                receipt.result(timeout=1.0)
            assert raised.value is expected
        assert [
            [message.arbitration_id for message in batch]
            for batch in interface.batch_calls
        ] == [[1, 2, 3]]
    finally:
        dispatcher.stop()


def test_receipt_identity_callbacks_and_queue_overflow():
    from linkerbot_arm.comm.canfd import CANFDSendReceipt

    class GatedInterface(FakeInterface):
        def send(self, message, timeout_ms=10):
            entered.set()
            assert release.wait(2)
            super().send(message, timeout_ms)

    class SmallDispatcher(CANFDMessageDispatcher):
        SEND_QUEUE_SIZE = 1

    entered = threading.Event()
    release = threading.Event()
    dispatcher = SmallDispatcher(interface=GatedInterface())
    message = CANFDMessage(1, b"x")
    try:
        first = dispatcher.send(message)
        assert entered.wait(1)
        second = dispatcher.send(message)
        completed = []
        first.add_done_callback(completed.append)
        assert type(first) is CANFDSendReceipt
        assert first.running()
        assert first.cancel() is False
        with pytest.raises(queue.Full) as caught:
            dispatcher.send(message)
        assert type(caught.value) is queue.Full
        assert caught.value.args == ()
        release.set()
        assert first.result(1) is None
        assert second.result(1) is None
        wait_until(lambda: completed == [first])
    finally:
        release.set()
        dispatcher.stop()


@pytest.mark.parametrize(
    "error", [ValidationError("bad frame"), StateError("device unavailable")]
)
def test_receipt_wraps_non_can_backend_errors(error):
    interface = FakeInterface()
    interface.send_error = error
    with CANFDMessageDispatcher(interface=interface) as dispatcher:
        receipt = dispatcher.send(CANFDMessage(1, b"x"))
        with pytest.raises(CANError, match="background send failed") as caught:
            receipt.result(1)
        assert caught.value.__cause__ is error


def test_stop_preserves_best_effort_close_error(caplog):
    class FailingClose(FakeInterface):
        def close(self):
            super().close()
            raise OSError("close failed")

    interface = FailingClose()
    dispatcher = CANFDMessageDispatcher(interface=interface)
    dispatcher.stop()
    dispatcher.stop()
    assert interface.close_calls == 1
    assert "CANFD interface close failed" in caplog.text
