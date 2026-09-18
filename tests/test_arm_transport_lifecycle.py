"""Explicit dispatcher compatibility with real virtual CAN and fake motors."""

import importlib
import sys
import threading
import types
import uuid

import pytest
from linkerbot_transport.can.can import CANMessageDispatcher as TransportDispatcher

from linkerbot_arm import A7, P7, A7lite
from linkerbot_arm.comm.can import CANMessageDispatcher
from linkerbot_arm.exceptions import CANError


@pytest.fixture(params=[A7, A7lite, P7])
def constructed_arm(request, monkeypatch):
    monkeypatch.setenv("LINKERBOT_ARM_TRANSPORT", "dispatcher")
    cls = request.param
    module = importlib.import_module(cls.__module__)
    events = []
    dispatchers = []

    def open_dispatcher(name, backend, **kwargs):
        events.append(("open", name, backend))
        dispatcher = CANMessageDispatcher(name, backend, **kwargs)
        dispatchers.append(dispatcher)
        stop = dispatcher.stop

        def tracked_stop():
            events.append(("close_bus",))
            stop()

        monkeypatch.setattr(dispatcher, "stop", tracked_stop)
        return dispatcher

    def motor_type(kind):
        class FakeMotor:
            def __init__(self, id, dispatcher):
                self._id = id
                self._dispatcher = dispatcher
                self.kind = kind
                events.append(("motor", id, kind))

            def check_alive(self):
                events.append(("check", self._id))
                return True

            def read_initial_state(self):
                events.append(("initial", self._id))

            def has_initial_data(self):
                events.append(("has_initial", self._id))
                return True

            def has_reporting_data(self):
                events.append(("has_reporting", self._id))
                return True

            def start_polling(self, intervals):
                events.append(("poll", self._id, intervals))

            def stop_polling(self):
                events.append(("stop_poll", self._id))

            def start_reporting(self):
                events.append(("report", self._id))

        return FakeMotor

    def from_builtin(model, side, **kwargs):
        events.append(("kinematics", model, side, kwargs))
        return object()

    # Avoid importing Pinocchio in the minimum-dependency environment.
    kinetix = types.ModuleType("linkerbot_arm.arm.kinetix")
    kinetix.ArmKinetix = types.SimpleNamespace(from_builtin=from_builtin)
    monkeypatch.setitem(sys.modules, kinetix.__name__, kinetix)
    monkeypatch.setattr(module, "CANMessageDispatcher", open_dispatcher)
    for name in ("A7Motor", "A7liteMotor", "MotorV2"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, motor_type(name))

    def construct(side):
        arm = cls(side, "arm-lifecycle-" + uuid.uuid4().hex, "virtual")
        monkeypatch.setattr(
            arm._motion_timer, "wait_done", lambda: events.append(("wait_motion",))
        )
        return arm

    yield cls, construct, events
    for dispatcher in dispatchers:
        dispatcher.stop()


@pytest.mark.parametrize("side,first_id", [("left", 61), ("right", 51)])
def test_constructor_and_normal_close_order(constructed_arm, side, first_id):
    cls, construct, events = constructed_arm
    arm = construct(side)
    ids = list(range(first_id, first_id + 7))
    assert [m._id for m in arm._motors] == ids
    assert all(m._dispatcher is arm._can_dispatcher for m in arm._motors)
    assert isinstance(arm._can_dispatcher, TransportDispatcher)
    assert arm.can_interface is arm._can_dispatcher.can_interface
    assert arm._closed is False
    if cls is A7lite:
        assert arm.control_modes is None
    else:
        assert arm._control_mode is None
    kinds = ["A7liteMotor"] * 7 if cls is A7lite else ["A7Motor"] * 7
    if cls is P7:
        kinds[5:] = ["MotorV2"] * 2
    assert events[0] == ("open", arm.can_interface.interface_name, "virtual")
    assert events[1:8] == [("motor", id, kind) for id, kind in zip(ids, kinds)]
    model = {A7: "a7", A7lite: "a7_lite", P7: "p7"}[cls]
    assert events[8] == (
        "kinematics",
        model,
        side,
        {"tcp_offset": [0.0] * 3, "world_frame": "urdf"},
    )
    expected = [("check", id) for id in ids]
    if cls is A7lite:
        expected += [event for id in ids for event in [("report", id), ("initial", id)]]
        expected += [("has_reporting", id) for id in ids]
    else:
        expected += [("initial", id) for id in ids]
        expected += [("has_initial", id) for id in ids]
        intervals = importlib.import_module(cls.__module__).DEFAULT_POLL_INTERVALS
        assert intervals == {0x06: 0.01, 0x05: 0.01, 0x03: 0.05, 0x5F: 1.0}
        expected += [("poll", id, intervals) for id in ids]
        assert arm._polling is True
    assert events[9:] == expected

    events.clear()
    assert arm.close() is None
    expected_close = [] if cls is A7lite else [("stop_poll", id) for id in ids]
    assert events == expected_close + [("wait_motion",), ("close_bus",)]
    assert arm._closed is True
    assert not arm._can_dispatcher._recv_thread.is_alive()
    assert not arm._can_dispatcher._send_thread.is_alive()
    events.clear()
    arm.close()
    assert events == []


def test_context_manager_closes_and_propagates_body_exception(constructed_arm):
    _, construct, events = constructed_arm
    arm = construct("left")
    with pytest.raises(ValueError, match="body failure"):
        with arm as entered:
            assert entered is arm
            raise ValueError("body failure")
    assert arm._closed
    assert events[-1] == ("close_bus",)


def test_backend_fault_still_marks_arm_closed(constructed_arm, monkeypatch):
    _, construct, _ = constructed_arm
    arm = construct("left")
    error = OSError("simulated bus disconnect")
    dispatcher = arm._can_dispatcher
    dispatcher._max_consecutive_errors = 1
    fault_reported = threading.Event()
    callback = dispatcher._on_bus_error
    errors = []

    def on_error(value):
        errors.append(value)
        callback(value)
        fault_reported.set()

    def fail_recv(timeout):
        raise error

    monkeypatch.setattr(dispatcher, "_on_bus_error", on_error)
    monkeypatch.setattr(dispatcher._bus, "recv", fail_recv)
    assert fault_reported.wait(1)
    assert arm._closed is True
    assert arm._bus_error is error
    dispatcher._handle_bus_error(OSError("another error"))
    assert errors == [error]
    with pytest.raises(CANError, match="simulated bus disconnect"):
        dispatcher.send(None)
    # Legacy arm.close() returns early when faulted. The fixture explicitly
    # stops the dispatcher; automatic fault cleanup is a later lifecycle task.
