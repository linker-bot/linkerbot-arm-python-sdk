# LinkerBot Arm Python SDK

Python SDK for **A7, A7lite and P7** robotic arms, with joint control, feedback and
forward/inverse kinematics. Requires Python 3.10+. Install `linkerbot-arm` and import `linkerbot_arm`.

## Installation

Install `linkerbot-transport==1.0.0` using the [installation guide](docs/INSTALLATION.md),
then run from this repository:

```bash
python -m pip install -e '.[kinetix]'
```

All three arm constructors require Pinocchio. Use the `kinetix` extra for standalone
Python environments. ROS2 environments should use compatible system NumPy, SciPy
and Pinocchio packages; see the [ROS2 guide](docs/ROS2.md).

## Quick start

[Configure CAN](docs/zh/src/reference/can.md), connect and power the arm, then run:

```python
from linkerbot_arm import A7

with A7(side="left", interface_name="can0") as arm:
    print(arm.get_angles())  # Seven joint angles in radians
    print(arm.get_pose())   # TCP pose
```

Replace `A7` with `A7lite` or `P7` for other models, and use `side="right"` for a right arm.
Construction opens CAN, checks the motors and reads their initial state. The context manager closes the connection.

## Documentation

- [Installation](docs/INSTALLATION.md)
- [A7 API](docs/zh/src/reference/a7/README.md)
- [A7lite API](docs/zh/src/reference/a7lite/README.md)
- [P7 API](docs/zh/src/reference/p7/README.md)
- [CAN](docs/zh/src/reference/can.md)
- [ROS2](docs/ROS2.md)
- [Migration from the legacy SDK](docs/MIGRATION.md)
- [Changelog](CHANGELOG.md)

See [CONTRIBUTING](CONTRIBUTING.md) for development and testing. [中文](README.md)
