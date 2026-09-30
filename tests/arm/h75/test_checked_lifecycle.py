"""Lifecycle receipts and device readback through both real virtual-CAN workers."""

import threading
import time
import uuid
from types import SimpleNamespace

import can
import pytest

from linkerbot_arm import CANError, StateError, TimeoutError
from linkerbot_arm._transport.can import ManagedCANDispatcher
from linkerbot_arm.arm.h75 import H75Motor
from linkerbot_arm.comm.can import CANMessageDispatcher
from tests.arm.h75.test_h75 import arm as arm
from tests.arm.h75.test_h75 import configure
from tests.test_motion_batches import QueuedDispatcher


@pytest.fixture(params=["dispatcher", "cantransport"])
def connected(request, arm, monkeypatch):
    configure(arm)
    name = "h75-lifecycle-" + uuid.uuid4().hex
    peer = can.Bus(interface="virtual", channel=name)

    def fault(error):
        arm._on_bus_error(error)
        arm._motion_timer.cancel()

    adapter = (
        CANMessageDispatcher(name, "virtual", on_bus_error=fault)
        if request.param == "dispatcher"
        else ManagedCANDispatcher(name, "virtual", "h75", "left", fault)
    )
    dispatcher = (
        adapter if request.param == "dispatcher" else adapter._transport._dispatcher
    )
    state = SimpleNamespace(fail=None, refuse_enable=False, drop_enable_reply=False)
    seen, enabled = [], {}
    stopped = threading.Event()
    send = dispatcher._bus.send

    def fail_selected(message, *a, **k):
        if state.fail == (message.arbitration_id, bytes(message.data)):
            raise can.CanOperationError("injected physical send failure")
        return send(message, *a, **k)

    monkeypatch.setattr(dispatcher._bus, "send", fail_selected)

    def device():
        while not stopped.is_set():
            message = peer.recv(0.01)
            if message is None:
                continue
            data = bytes(message.data)
            seen.append((message.arbitration_id, data))
            if len(data) == 2 and data[0] == 0x2A:
                enabled[message.arbitration_id] = 0 if state.refuse_enable else data[1]
            elif data == b"\x2b":
                value = enabled.get(message.arbitration_id, 0)
                if not (state.drop_enable_reply and value):
                    peer.send(
                        can.Message(
                            arbitration_id=message.arbitration_id,
                            is_extended_id=False,
                            data=bytes([0x2B, value]),
                        )
                    )

    worker = threading.Thread(target=device)
    worker.start()
    arm._can_dispatcher = adapter
    for motor in arm._motors:
        motor._dispatcher = adapter
        adapter.subscribe(motor._on_message)
    original_read = H75Motor._read_enabled
    monkeypatch.setattr(
        H75Motor, "_read_enabled", lambda self, timeout_s=1: original_read(self, 0.05)
    )
    try:
        yield arm, adapter, dispatcher, state, seen
    finally:
        adapter.stop()
        stopped.set()
        worker.join(1)
        peer.shutdown()
        assert not worker.is_alive()
        assert not adapter._tx.get_health().running


def test_enable_readback_precedes_every_brake_release(connected):
    arm, _, _, _, seen = connected
    arm.enable()
    for mid in (61, 62):
        assert (
            seen.index((mid, b"\x2a\x01"))
            < seen.index((mid, b"\x2b"))
            < seen.index((mid, b"\xf4\x01"))
        )
    assert all(m.enabled for m in arm._motors)
    arm.disable()
    assert all(not m.enabled for m in arm._motors)


@pytest.mark.parametrize("failure", ["send", "nack", "read_timeout"])
def test_enable_failure_never_releases_brakes(connected, failure):
    arm, _, _, state, seen = connected
    expected = StateError
    if failure == "send":
        state.fail = (61, b"\x2a\x01")
        expected = CANError
    elif failure == "nack":
        state.refuse_enable = True
    else:
        state.drop_enable_reply = True
        expected = TimeoutError
    with pytest.raises(expected):
        arm.enable()
    assert not any(data == b"\xf4\x01" for _, data in seen)
    assert arm._control_mode is None
    assert all(not m.enabled for m in arm._motors)


def test_fatal_tx_callback_does_not_block_checked_send_on_motion_lock(connected):
    arm, adapter, dispatcher, state, _ = connected
    state.fail = (61, b"\x2a\x01")
    adapter.MAX_CONSECUTIVE_ERRORS = 1
    dispatcher._max_consecutive_errors = 1
    started = time.monotonic()
    with pytest.raises(CANError):
        arm.enable()
    assert time.monotonic() - started < 0.5


def test_timed_out_unstarted_lifecycle_frame_expires_before_dispatch():
    bus = QueuedDispatcher()
    try:
        with pytest.raises(TimeoutError):
            bus._send_checked(
                can.Message(arbitration_id=61, data=b"\x2a\x01"), timeout_s=0.01
            )
        bus._tx.drain()
        assert bus.sent == []
        assert bus._tx.get_health().expired == 1
    finally:
        bus._tx.close()


def test_failed_brake_delivery_preserves_enable_on_that_joint(connected):
    arm, _, _, state, seen = connected
    arm.enable()
    seen.clear()
    state.fail = (61, b"\xf4\x00")
    with pytest.raises(CANError):
        arm.disable()
    assert (61, b"\x2a\x00") not in seen
    assert arm._motors[0].enabled
    assert all(not m.enabled for m in arm._motors[1:])
