# CAN 后端选择

A7、A7lite、P7、H75 默认使用 `CANTransport` 后端。构造函数及 `enable()`、`_set_angles()`、运动、状态和 `close()` 的调用方式不变；需要低层后端时可显式选择 dispatcher。

## 从当前源码安装

在 arm 仓库根目录的独立 Python 环境中执行：

```bash
python -m pip install --force-reinstall --no-deps -r requirements/transport.txt
python -m pip install -e '.[kinetix]'
python -m pip check
```

`requirements/transport.txt` 从 transport 的 `main` 分支安装当前实现，提供批次准入和协议路由能力；两个后端共用该依赖，不再固定版本号或旧提交。`requirements/cantransport.txt` 保留为同一清单的兼容入口。安装命令本身不连接硬件；新建 arm 对象仍按原行为打开通道、检查电机和读取初始状态。

ROS2 环境按 [ROS2 接入](ROS2.md) 使用系统兼容的运动学依赖，安装基础 arm，省略 `kinetix` extra。`linkerbot-arm-ros2-sdk` 的节点同样默认使用 `CANTransport`，沿用现有 PP 控制调用；这不增加 ROS2 的 MIT/CSP Topic 或 Service。

## 选择后端

| `LINKERBOT_ARM_TRANSPORT` | 新建 arm 使用的后端 |
| --- | --- |
| 未设置 | `CANTransport`（默认） |
| `cantransport` | `CANTransport`（显式选择） |
| `dispatcher` | 低层 dispatcher |

变量在每次构造时读取，已存在实例不会切换后端。其他值（包括空字符串）会在打开通道前报错；高层连接失败也不会自动回退到 dispatcher。
直接导入 `linkerbot_arm.comm.can.CANMessageDispatcher` 的既有入口仍使用低层实现，不受此变量影响。

## 控制与生命周期

- arm 每个实例独占自己的连接，双臂使用不同 CAN 通道。
- `send()` 仍是非阻塞 FIFO 入队，返回 `None`；保留 2000 个待发帧的容量和成功发送后约 0.3 ms 的最小调度间隔。此间隔是软件调度策略，不是实时性保证。
- 运动目标、寄存器读取、模式设置、使能/失能、标定和停止命令使用同一个 FIFO，不合并、不重排。`emergency_stop()` 保留各型号现有命令及停止语义，详见型号 API。
- A7、A7lite 和 P7 的使能/失能、模式、标定、保存及驱动配置写入等待物理发送回执；成功后才更新使能、速度和增益等缓存。单帧物理失败立即抛 `CANError`，无需等到连续错误阈值；等待上限为每帧 1 秒，超时抛 `TimeoutError`。未开始发送的超时帧会过期，已在发送中的帧无法撤回。回执表示 backend 接受发送，不表示电机执行完成；电机回复仍由现有 relay 等待。
- 运动目标、寄存器查询和后台轮询/心跳保持非阻塞入队。整臂 `disable()` 会尝试全部关节后报告首个失败；失败关节的缓存保留原值。多帧操作可能已有部分发送成功，异常不代表整体回滚，调用方须保留可能仍使能的状态并处理后续失能/恢复。
- A7 和 P7 V2 的单电机使能/失能串行完成发送和缓存更新，较早的调用不会覆盖后续生命周期状态；等待时不持有运动目标准入锁。P7 V2 使能失败、超时或中断后继续暂停心跳，即使该使能帧稍后发送成功也不重发旧位置；只有再次显式使能成功后才恢复心跳，并使用当前保持位置或使能等待期间新接纳的目标。暂停心跳不等于物理失能，应按应用流程处理可能仍使能的状态。
- A7 和 P7 使用标准帧精确路由，P7 同时保留 Flash 响应路由。A7lite 从扩展 ID 提取 motor ID，状态位和通信类型仍由原 motor 解码，原始消息不改写。
- 构造失败会回收已创建的高层连接和后台资源。总线故障、连续发送失败或接收队列溢出会停止该后端；溢出不会被当成正常反馈继续运行。
- `close()` 可重复调用，包括故障后再次关闭。后端关闭失败时保留资源引用以便重试；停止软件连接不等于电机急停或失能。

高层路径中的队列满仍抛 `queue.Full`，故障后发送抛 arm `CANError`，正常关闭后发送抛 `RuntimeError`。输入校验、生命周期及超时错误映射到 arm 的 `ValidationError`、`StateError`、`TimeoutError`。

## 统一周期调度

A7 的七关节查询共用一个周期线程；P7 的五个 V1 电机查询和两个 V2 电机心跳也共用
一个线程。A7lite 继续主动上报，不创建额外查询线程。`start_polling(intervals)` 与
`stop_polling()` 调用不变；查询在回包或超时后再等待配置的间隔，保留原有频率语义。
每个查询先登记响应等待者再发帧，快速回包不会丢失；单个关节超时不阻塞其他任务。

## 整组目标与可选时延背压

A7、A7lite、P7、H75 的 `_set_angles()` 及 A7lite 的 `set_mits()`、`set_csp_angles()`、
`stream_joint_targets()` 均先完成全部编码，再将整组目标一次性加入 FIFO。七帧空间
不足时整组抛 `queue.Full`，控制目标缓存也不更新。组内帧不会被其他排队命令插入；
物理发送仍逐帧进行，故障可能产生已发送的前缀，并不保证七个电机同时执行。

默认只按容量准入，不过期、不合并、不自动丢弃旧目标。应用可为新提交的整组目标设置
时间预算（秒）：

