"""Three-model cleanup regression on real virtual CAN, without motor I/O."""

import importlib
import threading

import pytest

from linkerbot_arm.exceptions import CANError

from . import test_arm_transport_lifecycle as lifecycle

constructed_arm = lifecycle.constructed_arm


@pytest.mark.parametrize("stage", ["kinematics", "discovery", "initial", "polling"])
@pytest.mark.parametrize("error_type", [ValueError, KeyboardInterrupt])
def test_legacy_failed_constructor_releases_workers(
    constructed_arm, monkeypatch, stage, error_type
):
    cls, construct, events = constructed_arm
    module = importlib.import_module(cls.__module__)
    original = error_type("initialization interrupted")

    def fail(*args, **kwargs):
        raise original

    if stage == "kinematics":
        from linkerbot_arm.arm.kinetix import ArmKinetix

        monkeypatch.setattr(ArmKinetix, "from_builtin", fail)
    elif stage == "discovery":
        monkeypatch.setattr(cls, "_check_motors", fail)
    else:
        motor = getattr(
            module,
            "A7Motor",
            getattr(module, "A7liteMotor", getattr(module, "H75Motor", None)),
        )
        method = "read_initial_state" if stage == "initial" else "start_polling"
        if cls.__name__ == "A7lite" and stage == "polling":
            method = "start_reporting"
        monkeypatch.setattr(motor, method, fail)
    before = set(threading.enumerate())
    with pytest.raises(error_type) as exc:
        construct("left")
    assert exc.value is original
    assert not set(threading.enumerate()) - before
    assert events[-1] == ("close_bus",)


@pytest.mark.parametrize("backend", ["dispatcher", "cantransport"])
def test_close_failure_is_visible_and_physical_shutdown_retries(
    constructed_arm, monkeypatch, backend
):
    _, construct, _ = constructed_arm
    monkeypatch.setenv("LINKERBOT_ARM_TRANSPORT", backend)
    arm = construct("left")
    adapter = arm._can_dispatcher
    dispatcher = adapter if backend == "dispatcher" else adapter._transport._dispatcher
    shutdown = dispatcher._bus.shutdown
    attempts = []

    def shutdown_once_fails():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("physical shutdown failed")
        shutdown()

    monkeypatch.setattr(dispatcher._bus, "shutdown", shutdown_once_fails)
    try:
        with pytest.raises(CANError, match="physical shutdown failed"):
            arm.close()
        assert arm._closed
        assert not arm._resources_closed
        assert not dispatcher._shutdown_complete
        arm.close()
        arm.close()
        assert len(attempts) == 2
        assert arm._resources_closed
        assert dispatcher._shutdown_complete
        assert dispatcher._bus._is_shutdown
        assert not dispatcher._recv_thread.is_alive()
    finally:
        monkeypatch.setattr(dispatcher._bus, "shutdown", shutdown)
        arm.close()


@pytest.mark.parametrize("backend", ["dispatcher", "cantransport"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_interrupted_motion_wait_still_closes_and_preserves_interrupt(
    constructed_arm, monkeypatch, backend, cleanup_fails, caplog
):
    _, construct, _ = constructed_arm
    monkeypatch.setenv("LINKERBOT_ARM_TRANSPORT", backend)
    arm = construct("left")
    adapter = arm._can_dispatcher
    stop = adapter.stop
    original = KeyboardInterrupt("motion wait interrupted")

    def interrupt():
        raise original

    def fail_stop():
        raise CANError("close also failed")

    monkeypatch.setattr(arm, "wait_motion_done", interrupt)
    if cleanup_fails:
        monkeypatch.setattr(adapter, "stop", fail_stop)
    try:
        with pytest.raises(KeyboardInterrupt) as exc:
            arm.close()
        assert exc.value is original
        assert arm._closed
        assert arm._resources_closed is (not cleanup_fails)
        if cleanup_fails:
            assert "close also failed" in caplog.text
        monkeypatch.setattr(adapter, "stop", stop)
        arm.close()
        assert arm._resources_closed
    finally:
        monkeypatch.setattr(adapter, "stop", stop)
        arm.close()


@pytest.mark.parametrize("backend", ["dispatcher", "cantransport"])
def test_context_close_error_does_not_replace_application_error(
    constructed_arm, monkeypatch, backend, caplog
):
    _, construct, _ = constructed_arm
    monkeypatch.setenv("LINKERBOT_ARM_TRANSPORT", backend)
    arm = construct("left")
    adapter = arm._can_dispatcher
    stop = adapter.stop
    original = ValueError("application failed")

    def fail_stop():
        raise CANError("shutdown also failed")

    monkeypatch.setattr(adapter, "stop", fail_stop)
    try:
        with pytest.raises(ValueError) as exc:
            with arm:
                raise original
        assert exc.value is original
        assert "shutdown also failed" in caplog.text
        assert not arm._resources_closed
    finally:
        monkeypatch.setattr(adapter, "stop", stop)
        arm.close()
        assert arm._resources_closed
