# 运动控制

运动示例需先核对机械零位、工具、安装姿态与运动空间。参数示例不作为所有负载下的运行推荐值。

## PP 回零与点位运动

每次连接后显式设置速度和加减速度。SDK 不使用实测速度替代驱动规划参数。

```python
from linkerbot_arm import H75

with H75("left", "can0") as arm:
    arm.set_velocities([0.1] * 7)
    arm.set_accelerations([0.15] * 7)
    arm.enable()  # 默认 PP
    try:
        arm.home()
    finally:
        arm.disable()
```

| 方法 | 参数 | 行为 |
| --- | --- | --- |
| `home(*, blocking=True)` | `blocking: bool` | 相当于 `move_j([0.0] * 7)` |
| `move_j(target_joints, *, blocking=True)` | 7 个关节 rad | 一次性提交七个关节目标，由 PP 驱动规划 |
| `move_p(target_pose, *, current_angles=None, blocking=True)` | `Pose`；可选 IK 初值为 7 个 rad | 求 IK 后提交点位目标，TCP 路径不保证直线 |

三种方法均要求 PP。`move_p()` 从 IK 开始保持忙状态；规划期间的急停或失能会取消该次目标，IK 返回后不会继续提交。CSP 下调用会抛出 `StateError`，不会偷偷切换模式或把单次目标当成平滑轨迹。
`blocking=False` 在目标提交后返回，可用 `is_moving()` 和 `wait_motion_done()` 查询或等待估算时长。
计时采用较小的加速/减速值估算梯形轨迹；实际驱动为 S 曲线，SDK 返回不是硬件实际到位确认。

目标长度不是 7 时抛出 `ValueError`；非有限值、编码溢出或超出模型角度限位时抛出 `ValidationError`。
规划速度/减速度未知、非零位移对应的参数不为正，或已有 SDK 运动进行中时抛出 `StateError`。

## CSP 流式控制

```python
from linkerbot_arm import H75, ControlMode

with H75("left", "can0") as arm:
    arm.disable()
    arm.set_control_mode(ControlMode.CSP)
    arm.enable()
    try:
        # 仅展示一次目标提交。连续运动需由调用方提供连续、受限的轨迹。
        arm._set_angles(arm.get_angles())
    finally:
        arm.disable()
```

`_set_angles(angles, *, check_limits=True)` 不插值、不计算速度或加速度限制。
CSP 中 `set_velocities()` / `set_accelerations()` 配置的是 PP 参数，不能保证流式目标限速。
调用方负责相邻目标变化和发送周期。重新使用 `home()` / `move_j()` / `move_p()` 前，
先 `disable()`、选择 PP，再 `enable()`。

七轴目标先完整编码再整组入队。入队或编码失败不改变目标缓存；队列接受不代表物理送达。
需要队列年龄限制时可用 `set_motion_queue_policy(max_target_age_s=...)`，
通过 `get_motion_health()` 读取零 I/O 队列诊断，详见 [CAN 接口](../can.md)。

## move_l 直线运动

`move_l()` 支持 PP 和 CSP，始终同步执行，无 `blocking` 参数。
先完成全部规划和关节目标校验，再临时提高各关节的 PP 速度与加减速度至配置允许的编码上限，
按至少 10 ms 的提交间隔发送路点，结束后分别恢复原速度、加速度和减速度。
在 CSP 中，这些 PP 参数不是流式目标的硬限速。

```python
angles = arm.get_angles()
start = arm.forward_kinematics(angles)
target = start.model_copy(update={"x": start.x + 0.01})
arm.move_l(target, current_angles=angles, current_pose=start)
```

| 参数 | 默认值 | 说明/范围 |
| --- | --- | --- |
| `target_pose` | 必填 | 当前世界坐标系中的 TCP `Pose`，m、rad |
| `max_velocity` | 0.05 | TCP 平移速度，(0, 0.4] m/s |
| `max_angular_velocity` | 0.3 | TCP 角速度，(0, 3.0] rad/s |
| `acceleration` | 0.1 | TCP 平移加速度，(0, 1.0] m/s² |
| `angular_acceleration` | 0.1 | TCP 角加速度，(0, 1.0] rad/s² |
| `current_angles` | `None` | 起始角度；省略时取缓存 |
| `current_pose` | `None` | 提供时须同时给出角度；与 FK 不一致时警告并使用 FK |

规划失败不改动驱动参数或提交部分目标。不可达目标可能抛出 `RuntimeError`，
输入错误使用 `ValueError` / `ValidationError`，未知参数或忙状态使用 `StateError`。

## 取消与失败

`disable()`、`emergency_stop()` 可取消后续提交；已进入 CAN FIFO 的指令无法撤销。
急停保持目标仍以七轴整组提交，但不使用普通目标的年龄淘汰规则；队列满或发送失败仍须处理，不能把软件急停视为硬件立即停机保证。
`home_cancellable(cancel_event)` 在事件置位后结束等待，但仍需调用方决定停止或失能。
流式规划、发送和恢复期间保持忙状态，延迟会拉长运行时间，不追赶补发。

参数恢复失败会报告异常；一项失败仍尝试其他项。若已有运动异常，保留原始异常并记录恢复错误。
编码、入队与通信异常会传播给调用方；失能和关闭失败也必须检查，不能视为机械状态已安全到位。
