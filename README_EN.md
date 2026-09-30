# LinkerBot Arm Python SDK

All four arm models use `CANTransport` by default. Set
`LINKERBOT_ARM_TRANSPORT=dispatcher` to explicitly use the low-level backend.
Both backends require the fixed transport source in `requirements/transport.txt`.
Arm calls remain unchanged; failed connections require closing and recreating the arm. See the
[backend guide](docs/TRANSPORT.md) for installation, recovery and validation scope.

Python SDK for **A7, A7lite, P7 and H75** robotic arms, with joint control, feedback and
forward/inverse kinematics. Requires Python 3.10+. Install `linkerbot-arm` and import `linkerbot_arm`.

## Installation

Install the pinned transport source using the [installation guide](docs/INSTALLATION.md),
then run from this repository:

```bash
python -m pip install -e '.[kinetix]'
```

All four arm constructors require Pinocchio. Use the `kinetix` extra for standalone
Python environments. ROS2 environments should use compatible system NumPy, SciPy
and Pinocchio packages; see the [ROS2 guide](docs/ROS2.md).

## Quick start

[Configure CAN](docs/zh/src/reference/can.md), connect and power the arm, then run:

```python
from linkerbot_arm import A7

with A7(side="left", interface_name="can0") as arm:
    print(arm.get_angles())  # Seven joint angles in radians
    print(arm.get_pose())  # TCP pose
```

Replace `A7` with `A7lite`, `P7` or `H75` for other models, and use `side="right"` for a right arm.
Construction opens CAN, checks the motors and reads their initial state. The context manager closes the connection.
P7 also checks the PTM mode of joints 6 and 7. When necessary it enters Rest,
writes and saves the Flash mode, then verifies the readback; an existing PTM configuration skips writes.
Set velocity and acceleration explicitly before moving. See the [P7 reference](docs/zh/src/reference/p7/README.md).

H75 supports PP/CSP and brakes on joints 1/2. Use `get_currents()` for amperes;
torque conversion is unavailable. Check the upstream scaling defaults against your motor and firmware.

## Documentation

- [Installation](docs/INSTALLATION.md)
- [A7 API](docs/zh/src/reference/a7/README.md)
- [A7lite API](docs/zh/src/reference/a7lite/README.md)
- [P7 API](docs/zh/src/reference/p7/README.md)
- [H75 API](docs/zh/src/reference/h75/README.md)
- [CAN](docs/zh/src/reference/can.md)
- [ROS2](docs/ROS2.md)
- [Migration from the legacy SDK](docs/MIGRATION.md)
- [Changelog](CHANGELOG.md)

See [CONTRIBUTING](CONTRIBUTING.md) for development and testing. [中文](README.md)
