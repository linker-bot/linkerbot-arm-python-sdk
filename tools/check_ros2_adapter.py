"""Run the actual ROS2 adapter contract tests against canonical arm classes.

Usage: python tools/check_ros2_adapter.py /path/to/linker_arm_ros2

The process-only aliases bridge the old loader for this test. This is not a
production compatibility shim or acceptance of the phase-5 loader migration.
The ROS2 checkout and its tests are read without modification.
"""

import argparse
import importlib
import sys
from pathlib import Path

import pytest

import linkerbot_arm
import linkerbot_arm.arm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ros2_repo", type=Path)
    args = parser.parse_args()
    repo = args.ros2_repo.resolve()
    test = repo / "tests/test_sdk_adapter.py"
    if not test.is_file():
        parser.error(f"ROS2 adapter contract tests not found: {test}")
    sys.path.insert(0, str(repo))
    sys.modules["linkerbot"] = linkerbot_arm
    sys.modules["linkerbot.arm"] = linkerbot_arm.arm
    adapter = importlib.import_module("linker_arm_ros2.sdk_adapter")
    assert Path(adapter.__file__).resolve().is_relative_to(repo)
    assert adapter._ARM_CLASSES == {
        "a7": linkerbot_arm.A7,
        "a7lite": linkerbot_arm.A7lite,
        "p7": linkerbot_arm.P7,
    }
    print(f"Testing ROS2 adapter: {adapter.__file__}")
    print(f"Canonical arm SDK: {linkerbot_arm.__file__}")
    return pytest.main([str(test), "-q", "--tb=short"])


if __name__ == "__main__":
    raise SystemExit(main())
