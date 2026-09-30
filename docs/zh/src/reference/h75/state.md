# 状态读取

H75 反馈提供角度、速度、电流和温度。电流不等于关节扭矩；当前没有可靠的 Nm 换算参数。

```python
from linkerbot_arm import H75

with H75("left", "can0") as arm:
    print(arm.get_angles())
    print(arm.get_currents())
    state = arm.get_state()
    assert state.joint_torques is None
```

| 方法 | 返回值/单位 |
| --- | --- |
| `get_angles()` | 7 个实测角度，rad |
| `get_velocities()` | 7 个实测速度，rad/s |
| `get_currents()` | 7 个电流，A |
| `get_current_states()` | 7 个 `CurrentState`，字段 `current`（A）和 `timestamp`（UNIX 秒） |
| `get_temperatures()` | 7 个温度，°C |
| `get_pose()` | 根据角度缓存计算的 TCP `Pose` |
| `get_control_angles()` | 7 个最近接受的目标角度，rad |
| `get_control_velocities()` | 7 个已配置的有效 PP 速度，rad/s；未知时抛出 `StateError` |
| `get_control_acceleration()` | 7 个控制加速度，rad/s² |
| `get_control_decelerations()` | 7 个已配置的减速度，rad/s²；未知时抛出 `StateError` |
| `get_torques()` | 抛出 `StateError`，明确没有可用扭矩，不能把电流当作 Nm |

## 完整状态

`get_state()` 返回与其他型号共用的 `State`：位姿、关节角度、目标角度、实测速度、
控制速度、控制加速度、温度以及 `joint_torques=None`。
尚未配置全部关节的速度时，`joint_control_velocities=[]`，表示不可用；不填入实测速度或伪造默认值。
电流和独立减速度使用上表的专用方法获取，公共 `State` 没有这些字段。

各测量子状态包含值和 `timestamp`。时间戳来自主机处理回复时刻，
控制参数时间戳来自初始化或指令接受时刻；都不是驱动器的硬件同步时间。
`get_state()` 组合多个缓存并做 FK，不保证七关节同时采样。

## 轮询

| 反馈 | 默认间隔 |
| --- | --- |
| 角度 | 50 ms |
| 速度 | 100 ms |
| 电流 | 200 ms |
| 温度 | 2 s |

同一机械臂的轮询共用一个后台线程。间隔是调度目标，不是最大延迟保证；
通信超时、排队和断线会使缓存变旧。读取缓存成功不能证明连接在线。

```python
from linkerbot_arm.arm.h75 import SensorType

arm.start_polling({
    SensorType.POSITION: 0.05,
    SensorType.VELOCITY: 0.1,
    SensorType.CURRENT: 0.2,
    SensorType.TEMPERATURE: 2.0,
})
```

`start_polling()` 替换当前查询周期；`stop_polling()` 停止查询但不失能。
读取按电机 ID 和命令字匹配回复，并拒绝不匹配的帧类型或不完整数据。
同一寄存器没有事务序号，无法在协议层区分极晚到达的同地址旧回复。
