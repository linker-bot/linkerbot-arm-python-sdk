"""All three real arm constructors on the high-level connection backend."""

import importlib
import threading

import pytest
from linkerbot_transport import TransportState

from linkerbot_arm._transport import can as managed
from linkerbot_arm.exceptions import CANError, ValidationError

from . import test_arm_transport_lifecycle as lifecycle

constructed_arm = lifecycle.constructed_arm


@pytest.fixture
def connections(monkeypatch):
    monkeypatch.setenv("LINKERBOT_ARM_TRANSPORT", "cantransport")
    opened = []
    factory = managed.CANTransport

    def create(*args, **kwargs):
        connection = factory(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(managed, "CANTransport", create)
    yield opened
    for connection in opened:
        connection.close()


@pytest.mark.parametrize("side", ["left", "right"])
def test_high_backend_constructor_and_context_manager(
    constructed_arm, connections, side
):
    _, construct, _ = constructed_arm
    arm = construct(side)
    dispatcher = arm._can_dispatcher
    try:
        assert isinstance(dispatcher, managed.ManagedCANDispatcher)
        assert connections[0].get_health().state is TransportState.OPEN
        assert arm.can_interface is connections[0].can_interface
        assert len(arm._motors) == 7
        with pytest.raises(ValueError, match="application error"):
            with arm:
                raise ValueError("application error")
        assert connections[0].get_health().state is TransportState.CLOSED
        assert not dispatcher._recv_thread.is_alive()
        arm.close()
    finally:
        dispatcher.stop()


@pytest.mark.parametrize("failure", ["kinematics", "initial_state", "polling"])
def test_constructor_failure_releases_created_connection(
    constructed_arm, connections, monkeypatch, failure
):
    cls, construct, _ = constructed_arm
    module = importlib.import_module(cls.__module__)

    def fail(*args, **kwargs):
        raise ValueError("initialization failed")

    if failure == "kinematics":
        from linkerbot_arm.arm.kinetix import ArmKinetix

        monkeypatch.setattr(ArmKinetix, "from_builtin", fail)
    else:
        motor = getattr(module, "A7Motor", getattr(module, "A7liteMotor", None))
        method = "read_initial_state" if failure == "initial_state" else "start_polling"
        if cls.__name__ == "A7lite" and failure == "polling":
            method = "start_reporting"
        monkeypatch.setattr(motor, method, fail)
    before = set(threading.enumerate())
    with pytest.raises(ValueError, match="initialization failed"):
        construct("left")
    assert connections[0].get_health().state is TransportState.CLOSED
    assert not set(threading.enumerate()) - before


def test_fault_cancels_motion_stops_polling_and_close_remains_available(
    constructed_arm, connections
):
    _, construct, _ = constructed_arm
    arm = construct("left")
    adapter = arm._can_dispatcher
    arm._motion_timer.start(60)
    connections[0]._dispatcher._handle_bus_error(OSError("bus disconnected"))
    adapter._recv_thread.join(2)
    try:
        assert not adapter._recv_thread.is_alive()
        assert arm._closed
        assert not arm.is_moving()
        assert not getattr(arm, "_polling", False)
        assert isinstance(arm._bus_error, CANError)
        assert connections[0].get_health().state is TransportState.CLOSED
        arm.close()
        with pytest.raises(CANError, match="bus disconnected"):
            adapter.send(None)
    finally:
        adapter.stop()
        arm._motion_timer.cancel()


def test_fault_during_initial_state_cannot_return_a_healthy_arm(
    constructed_arm, connections, monkeypatch
):
    cls, construct, _ = constructed_arm
    module = importlib.import_module(cls.__module__)
    motor = getattr(module, "A7Motor", getattr(module, "A7liteMotor", None))

    def fail_during_read(self):
        connection = connections[0]
        if connection.get_health().state is TransportState.OPEN:
            connection._dispatcher._handle_bus_error(OSError("startup disconnected"))
            self._dispatcher._recv_thread.join(2)
            assert not self._dispatcher._recv_thread.is_alive()

    monkeypatch.setattr(motor, "read_initial_state", fail_during_read)
    with pytest.raises(CANError, match="startup disconnected"):
        construct("left")
    assert connections[0].get_health().state is TransportState.CLOSED


def test_invalid_backend_selection_does_not_open_a_bus(constructed_arm, monkeypatch):
    _, construct, events = constructed_arm
    monkeypatch.setenv("LINKERBOT_ARM_TRANSPORT", "unknown")
    with pytest.raises(ValidationError, match="LINKERBOT_ARM_TRANSPORT"):
        construct("left")
    assert events == []
