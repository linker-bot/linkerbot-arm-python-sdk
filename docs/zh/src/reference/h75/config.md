# 参数配置

所有整臂参数列表按 J1–J7 排列，长度必须为 7。先完整校验，再逐关节发送配置；
中途通信失败仍可能留下部分已生效配置，应检查错误后重新设置。
整臂配置的校验、入队和缓存更新与运动准入保持串行；SDK 运动期间，外部调参会抛出 `StateError`，应先停止运动。
轨迹内部设置临时参数和恢复原值仍可执行，避免其他线程的新配置被轨迹结束时覆盖。

## 电机换算配置

```python
from linkerbot_arm import H75
from linkerbot_arm.arm.h75 import H75MotorConfig

configs = [H75MotorConfig(gear_ratio=100.0) for _ in range(7)]
with H75("left", "can0", motor_configs=configs) as arm:
    print(arm.get_currents())
```

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| `gear_ratio` | 100.0 | 电机轴转数 / 关节转数 |
| `rpm_full_scale` | 6000.0 | 速度与加速度归一化所用电机轴 RPM 满量程 |
| `current_full_scale_a` | 33.0 | 电流反馈满量程，A |
| `profile_velocity_scale` | π | PP 速度指令的固件补偿，不作用于实测速度和加速度 |

默认组合沿用来源分支。满量程在上游仍标为手册示例值，需要与实际电机型号核对；
π 补偿对应上游测试过的固件，厂家修正后可能需要设为 `1.0`。
配置必须为有限正数，在打开 CAN 前校验。

位置编码使用电机轴转数：`N = θ × gear_ratio / (2π)`，SDK 返回关节 rad。
速度指令编码为 `ω × profile_velocity_scale × gear_ratio × 60 / (2π × rpm_full_scale)`；
加减速度编码使用电机轴 RPM/s，不应用速度补偿系数。

## 速度与独立减速度

```python
arm.set_velocities([0.1] * 7)
arm.set_accelerations([0.15] * 7)  # 同时设置加速度和减速度
arm.set_decelerations([0.2] * 7)  # 只改减速度
```

| 方法 | 单位 | 默认配置下的接口范围 |
| --- | --- | --- |
| `set_velocities()` | rad/s | [0, 2] |
| `set_accelerations()` | rad/s² | [0.0001, 2π] |
| `set_decelerations()` | rad/s² | [0.0001, 2π] |

上限按每个电机的配置推导，是归一化编码能力，**不是机械安全运行额定值**。
超范围值会被拒绝，不会静默截断后仍按原值计时。成功接受后缓存 IQ24 量化的有效值，
所以读回控制参数可能与传入浮点数略有差异。

构造不猜测未知的规划速度和减速度，运动前必须显式设置。
`set_accelerations()` 同时更新两个方向的规划参数；需要不同减速度时随后调用 `set_decelerations()`。
`move_l()` 结束或取消后分别恢复它们。CSP 流式输入的速度由调用方轨迹决定，不能依赖 PP 参数限速。

## 增益

`set_position_kps()`、`set_velocity_kps()`、`set_velocity_kis()` 分别设置位置 Kp、速度 Kp、速度 Ki。
全部值必须有限且非负，编码最大值为 `127.99999994039536`。这只是 IQ24 表示范围，不是调参推荐范围。
只有指令被 SDK 接受后才更新控制缓存。

## 参数保存与标零

`save_params()` 发送保存命令，每关节等待 1 ms；不自动读回或断电验证。
`calibrate_zero()` 会逐关节发送 `0x87` 和 `0x0D`，改变零点并保存 EEPROM，要求电机失能且无 SDK 运动。
`home()` 只运动到零角度，不改变零点。

从源码仓库运行工具：

```bash
# 默认只读状态，电流输出为 A
python tools/h75_smoke.py --side left --interface can0

# 显式请求第 4 关节增加 0.05 rad；运行前确认姿态和空间
python tools/h75_smoke.py --side left --interface can0 --stage jog --joint 4 --delta 0.05

# 明确要求回零
python tools/h75_smoke.py --side left --interface can0 --stage home

# 将已摆好的机械零位写入 EEPROM；须停止其他控制程序并做好支撑
python tools/h75_calibrate_zero.py --side left --interface can0 --yes
```

小幅运动工具结束或异常时尝试失能，再关闭连接。标零工具先停止轮询、失能并查询使能状态，
再标零保存；保存后重新发送位置查询，避免把旧缓存当成标零结果。
查询接近零仍不等于确认 EEPROM 持久化，需要断电重启后复核。工具不随 wheel 提供，需使用源码仓库。
