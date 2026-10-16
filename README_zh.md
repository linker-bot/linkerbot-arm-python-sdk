# LinkerBot Arm Python SDK

[English](README.md) | 简体中文

用于 **A7、A7lite、P7、H75** 机械臂的 Python SDK，支持关节控制、状态读取和正逆运动学。
A7lite 0.6.1 新增 MIT/CSP、逐关节模式与混合控制，见 [控制模式](docs/zh/src/reference/a7lite/README.md#控制模式)。
Python 3.10+；发行包名为 `linkerbot-arm`，导入名为 `linkerbot_arm`。
四款机械臂默认使用 `CANTransport`；设置 `LINKERBOT_ARM_TRANSPORT=dispatcher`
可显式使用低层后端，现有构造和控制调用不变。见 [后端选择](docs/TRANSPORT.md)。

## 安装

SDK 基础依赖为 NumPy >=1.24、SciPy >=1.10、Pydantic 2.x，以及
`linkerbot-transport[can]`。源码仓库为
[linker-bot/linkerbot-arm-python-sdk](https://github.com/linker-bot/linkerbot-arm-python-sdk)，
默认分支为 `main`；发行包为 `linkerbot-arm`，导入为 `linkerbot_arm`。
从 GitHub 获取并安装源码：

```bash
git clone --branch main https://github.com/linker-bot/linkerbot-arm-python-sdk.git
cd linkerbot-arm-python-sdk
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --force-reinstall --no-deps -r requirements/transport.txt
python -m pip install -e '.[kinetix]'
```

详细环境配置见[安装指南](docs/INSTALLATION.md)。

四款机械臂的构造函数均需要 Pinocchio；当前验证基线为 Pinocchio 4.1.0。
`kinetix` extra 声明 `pin>=4.1.0`，只负责 pip 安装依赖，不开关 SDK 的运动学功能。
已有兼容 Pinocchio 时可安装基础包 `python -m pip install -e .`。
ROS2 Jazzy 的已验证组合和独立部署锁见 [ROS2 接入](docs/ROS2.md)；
ROS2 环境使用基础包及兼容的系统 Pinocchio。

## 快速开始

先完成 [CAN 配置](docs/zh/src/reference/can.md)，连接并上电机械臂：

```python
from linkerbot_arm import A7

with A7(side="left", interface_name="can0") as arm:
    print(arm.get_angles())  # 七个关节角，单位 rad
    print(arm.get_pose())  # TCP 位姿
```

使用 A7lite、P7 或 H75 时，将 `A7` 换成对应类；右臂使用 `side="right"`。
构造时会打开 CAN、检查电机并读取初始状态，`with` 退出时关闭连接。
P7 还会检查第 6、7 关节的 PTM 控制模式，必要时进入 Rest 并写入、保存 Flash；
模式已正确时跳过写入。运动前须显式设置速度和加速度，详见 [P7 API](docs/zh/src/reference/p7/README.md)。

P7 的 `move_j()` / `move_p()` 使用主机关节加减速轨迹；外部 `_set_angles()` 自动限速、限加速度，
首次调用保持反馈位置，需要持续周期输入才能趋向目标。`blocking=False` 仍同步发送整段轨迹。
A7lite 软件停止持续锁存，显式 `enable()` 或成功完成 PP `home()` 后才恢复。
`close()` 等待运动参数恢复后关闭 CAN，不自动失能。具体兼容变化见[迁移说明](docs/MIGRATION.md#运动与停止行为)。

H75 支持 PP/CSP 与前两关节抱闸，电流通过 `get_currents()` 返回，扭矩暂不可用。
默认缩放参数沿用上游已测试分支，使用前应核对型号与固件。

常用导入：

```python
from linkerbot_arm import A7, A7lite, P7, H75, ControlMode, Pose
from linkerbot_arm.arm import State, WayPoint
```

## 文档

- [安装与环境配置](docs/INSTALLATION.md)
- [A7 API](docs/zh/src/reference/a7/README.md)
- [A7lite API](docs/zh/src/reference/a7lite/README.md)
- [P7 API](docs/zh/src/reference/p7/README.md)
- [H75 API](docs/zh/src/reference/h75/README.md)
- [CAN 接口](docs/zh/src/reference/can.md)
- [CAN 后端选择与故障恢复](docs/TRANSPORT.md)
- [反馈新鲜度与轻量状态接口](docs/FEEDBACK.md)
- [ROS2 接入](docs/ROS2.md)
- [从旧 SDK 迁移](docs/MIGRATION.md)
- [版本变更](CHANGELOG.md)

项目专属的开发与测试说明见[开发检查](DEVELOPMENT.md)。

## 贡献与许可证

欢迎用中文或英文参与贡献，请遵循[Linkerbot 贡献指南](https://github.com/linker-bot/.github/blob/main/CONTRIBUTING.md)。
安全问题请按[组织安全策略](https://github.com/linker-bot/.github/blob/main/SECURITY.md)私下报告。

本项目采用 [MIT 许可证](LICENSE)。
