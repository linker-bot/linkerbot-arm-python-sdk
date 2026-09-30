"""Close keeps the connection available until owned motion cleanup completes."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from linkerbot_arm import Pose, StateError
from tests.arm.h75.test_h75 import arm as arm
from tests.arm.h75.test_h75 import configure, frames

POSE = Pose(x=0.01, y=0, z=0, rx=0, ry=0, rz=0)


def watch_closing(arm, monkeypatch):
    closing = threading.Event()
    wait = arm._motion_timer._wait_worker_done

    def observed(**kwargs):
        closing.set()
        return wait(**kwargs)

    monkeypatch.setattr(arm._motion_timer, "_wait_worker_done", observed)
    return closing


def pause_first_stream_delay(arm, monkeypatch):
    entered, resume = threading.Event(), threading.Event()
    wait = arm._motion_timer._wait_cancelled

    def paused(timeout):
        if timeout > 0 and not entered.is_set():
            entered.set()
            assert resume.wait(2)
        return wait(timeout)

    monkeypatch.setattr(arm._motion_timer, "_wait_cancelled", paused)
    return entered, resume


@pytest.mark.parametrize("cancel", [False, True])
def test_close_waits_for_restoration_before_releasing_bus(arm, monkeypatch, cancel):
    configure(arm)
    saved = (
        arm.get_control_velocities(),
        arm.get_control_acceleration(),
        arm.get_control_decelerations(),
    )
    entered, resume = pause_first_stream_delay(arm, monkeypatch)
    closing = watch_closing(arm, monkeypatch)
    closed_profiles = []
    arm._can_dispatcher.stop = lambda: closed_profiles.append(
        (
            arm.get_control_velocities(),
            arm.get_control_acceleration(),
            arm.get_control_decelerations(),
        )
    )
    with ThreadPoolExecutor() as pool:
        motion = pool.submit(arm.move_l, POSE)
        try:
            assert entered.wait(1)
            closer = pool.submit(arm.close)
            assert closing.wait(1)
            assert not closer.done()
            with pytest.raises(StateError, match="closing"):
                arm.set_velocities([0.2] * 7)
            if cancel:
                arm.emergency_stop()  # stopping remains available during close
                assert not closer.done()
        finally:
            resume.set()
        motion.result(2)
        closer.result(2)
    assert closed_profiles == [saved]
    assert arm._resources_closed
    assert not arm.is_moving()


def test_close_reports_restore_error_and_still_releases_bus(arm, monkeypatch):
    configure(arm)
    entered, resume = pause_first_stream_delay(arm, monkeypatch)
    closing = watch_closing(arm, monkeypatch)
    stopped = []
    arm._can_dispatcher.stop = lambda: stopped.append(True)
    original = RuntimeError("restore failed")
    set_accel = arm.set_accelerations
    calls = 0

    def fail_restore(values):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise original
        set_accel(values)

    monkeypatch.setattr(arm, "set_accelerations", fail_restore)
    with ThreadPoolExecutor() as pool:
        motion = pool.submit(arm.move_l, POSE)
        try:
            assert entered.wait(1)
            closer = pool.submit(arm.close)
            assert closing.wait(1)
        finally:
            resume.set()
        assert motion.exception(2) is original
        assert closer.exception(2) is original
    assert stopped == [True]
    assert arm._resources_closed


def test_close_waits_for_cancelled_ik_worker_to_unwind(arm, monkeypatch):
    configure(arm)
    entered, resume = threading.Event(), threading.Event()
    closing = watch_closing(arm, monkeypatch)
    stopped = []
    arm._can_dispatcher.stop = lambda: stopped.append(True)

    def solve(*a, **k):
        entered.set()
        assert resume.wait(2)
        return [0.1] * 7

    arm.inverse_kinematics = solve
    with ThreadPoolExecutor() as pool:
        motion = pool.submit(arm.move_p, POSE, blocking=False)
        try:
            assert entered.wait(1)
            arm.emergency_stop()
            after_stop = frames(arm)
            closer = pool.submit(arm.close)
            assert closing.wait(1)
            assert not stopped and not closer.done()
        finally:
            resume.set()
        motion.result(2)
        closer.result(2)
    assert frames(arm) == after_stop
    assert stopped == [True]


def test_motion_worker_cannot_deadlock_by_closing_itself(arm):
    configure(arm)
    arm._can_dispatcher.stop = lambda: None

    def plan(*a, **k):
        arm.close()
        return [SimpleNamespace(angles=[0.1] * 7)]

    arm._kx.plan_move_l = plan
    with pytest.raises(StateError, match="active motion worker"):
        arm.move_l(POSE)
    assert not arm._closed
    arm.close()
    assert arm._resources_closed


def test_close_before_planner_reservation_prevents_late_ik(arm, monkeypatch):
    configure(arm)
    arm._can_dispatcher.stop = lambda: None
    plan_and_start = arm._motion_timer._plan_and_start

    def close_first(*args, **kwargs):
        arm.close()
        return plan_and_start(*args, **kwargs)

    monkeypatch.setattr(arm._motion_timer, "_plan_and_start", close_first)
    arm.inverse_kinematics = lambda *a, **k: pytest.fail("closed arm must not start IK")
    with pytest.raises(StateError, match="closed"):
        arm.move_p(POSE)
    assert not arm.is_moving()
