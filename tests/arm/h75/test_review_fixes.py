"""Regression cases for the six H75 review findings; no physical CAN."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from linkerbot_arm import ControlMode, Pose, StateError
from tests.arm.h75.test_h75 import arm as arm
from tests.arm.h75.test_h75 import configure, frames

POSE = Pose(x=0.1, y=0, z=0, rx=0, ry=0, rz=0)


@pytest.mark.parametrize("stop", ["emergency_stop", "disable"])
def test_stop_during_ik_prevents_late_target_and_keeps_planner_busy(arm, stop):
    configure(arm)
    entered, resume = threading.Event(), threading.Event()

    def ik(*a, **k):
        entered.set()
        assert resume.wait(2)
        return [0.1] * 7

    arm.inverse_kinematics = ik
    with ThreadPoolExecutor() as pool:
        motion = pool.submit(arm.move_p, POSE, blocking=False)
        try:
            assert entered.wait(1)
            assert arm.is_moving()
            getattr(arm, stop)()
            after_stop = frames(arm)
            assert arm.is_moving()  # unfinished IK still owns the request
            with pytest.raises(StateError):
                arm.move_j([0.2] * 7, blocking=False)
        finally:
            resume.set()
        motion.result(2)
    assert frames(arm) == after_stop
    assert not arm.is_moving()


def test_ik_failure_releases_motion_ownership(arm):
    configure(arm)

    def fail(*a, **k):
        raise RuntimeError("IK failed")

    arm.inverse_kinematics = fail
    with pytest.raises(RuntimeError, match="IK failed"):
        arm.move_p(POSE)
    assert not arm.is_moving()
    assert frames(arm) == []


def test_nonblocking_ik_hands_over_to_motion_timer(arm):
    configure(arm)
    arm.inverse_kinematics = lambda *a, **k: [0.1] * 7
    arm.move_p(POSE, blocking=False)
    assert len(frames(arm)) == 7
    assert arm.is_moving()
    arm.emergency_stop()
    assert not arm.is_moving()


def test_stop_during_duration_calculation_prevents_ik_target(arm, monkeypatch):
    configure(arm)
    arm.inverse_kinematics = lambda *a, **k: [0.1] * 7
    duration = arm._move_duration

    def stop_then_duration(*args):
        arm.emergency_stop()
        return duration(*args)

    monkeypatch.setattr(arm, "_move_duration", stop_then_duration)
    arm.move_p(POSE, blocking=False)
    assert len(frames(arm)) == 7  # hold only
    assert arm.get_control_angles() == [0.0] * 7


def test_mode_change_is_rejected_while_ik_owns_motion(arm):
    configure(arm)

    def ik(*a, **k):
        with pytest.raises(StateError, match="Disable"):
            arm.set_control_mode(ControlMode.CSP)
        return [0.01] * 7

    arm.inverse_kinematics = ik
    arm.move_p(POSE, blocking=False)
    assert arm._control_mode is ControlMode.PP


def test_stop_batch_bypasses_target_age_but_not_capacity(arm, monkeypatch):
    import queue
    from types import SimpleNamespace

    import linkerbot_arm._transport.targets as targets
    from tests.test_motion_batches import QueuedDispatcher

    now = [10.0]
    monkeypatch.setattr(targets, "time", SimpleNamespace(monotonic=lambda: now[0]))
    configure(arm)
    bus = QueuedDispatcher(capacity=14, clock=lambda: now[0])
    arm._can_dispatcher = bus
    for motor in arm._motors:
        motor._dispatcher = bus
    try:
        arm.set_motion_queue_policy(max_target_age_s=0.05)
        arm._set_angles([0.1] * 7)
        now[0] += 0.1
        arm.emergency_stop()
        assert bus._tx.get_health().pending_fifo == 14
        with pytest.raises(queue.Full):
            arm.emergency_stop()
        now[0] += 1
        bus._tx.drain()
        assert len(bus.sent) == 7  # expired ordinary target omitted, hold retained
        assert all(bytes(m.data) == b"\x0a\x00\x00\x00\x00" for m in bus.sent)
    finally:
        bus._tx.close()
