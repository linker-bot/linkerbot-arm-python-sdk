# 运动学与关节定义

H75 复用 `ArmKinetix`，内置左右臂模型。默认 TCP 位于 `L8_Link` / `R8_Link` 原点，
`tcp_offset` 沿末端 link 的局部 XYZ 轴平移，单位 m。模型根是各自的 `L_arm_root` / `R_arm_root`，
原点与第 1 关节原点重合；整机安装变换需要另外提供。

`world_frame="urdf"` 使用根坐标系；`"maestro"` 使用现有 SDK 的第二关节原点及 Z 轴旋转约定。
同一目标位姿必须与所选坐标系、左右臂和工具偏移一致。

## 离线 FK/IK

```python
from linkerbot_arm.arm.kinetix import ArmKinetix

kx = ArmKinetix.from_builtin("h75", "left", world_frame="urdf")
limits = kx.get_joint_limits()
seed = [(lo + hi) / 2 for lo, hi in limits]
pose = kx.forward_kinematics(seed)
angles = kx.inverse_kinematics(pose, current_angles=seed)
```

这段示例不打开 CAN。已连接的 `H75` 提供相同的 `forward_kinematics(angles)`、
`inverse_kinematics(pose, *, current_angles=None)`；省略初值时使用角度缓存。
位姿为 `Pose(x, y, z, rx, ry, rz)`，位置单位 m，姿态为外旋 ZYX 欧拉角，单位 rad。
IK 失败抛出 `RuntimeError`。

## 关节顺序和角度限位

下表轴向来自 URDF 的关节坐标系，正方向遵循右手定则；Python 索引从 0 开始。
零角度与实物零点是否一致取决于标定，SDK 不自动验证机械姿态。

### 左臂

| 索引 | 关节 | 旋转轴 | 范围（rad） |
| --- | --- | --- | --- |
| 0 | L1_Joint | `0 -1 0` | [-2.79, 2.79] |
| 1 | L2_Joint | `1 0 0` | [-3.14, 0] |
| 2 | L3_Joint | `0 0 1` | [-2.79, 2.79] |
| 3 | L4_Joint | `0 1 0` | [-2.27, 0.52] |
| 4 | L5_Joint | `0 0 -1` | [-2.79, 2.79] |
| 5 | L6_Joint | `0 1 0` | [-1.22, 1.22] |
| 6 | L7_Joint | `1 0 0` | [-1.22, 1.22] |

### 右臂

| 索引 | 关节 | 旋转轴 | 范围（rad） |
| --- | --- | --- | --- |
| 0 | R1_Joint | `0 -1 0` | [-2.79, 2.79] |
| 1 | R2_Joint | `1 0 0` | [0, 3.14] |
| 2 | R3_Joint | `0 0 1` | [-2.79, 2.79] |
| 3 | R4_Joint | `0 1 0` | [-2.27, 0.52] |
| 4 | R5_Joint | `0 0 -1` | [-2.79, 2.79] |
| 5 | R6_Joint | `0 1 0` | [-1.22, 1.22] |
| 6 | R7_Joint | `1 0 0` | [-1.22, 1.22] |

`get_joint_limits()` 返回当前模型角度范围。`set_joint_limits(limits)` 只调整当前模型，
不写入驱动或 EEPROM，也不提供碰撞检测。
URDF 中 `effort`、`velocity` 为上游未填写额定数据的零值；不能把这些占位值当作机械额定能力。
驱动参数编码范围见[配置](config.md)，实际运行范围应依据硬件资料和验证结果确定。
