# 从旧 SDK 迁移

`linkerbot-arm` 0.6.x 使用 `linkerbot_arm` 命名空间。该发行包不提供旧 `linkerbot.*`
导入路径，升级应用时需要更新导入。

## 导入映射

| 旧导入 | 当前导入 |
| --- | --- |
| `from linkerbot import A7, A7lite, P7, Pose, ControlMode` | `from linkerbot_arm import A7, A7lite, P7, Pose, ControlMode` |
| `from linkerbot.arm import State, WayPoint` | `from linkerbot_arm.arm import State, WayPoint` |
| `from linkerbot.arm.a7.motor import A7Motor, SensorType` | `from linkerbot_arm.arm.a7.motor import A7Motor, SensorType` |
| `from linkerbot.arm.p7.motor_v2 import MotorV2` | `from linkerbot_arm.arm.p7.motor_v2 import MotorV2` |
| `from linkerbot.arm.kinetix import ArmKinetix` | `from linkerbot_arm.arm.kinetix import ArmKinetix` |
| `from linkerbot.comm import CANMessageDispatcher` | `from linkerbot_arm.comm import CANMessageDispatcher` |
| `from linkerbot.exceptions import StateError` | `from linkerbot_arm.exceptions import StateError` |

arm 构造参数和已有方法调用保持兼容，包括 `_set_angles()` 和 `_motors`。
底层 dispatcher 的 `send()` 仍返回 `None`，队列满仍抛出 `queue.Full`，
总线故障后的发送仍抛出 arm 的 `CANError`。

## 安装

按照[安装指南](INSTALLATION.md)在独立环境安装 SDK 和当前 transport 源码。
确认应用加载当前命名空间：

```bash
python -c "import linkerbot_arm; from linkerbot_arm import A7, A7lite, P7; print(linkerbot_arm.__file__)"
```

仅安装新发行包不会重定向应用已有的 `import linkerbot`。
需要灵巧手的应用仍须保留自己的 hand SDK 依赖；arm 包不包含手部驱动。

CAN FD 兼容层的关闭由 transport 管理。厂商驱动关闭失败仍抛出 arm 的 `CANError`，
SocketCAN 关闭失败记录警告；资源保留到实际释放成功，可再次调用 `close()` 重试。
关闭开始后拒绝继续收发，SocketCAN 关闭不会将共享 CAN 接口设为 down。

## ROS2 应用

检查所用 ROS2 版本的适配器导入。仍使用 `from linkerbot import ...` 的适配器需要旧 SDK，
不能只替换安装包就切换到 `linkerbot_arm`。支持新命名空间的接入方式和环境要求见 [ROS2 接入](ROS2.md)。

## 运动与停止行为

调用签名保留，但以下行为已调整，集成需同步调用方式：

- A7/A7lite/P7 的 `move_p()` 在 IK 求解期间保持 busy。停止或失能后，即使求解返回也不提交该次目标；
  不会强行中断求解器，关闭会等待它退出及参数恢复结束。
- A7lite `emergency_stop()` 不再等待约两秒后自动恢复速度，而是持续锁存。
  PP/CSP 保持零速并替换旧位置目标，MIT 当前位置保持使用至少 `kp=20`、`kd=1`。
  外部目标与普通运动被拒绝；显式 `enable()` 或成功 PP `home()` 才恢复，失败或取消继续停止。
  停止期间设置速度会保存待恢复配置，参数清理不会解除停止。单轴保持失败时尽力失能该轴，继续处理其他轴并报告错误。
- P7 `move_p()` 与 `move_j()` 都发送同步的关节梯形/三角形轨迹；`blocking=False` 仍完成整段路点发送，
  只省略末次等待。需要应用线程隔离时由调用方安排，不应据此将它当作后台启动接口。
  路点在真实提交间隔下仍须满足原速度、加速度配置；调度停顿时可延长等待，不裁剪或跳过路点。
- P7 外部 `_set_angles()` 按配置的速度/加速度自动限幅。首周期发送反馈保持目标，后续周期逐步趋向目标；
  单条指令不会自动执行到终点。限幅使用两次接纳之间的实际时间间隔；设置 profile 或停止后重新播种。
  SDK 自有轨迹不再叠加这一限幅；`move_l()` 的笛卡尔参数不保证奇异点附近的关节速度上限。
- A7/A7lite/P7 `close()` 在运动 worker 和参数恢复结束后才停止轮询、关闭 CAN。
  关闭期间拒绝新运动，不允许 worker 内关闭；必要时先停止或失能，`close()` 不自动失能。
  取消后的清理等待可延后连续中断，完成后再传播最初的异常；H75 复用同一保护。
- 限位设置完整验证后一次替换，getter 返回副本；修改返回列表不再修改内部限位。
  `ArmKinetix.plan_move_l()` 对间隔、速度、加速度及位姿提前拒绝非有限/非法值，保留合法零位移。
- A7（含 P7 前五轴）读取拒绝回显、短回复、错误/FD/远程/扩展帧及非有限值。
  读取 timeout 覆盖等待同命令请求锁和回包的总预算；自定义发送回调仍须及时返回。

主机轨迹和保持帧不证明电机实际到位或负载下停止效果，相关运动变化仍需对应型号实机验收。

## 回滚

### P7 的 PTM 控制

P7 第 6、7 关节已同步完整 SDK 的 PTM 控制修复。整臂方法签名保持不变，
但构造会检查控制模式，必要时将电机 Flash Control Mode 从旧模式改为 `0x02`、保存并读回验证。
V2 位置增益初始值改为 Kp=4、Kd=15，速度前馈默认为零；
`set_velocity_kps()` / `set_velocity_kis()` 对这两个关节无操作，
`set_velocities()` 只更新其主机规划速度缓存。旧 Servo 参数不能直接作为 PTM 调参依据。

使用底层 `MotorV2` 时，应在发送 PTM 目标或启动心跳前调用 `ensure_ptm_mode()`，
并停止其他控制发送；正常使用 `P7` 时构造流程已完成此步骤。
内部编码 helper `_build_servo_frame()` 已替换为 `_build_ptm_frame()`，
集成应使用 `set_angle()` 或整臂 `_set_angles()` 提交目标。

仅回退 Python 包不会恢复电机 Flash 控制模式。回退到 Servo 驱动前，需要按电机配置流程
恢复与旧驱动匹配的模式；不要向 PTM 模式的电机发送旧 Servo 帧。
完整参数和持久化限制见 [P7 参数配置](zh/src/reference/p7/config.md)。

### 应用环境

保留原应用环境及对应 SDK 版本。回滚时恢复应用导入代码和原环境的依赖组合，
避免仅回退包版本却保留新命名空间导入。
