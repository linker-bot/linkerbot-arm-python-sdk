# LinkerBot Arm Python SDK

从 `linkerbot-python-sdk` 0.5.4 拆出的独立机械臂 SDK，支持 **A7、A7lite、P7**，Python 3.10+。
当前 0.6.0 开发版本的发行包名为 `linkerbot-arm`，Python 导入名为 `linkerbot_arm`。
原来的 `linkerbot.*` 导入兼容门面计划由后续聚合包提供；现有 ROS2 loader 尚待迁移，因此当前分支还不是可直接替换旧 SDK 的完整兼容版本。

## 安装

独立 Python 环境（包含运动学）：

```bash
cd linkerbot-arm
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[kinetix]'
```

三款机械臂的构造函数都需要 Pinocchio。`kinetix` extra 为纯 Python 环境安装 PyPI 的 `pin`；
ROS2 已有 Pinocchio 时安装基础包即可。Windows 可通过 Conda 安装 `pinocchio`。
**ROS2 使用系统 Python、NumPy 和 Pinocchio 的组合，安装方法见 [ROS2 接入](docs/ROS2.md)。**

当前 wheel 只提供 `linkerbot_arm`，后续将接入独立的 `linkerbot-transport`。
arm、hand、transport 与聚合包的共存安装矩阵仍待验收，进度见 [迁移 TODO](docs/ARM_TRANSPORT_MIGRATION_TODO.md)。

## 当前导入方式

```python
from linkerbot_arm import A7, A7lite, P7, ControlMode, Pose
from linkerbot_arm.arm import State, WayPoint
from linkerbot_arm.arm.a7.motor import A7Motor, SensorType
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
```

控制示例（需要已配置的 CAN 和实际机械臂）：

```python
from linkerbot_arm import A7

with A7(side="left", interface_name="can0", world_frame="urdf") as arm:
    print(arm.get_angles())
    print(arm.get_pose())
```

构造参数、返回模型、异常、枚举、运动控制、状态读取、标定、底层 motor 与 CAN 接口均沿用上游实现。
ROS2 使用的 `_set_angles`、`_motors` 也保留。API 文档：[A7](docs/zh/src/reference/a7/README.md)、
[A7lite](docs/zh/src/reference/a7lite/README.md)、[P7](docs/zh/src/reference/p7/README.md)、
[CAN](docs/zh/src/reference/can.md)。
上述详细 API 文档中部分导入示例仍使用旧 `linkerbot.*` 路径，更新工作尚未完成。

## 开发与验证

```bash
python -m pip install -e '.[kinetix,test,dev]'
python -m pytest
python tools/check_upstream.py ../linkerbot-python-sdk
python -m build
```

默认测试不连接真实机械臂。已有 A7/A7lite 真机测试保留，需要显式使用 `-m hardware`；
P7 提供无硬件接口和运动学测试，真机验证仍需部署现场执行。
接口基线固定在 `tests/compat/upstream_api.json`，不依赖旧仓库参与日常测试。

架构与实施记录见 [拆分计划](docs/SPLIT_PLAN.md)，维护约定见 [贡献指南](CONTRIBUTING.md)。
