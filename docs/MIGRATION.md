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

### P7 的 PTM 控制

P7 第 6、7 关节已同步完整 SDK 的 PTM 控制修复。整臂方法签名保持不变，
但构造会检查控制模式，必要时将电机 Flash Control Mode 从旧模式改为 `0x02`、保存并读回验证。
V2 位置增益初始值改为 Kp=4、Kd=15，速度前馈默认为零；
`set_velocity_kps()` / `set_velocity_kis()` 对这两个关节无操作，
`set_velocities()` 只更新其主机规划速度缓存。旧 Servo 参数不能直接作为 PTM 调参依据。

使用底层 `MotorV2` 时，应在发送 PTM 目标或启动心跳前调用 `ensure_ptm_mode()`，
并停止其他控制发送；正常使用 `P7` 时构造流程已完成此步骤。
内部编码 helper `_build_servo_frame()` 已替换为 `_build_ptm_frame()`，
集成应使用 `set_angle()` 或整臂 `_set_angles()` 提交目标。

仅回退 Python 包不会恢复电机 Flash 控制模式。回退到 Servo 驱动前，需要按电机配置流程
恢复与旧驱动匹配的模式；不要向 PTM 模式的电机发送旧 Servo 帧。
完整参数和持久化限制见 [P7 参数配置](zh/src/reference/p7/config.md)。

### 应用环境

保留原应用环境及对应 SDK 版本。回滚时恢复应用导入代码和原环境的依赖组合，
避免仅回退包版本却保留新命名空间导入。