```python
arm.set_motion_queue_policy(max_target_age_s=0.02)
arm._set_angles([0.0] * 7)  # 原调用与 None 返回值保持不变
health = arm.get_motion_health()  # 只读本地状态，不发查询帧
print(health.queue.oldest_pending_age_s, health.queue.pending_fifo)
print(health.queue.rejected_stale, health.queue.expired, health.last_error)
arm.set_motion_queue_policy(max_target_age_s=None)  # 后续提交恢复容量策略
```

- 队列或正在发送的工作已达到预算时，新的整组目标抛 arm `TimeoutError`；调用方应处理
  该异常和 `queue.Full`，暂停目标生产或降低提交速率，避免持续积累时延。
- 已接纳、尚未开始发送的目标组若超过预算，整组失败且零帧发送。开始后不会因截止时间
  只发一半；物理故障或关闭仍可能中止剩余帧。因此预算约束的是开始发送前的年龄，
  不承诺整个组的完成时刻。修改策略不会追溯修改已经入队的截止时间。
- `last_outcome`、`last_sent_frames`、`last_frame_count`、`last_error` 描述最后一次已接纳的
  目标提交。返回 `None` 只表示成功入队；通过健康状态观察异步发送失败。
  `queue.failed`、`queue.expired` 为累计计数，可发现后续提交覆盖之前的失败。
- `pending_fifo` 按帧计数；`in_flight_frames` 是当前正在处理的一组的总帧数。
  `accepted/dispatched/failed/expired` 按提交计数，一组七帧只记一次。
- 使能、失能、模式、标定、查询和单电机停止/保持命令继续使用普通 FIFO，不受目标年龄
  策略丢弃。P7 心跳仅重发已成功发送的目标，跳过仍在等待或已失败的目标；过期后需
  提交新的有效目标才恢复对应心跳，SDK 不自动重新使能或重放过期动作。

以上保证适用于内置的两个 arm 后端。自行替换底层 dispatcher 的集成需自行提供批次准入能力；配置与生命周期保留其原 `send(message)` 合约，SDK 无法确认自定义异步队列的物理结果。

## 故障恢复与回退

当前不自动调用 transport 的 `recover()`。仅重新打开 CAN 无法恢复电机使能、控制模式及缓存状态；出现故障后，应停止应用的目标发送，关闭旧 arm，再构造新 arm 并按应用流程检查状态、配置模式和使能。未发送的旧队列不会重放。

回退时先关闭当前 arm，再在启动应用的环境显式选择 dispatcher 并创建新实例：

```bash
export LINKERBOT_ARM_TRANSPORT=dispatcher
```

恢复默认高层后端时，先关闭当前 arm，再取消变量并重新启动应用：

```bash
unset LINKERBOT_ARM_TRANSPORT
# 也可以显式设置：export LINKERBOT_ARM_TRANSPORT=cantransport
```

## 验证边界

后端选择、协议收发与资源生命周期由本地和 virtual/vcan 回归覆盖；设备端延迟、反馈、停止及动作效果仍需在相应设备上验证，软件回归不能代替实机结果。当前支持范围不包含臂手共用通道、CAN/CAN FD 混接或自动恢复运动。

## 初始化失败与关闭

默认 CANTransport 和显式 dispatcher 都会在 arm 初始化失败时停止轮询并释放连接。
正常 `close()` 仍返回 `None`，重复关闭已释放的对象不会再次操作总线；总线故障后也应调用
`close()` 完成资源释放。`close()` 本身不等同于电机失能，按应用需要先调用 `disable()`。

A7/A7lite/P7 关闭开始后拒绝新运动和受保护的外部目标，但保持 CAN 和轮询可用，
先等待已有运动 worker 完成规划、发送和参数恢复，再停止轮询并关闭后端。
取消事件置位不代表 worker 已退出；不能在该 worker 内调用 `close()`，否则抛 `StateError`。
关闭不会强行中断 IK 求解或外部阻塞回调，应用要求立即停止时应先调用停止或失能操作。
等待期间的中断会取消运动；即使再次收到 `KeyboardInterrupt` 或 `SystemExit`，
A7/A7lite/P7/H75 也会先等 worker 清理结束，再关闭通信并传播最初的异常。

**异常行为修正：** 物理关闭失败不再被静默吞掉，会报告 `CANError`（线程退出异常等保留其
对应异常）；资源保留供再次 `close()`。不要将控制停止与资源释放完成视为同一状态。
`with arm:` 的业务代码与清理同时失败时，保留业务异常并记录清理错误，之后仍可显式重试关闭。
构造回滚的清理失败也会记录；强制结束进程不能由 Python 清理逻辑保证释放。

## 读取预算与回复校验

同命令读取共享唯一 relay，并串行取得请求所有权。`timeout_s` 从调用入口按单调时间计时，
覆盖锁等待及剩余回包等待；零超时仍可接纳同步发送回调中的回复，锁不可用时立即失败。
发送回调须迅速返回，预算不能打断自定义阻塞发送。协议没有请求序号，迟到的同命令回复仍无法区分。
A7 回复必须为对应 ID 的标准数据帧，DLC 与长度一致；短回复、回显、错误/远程/FD 帧和非有限浮点值不会完成有效读取。

## H75 接入

H75 使用标准 CAN ID 路由，IQ24 协议由独立 H75Motor 编解码；不使用 A7 的浮点编码。
七关节共用轮询线程和整组目标队列，沿用有界发现、回复匹配、关闭重试和运动取消。
抱闸、CSP 和电流单位等型号差异见 [H75 reference](zh/src/reference/h75/README.md)。
