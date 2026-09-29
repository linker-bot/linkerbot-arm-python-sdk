# 参数配置

以下范围是 SDK 接口校验或协议编码范围，不是各关节在所有负载下的推荐运行范围。
示例参数用于展示调用方式，实际运行时应根据安装姿态和负载设置。
所有整臂参数列表按关节索引 `0–6` 排列，必须包含 7 个值。

## 速度与加速度

```python
from linkerbot_arm import P7

with P7(side="left", interface_name="can0") as arm:
    arm.set_velocities([0.3] * 7)
    arm.set_accelerations([5.0] * 7)
    print(arm.get_control_velocities())
    print(arm.get_control_acceleration())
```

| 方法 | 参数与单位 | 范围 | V1（索引 0–4） | V2（索引 5–6） |
| --- | --- | --- | --- | --- |
| `set_velocities(velocities)` | 7 个速度值，rad/s | [0.0, 50.0] | 设置驱动轨迹速度 | 仅缓存，用于主机运动时长估算；不作为 PTM 的速度前馈 |
| `set_accelerations(accelerations)` | 7 个加速度值，rad/s² | [1.0, 50.0] | 同时设置驱动加速度和减速度 | 仅缓存，用于主机运动时长估算；驱动无加减速度规划器 |

V1 构造时从电机读取轨迹参数，不保证固定出厂值；V2 构造时的速度缓存为 `0.0`，
加速度缓存为 `10.0`。因此，在调用 `home()`、`move_j()` 或 `move_p()` 前应显式设置运动参数。
非零位移要求对应关节的速度和加速度为有限正数，否则在发送目标前抛出 `StateError`。
零位移关节不要求正速度。

`move_j()` / `move_l()` 在下发路点期间临时使用最大速度、加速度设置，
结束、失败或取消时尝试恢复原值。V2 实际运动由主机下发的位置路点和 PTM 位置环控制。
`move_j()` 按估算时长对关节角度做线性插值，并非驱动端梯形加减速轨迹。

**异常：** `ValueError`（列表长度不是 7），`ValidationError`（数值超出范围）。

## 增益设置

两类电机的控制环不同，同一列表中应分别配置。

```python
# 假设 arm 已连接。这里展示列表顺序，不作为通用调参推荐值。
arm.set_position_kps([80.0] * 5 + [4.0, 4.0])
arm.set_velocity_kps([0.4] * 5 + [0.0, 0.0])
arm.set_velocity_kis([0.008] * 5 + [0.0, 0.0])
```

| 方法 | V1（索引 0–4） | V2（索引 5–6） |
| --- | --- | --- |
| `set_position_kps(kps)` | 写入位置环 Kp 寄存器 | 缓存位置 Kp，在后续 PTM 目标帧或心跳中发送 |
| `set_velocity_kps(kps)` | 写入速度环 Kp 寄存器 | 无操作；PTM 帧不包含速度环 Kp |
| `set_velocity_kis(kis)` | 写入速度环 Ki 寄存器 | 无操作；PTM 帧不包含速度环 Ki |

这三个方法在列表长度不是 7 时抛出 `ValueError`。
V2 的 `velocity_kp`、`velocity_ki` 属性均返回 `0.0`，不表示设置已生效。

### V2 PTM 参数

| 参数 | SDK 初始值 | 协议编码范围 | 说明 |
| --- | --- | --- | --- |
| 位置 Kp | 4.0 | [0, 250] | 可通过 `set_position_kps()` 修改 |
| 位置 Kd | 15.0 | [0, 50] | 当前无公开设置方法 |
| 速度前馈 | 0.0 rad/s | [-10, 10] rad/s | 与 `set_velocities()` 独立，默认关闭 |
| 力矩前馈 | 0.0 Nm | [-50, 50] Nm | 底层 `MotorV2.set_torque_ref(torque)` 缓存；整臂无对应设置方法 |
| 目标角度 | 当前角度 | [-12.5, 12.5] rad | 整臂运动仍受 URDF 关节限位约束 |

PTM 目标角度编码为 16 位，其余参数为 12 位。编码时按协议范围截断和量化，
不能把编码范围用作机械限位或把缓存值视为电机执行确认。
底层 `MotorV2` 在 `linkerbot_arm.arm.p7` 中导出；驱动模式初始化方法为
`ensure_ptm_mode(timeout_s=0.2)`，正常使用 `P7` 时由构造流程调用。

### move_l 参数速查

| 参数 | 默认值 | 范围 |
| --- | --- | --- |
| `max_velocity` | 0.05 m/s | (0, 0.4] m/s |
| `max_angular_velocity` | 0.3 rad/s | (0, 3.0] rad/s |
| `acceleration` | 0.1 m/s² | (0, 1.0] m/s² |
| `angular_acceleration` | 0.1 rad/s² | (0, 1.0] rad/s² |

完整语义见[运动控制](motion.md)。

## 参数持久化

`save_params()` 向所有电机发送保存命令。V1 保存已写入驱动的参数；
V2 保存电机内部 Flash 参数，但 SDK 的位置 Kp、力矩前馈、速度和加速度缓存没有先写入 Flash，
因此这些主机缓存值不会随此调用持久化，重新创建对象后需要重新设置。

V2 的控制模式由构造流程在必要时写入并保存；`calibrate_zero()` 也会向 V2 发送保存命令。
每个 V2 保存调用固定等待 1 秒，两关节合计至少等待约 2 秒；避免在实时控制循环中调用。
`save_params()` 本身不读回验证所有参数，不能据其返回推断全部参数均已保存成功。
