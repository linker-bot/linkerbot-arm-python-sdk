# 状态读取

## 完整状态快照

从各关节缓存组合状态，并通过 FK 计算 TCP 位姿。它不是硬件同步采样，
包含实测角度、速度、扭矩、温度以及主机控制参数；没有实测加速度字段。

```python
from linkerbot_arm import P7

with P7(side="left", interface_name="can0") as arm:
    state = arm.get_state()
    print(state.pose)
    print(f"第一个关节实际角度：{state.joint_angles[0].angle:.4f} rad")
```

**返回值**

- `State`: 包含 `pose`、`joint_angles`、`joint_control_angles`、`joint_velocities`、`joint_control_velocities`、`joint_control_acceleration`、`joint_torques`、`joint_temperatures`

### State 数据模型

| 属性                         | 说明                                            |
| ---------------------------- | ----------------------------------------------- |
| `pose`                       | TCP 位姿（Pose）                                |
| `joint_angles`               | 7 个关节的实际角度（list[AngleState]）          |
| `joint_control_angles`       | 7 个关节的控制角度（list[AngleState]）          |
| `joint_velocities`           | 7 个关节的实际速度（list[VelocityState]）       |
| `joint_control_velocities`   | 7 个关节的控制速度（list[VelocityState]）       |
| `joint_control_acceleration` | 7 个关节的控制加速度（list[AccelerationState]） |
| `joint_torques`              | 7 个关节的实际扭矩（list[TorqueState]）         |
| `joint_temperatures`         | 7 个关节的温度（list[TemperatureState]）        |

各子状态模型均包含值字段和 `timestamp`（UNIX 时间戳，秒）。
实测状态的时间戳来自主机解码时刻；控制状态的时间戳来自本地设置或初始化，不能当作硬件采样时间。
V1 的 `joint_control_velocities` 是驱动轨迹速度，V2 的该字段与加速度字段仅为主机缓存。

### 子状态模型字段

| 模型                | 值字段          | 时间戳字段   |
| ------------------- | --------------- | ------------ |
| `AngleState`        | `.angle`        | `.timestamp` |
| `VelocityState`     | `.velocity`     | `.timestamp` |
| `AccelerationState` | `.acceleration` | `.timestamp` |
| `TorqueState`       | `.torque`       | `.timestamp` |
| `TemperatureState`  | `.temperature`  | `.timestamp` |

## 单项状态读取

除 `get_state()` 外，以下方法分别返回单一类型的状态数据，均返回 7 个关节的列表（`get_pose()` 除外）。

```python
from linkerbot_arm import P7

with P7(side="left", interface_name="can0") as arm:
    angles = arm.get_angles()
    velocities = arm.get_velocities()
    temps = arm.get_temperatures()
    pose = arm.get_pose()
    print(f"第二个关节实际角度：{angles[1]:.4f} rad")
    print(f"第三个关节实际速度：{velocities[2]:.4f} rad/s")
    print(f"第四个关节实际温度：{temps[3]:.1f} °C")
    print(f"TCP: ({pose.x:.3f}m, {pose.y:.3f}m, {pose.z:.3f}m)")
```

**返回值**

| 方法                         | 返回值               | 单位   |
| ---------------------------- | -------------------- | ------ |
| `get_angles()`               | 7 个关节的实际角度   | rad    |
| `get_control_angles()`       | 7 个关节的控制角度   | rad    |
| `get_velocities()`           | 7 个关节的实际速度   | rad/s  |
| `get_control_velocities()`   | 7 个关节的控制速度   | rad/s  |
| `get_control_acceleration()` | 7 个关节的控制加速度 | rad/s² |
| `get_torques()`              | 7 个关节的实际扭矩   | Nm     |
| `get_temperatures()`         | 7 个关节的温度       | °C     |
| `get_pose()`                 | TCP 位姿             | m, rad |

## 传感器数据与心跳

构造时自动启动 V1 轮询和 V2 心跳，`get_*()` 读取最近缓存，不强制刷新全部电机。

| 电机 | 数据来源 | 默认周期 |
| --- | --- | --- |
| V1（索引 0–4） | 主机轮询角度、速度 | 各 10 ms |
| V1（索引 0–4） | 主机轮询扭矩 | 50 ms |
| V1（索引 0–4） | 主机轮询温度 | 1000 ms |
| V2（索引 5–6） | 每条控制命令的反馈帧同时包含角度、速度、扭矩、温度和故障码 | 随命令更新；空闲心跳目标周期 200 ms |

这些周期不是最大延迟保证。通信排队、丢帧或断线会使缓存变旧，单独读取一个数值不能确认电机在线。
V2 默认通信看门狗约 1 秒，固件配置可能不同；心跳用于维持通信，不能替代连接健康检查。

`start_polling(intervals)` 仅改变 V1 各传感器的轮询周期，V2 忽略 `intervals`，
继续使用固定的 200 ms 心跳。`stop_polling()` 同时停止 V1 轮询和 V2 心跳；长时间停用心跳可能触发 V2 看门狗。

```python
from linkerbot_arm import P7
from linkerbot_arm.arm.p7 import SensorType

with P7(side="left", interface_name="can0") as arm:
    arm.start_polling({
        SensorType.POSITION: 0.01,
        SensorType.VELOCITY: 0.01,
        SensorType.TORQUE: 0.05,
        SensorType.TEMPERATURE: 1.0,
    })
    print(arm.get_state())
```

V2 底层 `MotorV2.fault_code` 返回缓存的故障码；整臂 `State` 没有故障码字段。
故障码含义应以对应电机固件的协议说明为准。
