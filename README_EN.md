# LinkerBot Arm Python SDK

Standalone A7, A7lite and P7 SDK extracted from `linkerbot-python-sdk` 0.5.4.
The 0.6.0 development distribution is named `linkerbot-arm` and imports use `linkerbot_arm`.
Legacy `linkerbot.*` forwarding belongs to the planned aggregate package. ROS2 loader
migration is still pending; this branch is not yet a drop-in replacement for the old SDK.

```bash
python3 -m venv .venv
source .venv/bin/activate
# Requires Gitea SSH access; reviewed Transport 1.0.0 source.
python -m pip install 'linkerbot-transport[can] @ git+ssh://git@git.linkerhub.work:12222/zhuzhixiang/linkerbot-transport.git@e8c8bf7cc424cffa0234e659537c64f102b22426'
python -m pip install -e '.[kinetix]'
```

```python
from linkerbot_arm import A7, A7lite, P7, Pose, ControlMode
from linkerbot_arm.arm import State, WayPoint
```

All three arm constructors require Pinocchio. Install the `kinetix` extra in standalone
environments; ROS2 installations should use their existing compatible NumPy/Pinocchio
binaries and install the base package. Python 3.10+, NumPy 1.24+, SciPy 1.10+ are required.

The current wheel contains only `linkerbot_arm` and depends on `linkerbot-transport[can]>=1.0,<2.0`.
CAN workers are delegated to the low-level dispatcher through an arm compatibility adapter;
motor protocols and arm constructors remain unchanged. See the [phase-3 record](docs/PHASE3_TRANSPORT.md)
for authenticated package installation and validation. The arm/hand/transport installation matrix is still pending. Detailed API pages
also contain legacy imports awaiting updates; see the [migration TODO](docs/ARM_TRANSPORT_MIGRATION_TODO.md).

For development, install `.[kinetix,test,dev]` and run `python -m pytest` and `python -m build`.
Hardware tests are excluded by default. See the [Chinese README](README.md),
[migration guide](docs/MIGRATION.md), [ROS2 guide](docs/ROS2.md) and [architecture decisions](docs/SPLIT_PLAN.md).
