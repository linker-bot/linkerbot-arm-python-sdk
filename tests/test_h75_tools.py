"""CLI defaults and calibration admission are verified without opening CAN."""

import importlib.util
from pathlib import Path

import pytest


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "tools" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Arm:
    def __init__(self):
        self.events = []
        self.motor_enabled = False
        self._motors = [self.Motor(self, mid) for mid in range(61, 68)]

    class Motor:
        def __init__(self, arm, mid):
            self.arm, self._id = arm, mid

        def _read_register(self, cmd):
            self.arm.events.append(("read", self._id, cmd))
            return bytes([int(self.arm.motor_enabled)])

        def _decode_sensor(self, sensor, data):
            return 0.0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.events.append("close")

    def get_angles(self):
        return [0.0] * 7

    get_velocities = get_currents = get_temperatures = get_angles

    def get_joint_limits(self):
        return [(-1, 1)] * 7

    def set_velocities(self, values):
        self.events.append("velocity")

    def set_accelerations(self, values):
        self.events.append("acceleration")

    def enable(self):
        self.events.append("enable")

    def disable(self):
        self.events.append("disable")

    def home(self):
        self.events.append("home")

    def move_j(self, target):
        self.events.append(("move_j", target))

    def stop_polling(self):
        self.events.append("stop_polling")

    def calibrate_zero(self):
        self.events.append("calibrate_zero")


@pytest.mark.parametrize(
    "name,args",
    [
        ("h75_calibrate_zero", []),
        ("h75_calibrate_zero", ["--yes", "--settle", "nan"]),
        ("h75_smoke", ["--stage", "jog", "--delta", "0.2"]),
        ("h75_smoke", ["--hold", "inf"]),
    ],
)
def test_invalid_cli_or_missing_zero_confirmation_never_opens_can(
    monkeypatch, name, args
):
    tool = load(name)
    monkeypatch.setattr(tool, "H75", lambda *a, **k: pytest.fail("must not open CAN"))
    with pytest.raises(SystemExit):
        tool.main(["--side", "left", "--interface", "can0", *args])


def test_default_smoke_stage_performs_no_control_writes(monkeypatch):
    tool, arm = load("h75_smoke"), Arm()
    monkeypatch.setattr(tool, "H75", lambda *a, **k: arm)
    assert tool.main(["--side", "left", "--interface", "can0"]) == 0
    assert arm.events == ["close"]


@pytest.mark.parametrize("stage", ["enable", "jog", "home"])
def test_requested_operation_disables_and_closes(monkeypatch, stage):
    tool, arm = load("h75_smoke"), Arm()
    monkeypatch.setattr(tool, "H75", lambda *a, **k: arm)
    assert (
        tool.main(
            ["--side", "left", "--interface", "can0", "--stage", stage, "--hold", "0"]
        )
        == 0
    )
    assert arm.events[:3] == ["velocity", "acceleration", "enable"]
    assert arm.events[-2:] == ["disable", "close"]
    if stage == "jog":
        assert ("move_j", [0, 0, 0, 0.05, 0, 0, 0]) in arm.events


def test_primary_failure_survives_disable_failure(monkeypatch):
    tool, arm = load("h75_smoke"), Arm()
    monkeypatch.setattr(tool, "H75", lambda *a, **k: arm)
    original = RuntimeError("enable failed")

    def fail_enable():
        raise original

    def fail_disable():
        raise RuntimeError("cleanup failed")

    arm.enable, arm.disable = fail_enable, fail_disable
    with pytest.raises(RuntimeError) as exc:
        tool.main(["--side", "left", "--interface", "can0", "--stage", "enable"])
    assert exc.value is original
    assert arm.events[-1] == "close"


def test_calibration_queries_disable_and_fresh_positions(monkeypatch):
    tool, arm = load("h75_calibrate_zero"), Arm()
    monkeypatch.setattr(tool, "H75", lambda *a, **k: arm)
    assert (
        tool.main(["--side", "left", "--interface", "can0", "--yes", "--settle", "0"])
        == 0
    )
    assert arm.events[:2] == ["stop_polling", "disable"]
    at = arm.events.index("calibrate_zero")
    assert all(e[2] == 0x2B for e in arm.events[2:at])
    assert len(arm.events[2:at]) == 7
    assert arm.events[at + 1 : -1] == [("read", mid, 6) for mid in range(61, 68)]
    assert arm.events[-1] == "close"


def test_calibration_refuses_reported_enabled_motor(monkeypatch):
    tool, arm = load("h75_calibrate_zero"), Arm()
    arm.motor_enabled = True
    monkeypatch.setattr(tool, "H75", lambda *a, **k: arm)
    with pytest.raises(tool.StateError, match="仍处于使能"):
        tool.main(["--side", "left", "--interface", "can0", "--yes"])
    assert "calibrate_zero" not in arm.events
    assert arm.events[-1] == "close"
