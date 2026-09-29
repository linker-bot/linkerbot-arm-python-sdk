# 运动学

## 正运动学

根据关节角度计算 TCP 位姿。

```python
pose = arm.forward_kinematics([0.0, 0.0, 0.0, 1.57, 0.0, 0.0, 0.0])
print(f"TCP: ({pose.x:.3f}, {pose.y:.3f}, {pose.z:.3f})")
```

**参数：**

- `angles`: 7 个关节角度（rad），类型 `list[float]`

**返回值：**

- `Pose`: TCP 位姿

## 逆运动学

根据 TCP 位姿求解关节角度。

```python
from linkerbot_arm import Pose

seed = [0.0, 0.0, 0.0, 0.3, 0.0, 0.0, 0.0]
target: Pose = arm.forward_kinematics(seed)
angles = arm.inverse_kinematics(target, current_angles=seed)
print(f"关节角度：{angles}")
```

**参数：**

- `pose`: 目标 TCP 位姿，类型 `Pose`
- `current_angles`: IK 初始猜测关节角度，类型 `list[float] | None`，`None` 时使用关节角度缓存

**返回值：**

- `list[float]`: 7 个关节角度（rad）

## 关节限位

```python
# 获取当前关节限位
limits = arm.get_joint_limits()
print(limits)  # [(lower0, upper0), (lower1, upper1), ...]

# 设置自定义关节限位
arm.set_joint_limits([(-1.0, 1.0)] * 7)
```

关节顺序、默认限位和 TCP 定义见[P7 概览](README.md)。`set_joint_limits()` 只修改当前运动学模型，
不写入驱动或 Flash，也不执行碰撞检测。FK/IK 使用构造时选择的 `world_frame` 和 `tcp_offset`；
不同安装基座、工具或坐标系下的位姿不可直接混用。IK 失败时抛出 `RuntimeError`。

需要离线计算时，可直接加载模型，无需创建 P7 通信连接或改变电机控制模式：

```python
from linkerbot_arm.arm.kinetix import ArmKinetix

kx = ArmKinetix.from_builtin("p7", "left", world_frame="urdf")
pose = kx.forward_kinematics([0.0] * 7)
```
