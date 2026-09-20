# P7 机械臂

P7 是七关节机械臂，前五个关节使用 A7Motor，后两个关节使用 MotorV2。

## 快速开始

```python
from linkerbot_arm import P7

with P7(side="left", interface_name="can0") as arm:
    print(arm.get_angles())
    print(arm.get_pose())
```

构造函数与 A7 一致：`P7(side, interface_name, interface_type='socketcan',
tcp_offset=[0.0, 0.0, 0.0], world_frame='urdf')`。
左右臂 URDF 均随安装包提供，构造时需要 Pinocchio 并检查电机状态。

安装方法见[安装指南](../../../../INSTALLATION.md)，链路配置见 [CAN 接口](../can.md)。

## 控制与状态

可使用 `enable()`、`disable()`、`reset_error()`、`home()`、`move_j()`、`move_p()`、`move_l()`、
`get_angles()`、`get_velocities()`、`get_torques()`、`get_pose()`、`get_state()`、参数配置和 `close()`。
运动方法与 A7 的调用参数对应。`move_j()` 使用主机侧路点插值控制两种电机，
`blocking=False` 仍会在调用内发送整段轨迹，仅省略最后的短暂等待；它不是后台轨迹任务。
`move_p()` 保留一次目标提交与估算等待的行为。

运动完成仍按 SDK 的时长估算或主机轨迹提交进度判断，**不是电机实际到位确认**。
A7（含 P7 前五关节）初始化时从 `0x1C` 读取轨迹速度，`get_velocities()` 仍返回实测速度。
`move_j()` / `move_p()` 对非零位移要求有效的正速度与加速度；参数为零、缺失或非有限值时，
在提交目标前抛出 `StateError`。可先调用 `set_velocities()` 和 `set_accelerations()` 设置参数。
未发生位移的关节不要求正速度。

`move_l()` 会先完成整段规划并校验全部关节目标，再临时调整参数和发送路点。
规划失败不修改电机参数或提交部分轨迹；执行期间每次提交完成后至少等待 10 ms 再提交下一点。
发送变慢或调度晚醒会延长执行时间，路点保持顺序，不追赶补发、不自动丢点。
规划、发送和参数恢复期间 `is_moving()` 保持 True；停止可取消后续目标，规划器返回前仍保留忙状态。
已进入 CAN FIFO 的帧不会撤销，通信排队和机械跟踪误差仍需结合反馈判断。

失败或取消会尝试恢复原速度和加速度；一类参数恢复失败仍尝试另一类，失败写入日志并向调用方报告。
若运动操作本身也失败，保留原始异常，恢复错误记录在日志中。恢复调用成功表示 SDK 接受参数，
不保证所有电机已经执行；无法恢复时应检查通信及参数后再运动。

底层 motor 导入：

```python
from linkerbot_arm.arm.p7 import MotorV2, SensorType
```

MotorV2 的伺服命令与 A7Motor 的协议不同，并使用后台心跳维持驱动状态。
自行集成流式关节控制时，可调用 P7 的 `_set_angles(angles)` 转发七个目标角度。
方法签名见 [P7 源码](../../../../../src/linkerbot_arm/arm/p7/p7.py)。
