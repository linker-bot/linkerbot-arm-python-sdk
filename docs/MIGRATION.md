# 从旧 SDK 迁移

`linkerbot-arm` 0.6.x 使用 `linkerbot_arm` 命名空间。该发行包不提供旧 `linkerbot.*`
导入路径，升级应用时需要更新导入。

## 导入映射

| 旧导入 | 当前导入 |
| --- | --- |
| `from linkerbot import A7, A7lite, P7, Pose, ControlMode` | `from linkerbot_arm import A7, A7lite, P7, Pose, ControlMode` |
| `from linkerbot.arm import State, WayPoint` | `from linkerbot_arm.arm import State, WayPoint` |
| `from linkerbot.arm.a7.motor import A7Motor, SensorType` | `from linkerbot_arm.arm.a7.motor import A7Motor, SensorType` |
| `from linkerbot.arm.p7.motor_v2 import MotorV2` | `from linkerbot_arm.arm.p7.motor_v2 import MotorV2` |
| `from linkerbot.arm.kinetix import ArmKinetix` | `from linkerbot_arm.arm.kinetix import ArmKinetix` |
| `from linkerbot.comm import CANMessageDispatcher` | `from linkerbot_arm.comm import CANMessageDispatcher` |
| `from linkerbot.exceptions import StateError` | `from linkerbot_arm.exceptions import StateError` |

arm 构造参数和已有方法调用保持兼容，包括 `_set_angles()` 和 `_motors`。
底层 dispatcher 的 `send()` 仍返回 `None`，队列满仍抛出 `queue.Full`，
总线故障后的发送仍抛出 arm 的 `CANError`。

## 安装

按照[安装指南](INSTALLATION.md)在独立环境安装 SDK 和 transport 1.0.0。
确认应用加载当前命名空间：

```bash
python -c "import linkerbot_arm; from linkerbot_arm import A7, A7lite, P7; print(linkerbot_arm.__file__)"
```

仅安装新发行包不会重定向应用已有的 `import linkerbot`。
需要灵巧手的应用仍须保留自己的 hand SDK 依赖；arm 包不包含手部驱动。

## ROS2 应用

检查所用 ROS2 版本的适配器导入。仍使用 `from linkerbot import ...` 的适配器需要旧 SDK，
不能只替换安装包就切换到 `linkerbot_arm`。支持新命名空间的接入方式和环境要求见 [ROS2 接入](ROS2.md)。

## 回滚

保留原应用环境及对应 SDK 版本。回滚时恢复应用导入代码和原环境的依赖组合，
避免仅回退包版本却保留新命名空间导入。
