# LinkerBot Arm Python SDK

用于 **A7、A7lite、P7** 机械臂的 Python SDK，支持关节控制、状态读取和正逆运动学。
Python 3.10+；发行包名为 `linkerbot-arm`，导入名为 `linkerbot_arm`。

## 安装

按[安装指南](docs/INSTALLATION.md)安装 `linkerbot-transport==1.0.0` 后，在本仓库目录执行：

```bash
python -m pip install -e '.[kinetix]'
```

三款机械臂的构造函数均需要 Pinocchio。独立 Python 环境安装 `kinetix` extra；
ROS2 环境使用系统兼容的 NumPy、SciPy 和 Pinocchio，见 [ROS2 接入](docs/ROS2.md)。

## 快速开始

先完成 [CAN 配置](docs/zh/src/reference/can.md)，连接并上电机械臂：

```python
from linkerbot_arm import A7

with A7(side="left", interface_name="can0") as arm:
    print(arm.get_angles())  # 七个关节角，单位 rad
    print(arm.get_pose())   # TCP 位姿
```

使用 A7lite 或 P7 时，将 `A7` 换成对应类；右臂使用 `side="right"`。
构造时会打开 CAN、检查电机并读取初始状态，`with` 退出时关闭连接。

常用导入：

```python
from linkerbot_arm import A7, A7lite, P7, ControlMode, Pose
from linkerbot_arm.arm import State, WayPoint
```

## 文档

- [安装与环境配置](docs/INSTALLATION.md)
- [A7 API](docs/zh/src/reference/a7/README.md)
- [A7lite API](docs/zh/src/reference/a7lite/README.md)
- [P7 API](docs/zh/src/reference/p7/README.md)
- [CAN 接口](docs/zh/src/reference/can.md)
- [ROS2 接入](docs/ROS2.md)
- [从旧 SDK 迁移](docs/MIGRATION.md)
- [版本变更](CHANGELOG.md)

开发、测试和贡献方式见[贡献指南](CONTRIBUTING.md)。[English](README_EN.md)
