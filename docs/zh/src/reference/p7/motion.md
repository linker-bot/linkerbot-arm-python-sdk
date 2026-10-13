# 运动控制

P7 的索引 `0–4` 为 V1 电机，索引 `5–6` 为 V2 电机。V2 的 PTM 位置环没有驱动端轨迹生成器，
`move_j()` / `move_p()` / `move_l()` 通过主机路点控制七轴。执行期间临时提高驱动端速度、加速度设置，结束后恢复；
`move_j()` / `move_p()` 的主机轨迹仍按调用前配置的关节速度、加速度规划。
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

主机为各关节生成梯形或三角形加减速曲线，将较短的曲线按最长轴时长放慢，实现同步到达。
每个点提交前还根据真实间隔校验调用前的速度、加速度配置；调度停顿后若直接发送会超限，
则继续可取消地等待同一个路点。路点和各轴同步关系保持不变，实际执行时长可能延长。
**`blocking=False` 仍在调用内发送整段轨迹，只省略最后的短暂等待，不启动后台运动任务。**
`home(blocking=False)` 同样如此。

**异常：**

- `ValueError`：目标列表长度不是 7。
- `ValidationError`：角度非有限、不能表示为 float32，或超出关节限位。
- `StateError`：已有运动进行中，或非零位移对应的速度、加速度缺失、为零或非有限值。

## move_p

通过逆运动学求解目标角度，再执行与 `move_j()` 相同的关节加减速轨迹。末端路径不保证为直线。
IK 求解期间已占有本次运动，`is_moving()` 为 `True`；停止或失能后，求解返回也不会提交该次目标。
关闭会等待已开始的规划、发送及参数恢复结束，再释放 CAN。

```python
# 用当前 P7 模型生成目标，避免混用其他型号或坐标系的位姿。
target = arm.forward_kinematics([0.0, 0.0, 0.0, 0.3, 0.0, 0.0, 0.0])
arm.move_p(target, blocking=True)
```

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `target_pose` | `Pose` | 必填 | 当前世界坐标系下的 TCP 位姿，单位 m、rad |
| `current_angles` | `list[float] \| None` | `None` | IK 初始猜测；省略时使用角度缓存 |
| `blocking` | `bool` | `True` | 是否保留整段路点发送后的末次等待；`False` 仍同步规划并发送整段轨迹 |

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

这些速度、加速度参数约束 TCP 的笛卡尔轨迹。`move_l()` 不对 IK 路点再次应用外部关节限幅，
因此不保证靠近奇异位形时每个关节都符合 `set_velocities()` / `set_accelerations()` 的上限；
应结合关节反馈和具体路径降低 TCP 速度。

**异常：**

- `StateError`：已有运动进行中，或规划所需状态无效。
- `ValidationError`：速度、加速度或规划后的目标不合法。
- `ValueError`：仅提供 `current_pose` 而没有 `current_angles`，或目标列表长度错误。
- `RuntimeError`：路径点 IK 求解失败。

## 提交、完成与停止

`move_j()` / `move_p()` / `move_l()` 每次路点提交完成后至少等待 10 ms 再提交下一点。
约 100 Hz 是目标节奏；通信变慢或调度晚醒会延长执行时间，不追赶补发或自动丢点。
`is_moving()` 在规划、路点发送和参数恢复期间保持 `True`。

运动完成按 SDK 计时或主机提交进度判断，**不是电机实际到位确认**。
`get_angles()` 等返回缓存反馈，必要时应结合状态与时间戳判断实际跟踪情况。

```python
# blocking=False 仍同步发送整段轨迹，仅省略末次等待。
arm.move_p(target, blocking=False)
```

`emergency_stop()` 和 `disable()` 会取消后续运动提交，但不能撤销已进入 CAN FIFO 的帧。
`home_cancellable(cancel_event)` 可在其他线程设置事件时结束回零提交，调用方仍应按需发出停止或失能操作。
`close()` 等待运动 worker 完成参数恢复，再停止轮询和关闭 CAN，不自动失能。
关闭开始后拒绝新运动和外部目标；不能从本次运动 worker 内调用 `close()`。

失败或取消时会尝试恢复原速度和加速度。一类参数恢复失败仍尝试另一类，并报告失败；
如果运动操作本身也失败，保留原始异常，将恢复错误写入日志。
恢复调用成功表示 SDK 接受参数，不保证所有电机已经执行。通信或入队失败也会传播给调用方，
包括 `CANError`、`TimeoutError`、`queue.Full`；队列诊断见 [CAN 接口](../can.md)。

## 直接流式关节控制

已有集成可继续使用 `arm._set_angles(angles)` 提交 7 个关节目标，默认检查 URDF 限位。
该方法根据已接纳目标和单调时间，自动限制七轴目标轨迹的速度、加速度。调用方仍负责周期发送：
首次调用只提交反馈位置作为保持目标，后续调用才逐步趋向外部目标；单条指令不会自动执行到终点。
限幅使用两次接纳之间的实际时间间隔；输入中断后如需重新从反馈位置开始，应先按应用流程停止并恢复。
开始 SDK 运动时拒绝并行外部目标；使能、失能、停止或修改速度/加速度后重新从反馈播种。
七轴目标整组入队，被拒绝时不更新目标缓存或限幅器状态。
主机限幅约束发送的目标曲线，不证明电机实测速度、加速度或实际到位。
V2 心跳不会重新激活过期或失败的目标；队列接受和缓存更新不代表硬件已执行。
