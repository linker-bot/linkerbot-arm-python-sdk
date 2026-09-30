"""Configuration admission/cache linearization and motion ownership."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from linkerbot_arm import StateError
from linkerbot_arm.arm.h75 import H75Motor
from linkerbot_arm.arm.h75.iq24 import (
    iq24_be_to_float,
    profile_velocity_iq_to_joint_rad_s,
)
from tests.arm.h75.test_h75 import arm as arm
from tests.arm.h75.test_h75 import configure
from tests.test_transport_frames import FakeDispatcher


@pytest.mark.parametrize("whole_arm", [False, True])
def test_competing_writers_keep_cache_equal_to_last_wire_value(arm, whole_arm):
    configure(arm)
    motor = arm._motors[0] if whole_arm else H75Motor(61, FakeDispatcher())
    bus = arm._can_dispatcher if whole_arm else motor._dispatcher
    setter = arm.set_velocities if whole_arm else motor.set_velocity

    def write(value):
        setter([value] * 7 if whole_arm else value)

    entered, resume, b_started, b_done = (threading.Event() for _ in range(4))
    send = bus.send

    def pause_first(message):
        send(message)
        if not entered.is_set():
            entered.set()
            assert resume.wait(2)

    bus.send = pause_first

    def second():
        b_started.set()
        write(0.1)
        b_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(write, 1.0)
        try:
            assert entered.wait(1)
            b = pool.submit(second)
            assert b_started.wait(1)
            assert not b_done.wait(0.05)
        finally:
            resume.set()
        a.result(2)
        b.result(2)
    last = [m for m in bus.sent if m.arbitration_id == 61 and m.data[0] == 0x1F][-1]
    wire = profile_velocity_iq_to_joint_rad_s(iq24_be_to_float(bytes(last.data[1:])))
    assert motor.control_velocity.velocity == wire
    assert wire == pytest.approx(0.1, abs=1e-7)
    if whole_arm:
        assert arm.get_control_velocities() == [wire] * 7


def test_profile_read_waits_for_whole_arm_write_to_complete(arm):
    configure(arm)
    entered, resume, read_started, read_done = (threading.Event() for _ in range(4))
    send = arm._can_dispatcher.send

    def pause(message):
        send(message)
        if not entered.is_set():
            entered.set()
            assert resume.wait(2)

    arm._can_dispatcher.send = pause

    def read():
        read_started.set()
        values = arm.get_control_velocities()
        read_done.set()
        return values

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(arm.set_velocities, [1.0] * 7)
        try:
            assert entered.wait(1)
            reader = pool.submit(read)
            assert read_started.wait(1)
            assert not read_done.wait(0.05)
        finally:
            resume.set()
        writer.result(2)
        assert reader.result(2) == [1.0] * 7


@pytest.mark.parametrize(
    "method",
    [
        "set_velocities",
        "set_accelerations",
        "set_decelerations",
        "set_position_kps",
        "set_velocity_kps",
        "set_velocity_kis",
    ],
)
def test_external_configuration_cannot_override_active_motion_restore(arm, method):
    configure(arm)
    with arm._motion_timer._stream_scope():
        with ThreadPoolExecutor() as pool:
            future = pool.submit(getattr(arm, method), [0.1] * 7)
            with pytest.raises(StateError, match="during active motion"):
                future.result(1)
        # The owner still needs the same methods to install and restore profiles.
        getattr(arm, method)([0.1] * 7)
