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
运动方法与 A7 的调用参数对应，但 P7 使用主机侧路点插值控制两种电机。

底层 motor 导入：

```python
from linkerbot_arm.arm.p7 import MotorV2, SensorType
```

MotorV2 的伺服命令与 A7Motor 的协议不同，并使用后台心跳维持驱动状态。
自行集成流式关节控制时，可调用 P7 的 `_set_angles(angles)` 转发七个目标角度。
方法签名见 [P7 源码](../../../../../src/linkerbot_arm/arm/p7/p7.py)。
