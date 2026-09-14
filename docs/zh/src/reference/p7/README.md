# P7 机械臂

P7 使用 A7 的前五个 V1 电机及两个 MotorV2。类与 motor 的导入保持不变：

```python
from linkerbot import P7
from linkerbot.arm.p7 import MotorV2, SensorType
```

构造函数与 A7 一致：`P7(side, interface_name, interface_type='socketcan',
tcp_offset=[0.0, 0.0, 0.0], world_frame='urdf')`。左右臂 URDF 均随安装包提供。

可使用 `enable`、`disable`、`reset_error`、`home`、`move_j`、`move_p`、`move_l`、
`get_angles`、`get_velocities`、`get_torques`、`get_pose`、`get_state`、参数配置和 `close`。
方法与参数以 `src/linkerbot/arm/p7/p7.py` 为准，完整签名纳入兼容性基线。

P7 的混合 motor 控制包含主机侧路点插值，不能假定其运动实现和 A7 相同。
ROS2 适配器已注册 `p7`，流式控制继续通过 `_set_angles`；独立标定与生命周期脚本目前只开放 A7/A7lite。
P7 此次完成无硬件 API 和运动学验证，真机控制验收需要单独执行。
