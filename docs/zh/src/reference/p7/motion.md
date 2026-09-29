# 运动控制

P7 的索引 `0–4` 为 V1 电机，索引 `5–6` 为 V2 电机。V2 的 PTM 位置环没有驱动端轨迹生成器，
`move_j()` / `move_l()` 通过主机路点控制七轴。执行期间临时提高速度、加速度设置，结束后恢复。
示例目标用于说明接口；运行前应确认零位、安装姿态、工具和运动空间。

## 回零

`home(*, blocking=True)` 将所有关节移动到零角度（`[0.0] * 7`），不执行零位标定。
其调用语义与 `move_j()` 相同。

```python
from linkerbot_arm import P7

with P7(side="left", interface_name="can0") as arm:
    arm.set_velocities([0.3] * 7)
    arm.set_accelerations([5.0] * 7)
    arm.enable()
    arm.home()
    arm.disable()
```

V2 初始速度缓存为零，执行非零位移前需要显式设置速度和加速度，详见[参数配置](config.md)。

## move_j

```python
arm.move_j([0.0, 0.0, 0.0, 0.3, 0.0, 0.0, 0.0], blocking=True)
```

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `target_joints` | `list[float]` | 必填 | 7 个目标关节角度，单位 rad |
| `blocking` | `bool` | `True` | 是否保留整段路点发送后的末次等待 |

主机根据各关节的位移、速度和加速度估算时长，再对起止角度做线性插值。
**`blocking=False` 仍在调用内发送整段轨迹，只省略最后的短暂等待，不启动后台运动任务。**
`home(blocking=False)` 同样如此。

**异常：**

- `ValueError`：目标列表长度不是 7。
- `ValidationError`：角度非有限、不能表示为 float32，或超出关节限位。
- `StateError`：已有运动进行中，或非零位移对应的速度、加速度缺失、为零或非有限值。

## move_p

通过逆运动学求解目标角度，再一次性提交七轴目标。末端路径不保证为直线。
当前实现没有复用 `move_j()` 路点插值，V2 会直接跟踪目标位置。
若需要主机插值，可先调用 `inverse_kinematics()`，再将结果传给 `move_j()`。

```python
# 用当前 P7 模型生成目标，避免混用其他型号或坐标系的位姿。
target = arm.forward_kinematics([0.0, 0.0, 0.0, 0.3, 0.0, 0.0, 0.0])
arm.move_p(target, blocking=True)
```

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `target_pose` | `Pose` | 必填 | 当前世界坐标系下的 TCP 位姿，单位 m、rad |
| `current_angles` | `list[float] \| None` | `None` | IK 初始猜测；省略时使用角度缓存 |
| `blocking` | `bool` | `True` | 是否按估算时长等待；`False` 时目标提交后返回 |

`StateError` 表示已有运动或运动计时参数无效，`RuntimeError` 表示 IK 求解失败。
求解结果仍需通过目标值校验；无效目标可能抛出 `ValueError` / `ValidationError`。

## move_l

末端位置沿笛卡尔空间直线规划，姿态使用 Slerp 插值。
`move_l()` 始终同步执行，没有 `blocking` 参数。

```python
# 从当前 TCP 位姿沿当前世界坐标系 X 方向平移 1 cm。
# 示例仍可能因可达性或关节限位而规划失败。
start_angles = arm.get_angles()
start_pose = arm.forward_kinematics(start_angles)
target = start_pose.model_copy(update={"x": start_pose.x + 0.01})
arm.move_l(target, current_angles=start_angles, current_pose=start_pose)
```

| 参数 | 类型 | 默认值 | 范围或说明 |
| --- | --- | --- | --- |
| `target_pose` | `Pose` | 必填 | 目标 TCP 位姿，单位 m、rad |
| `max_velocity` | `float` | 0.05 | (0, 0.4] m/s |
| `max_angular_velocity` | `float` | 0.3 | (0, 3.0] rad/s |
| `acceleration` | `float` | 0.1 | (0, 1.0] m/s² |
| `angular_acceleration` | `float` | 0.1 | (0, 1.0] rad/s² |
| `current_pose` | `Pose \| None` | `None` | 起始位姿；指定时必须同时提供 `current_angles` |
| `current_angles` | `list[float] \| None` | `None` | 起始关节角度；省略时使用角度缓存 |

同时提供起始角度和位姿时，会核对正运动学结果；不一致则发出警告并使用 FK 位姿。
SDK 先完成整段规划并校验所有关节目标，再调整参数和发送路点。
规划失败不会修改电机参数或提交部分轨迹。

**异常：**

- `StateError`：已有运动进行中，或规划所需状态无效。
- `ValidationError`：速度、加速度或规划后的目标不合法。
- `ValueError`：仅提供 `current_pose` 而没有 `current_angles`，或目标列表长度错误。
- `RuntimeError`：路径点 IK 求解失败。

## 提交、完成与停止

`move_j()` / `move_l()` 每次路点提交完成后至少等待 10 ms 再提交下一点。
约 100 Hz 是目标节奏；通信变慢或调度晚醒会延长执行时间，不追赶补发或自动丢点。
`is_moving()` 在规划、路点发送和参数恢复期间保持 `True`。

运动完成按 SDK 计时或主机提交进度判断，**不是电机实际到位确认**。
`get_angles()` 等返回缓存反馈，必要时应结合状态与时间戳判断实际跟踪情况。

```python
# move_p 可以在目标提交后按估算时长异步等待。
arm.move_p(target, blocking=False)
if arm.is_moving():
    arm.wait_motion_done()
```

`emergency_stop()` 和 `disable()` 会取消后续运动提交，但不能撤销已进入 CAN FIFO 的帧。
`home_cancellable(cancel_event)` 可在其他线程设置事件时结束回零提交，调用方仍应按需发出停止或失能操作。
`close()` 释放连接，不自动失能。

失败或取消时会尝试恢复原速度和加速度。一类参数恢复失败仍尝试另一类，并报告失败；
如果运动操作本身也失败，保留原始异常，将恢复错误写入日志。
恢复调用成功表示 SDK 接受参数，不保证所有电机已经执行。通信或入队失败也会传播给调用方，
包括 `CANError`、`TimeoutError`、`queue.Full`；队列诊断见 [CAN 接口](../can.md)。

## 直接流式关节控制

已有集成可继续使用 `arm._set_angles(angles)` 提交 7 个关节目标，默认检查 URDF 限位。
该方法不生成轨迹，调用方负责路点和节奏。七轴目标整组入队，被拒绝时不更新目标缓存。
V2 心跳不会重新激活过期或失败的目标；队列接受和缓存更新不代表硬件已执行。
