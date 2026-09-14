# LinkerBot Arm Python SDK

Standalone A7, A7lite and P7 SDK extracted from `linkerbot-python-sdk` 0.5.4.
The distribution is named `linkerbot-arm`; all existing arm imports still use `linkerbot`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[kinetix]'
```

```python
from linkerbot import A7, A7lite, P7, Pose, ControlMode
from linkerbot.arm import State, WayPoint
```

All three arm constructors require Pinocchio. Install the `kinetix` extra in standalone
environments; ROS2 installations should use their existing compatible NumPy/Pinocchio
binaries and install the base package. Python 3.10+, NumPy 1.24+, SciPy 1.10+ are required.

Do not co-install this distribution with `linkerbot` or the historical `linkerbot-py`
distribution: they own the same Python paths. Applications needing both hands and arms
in one process should continue using the full SDK until a coordinated namespace migration.

For development, install `.[kinetix,test,dev]` and run `python -m pytest` and `python -m build`.
Hardware tests are excluded by default. See the [Chinese README](README.md),
[migration guide](docs/MIGRATION.md), [ROS2 guide](docs/ROS2.md) and [architecture decisions](docs/SPLIT_PLAN.md).
