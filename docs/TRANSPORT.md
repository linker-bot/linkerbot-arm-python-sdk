# CAN 后端选择

A7、A7lite、P7 默认继续使用 dispatcher 后端。可选的 `CANTransport` 后端用于本地和设备验收，构造函数及 `enable()`、`_set_angles()`、运动、状态和 `close()` 的调用方式不变。

## 从固定源码启用

在 arm 仓库根目录的独立 Python 环境中执行：

```bash
python -m pip install --force-reinstall --no-deps -r requirements/cantransport.txt
python -m pip install -e '.[kinetix]'
python -m pip check
export LINKERBOT_ARM_TRANSPORT=cantransport
```

`requirements/cantransport.txt` 固定提供协议路由能力的 transport 源码提交；当前发行版本号不能区分这项源码能力，需按该清单安装。安装命令本身不连接硬件；设置变量后，新建 arm 对象仍按原行为打开通道、检查电机和读取初始状态。

ROS2 环境按 [ROS2 接入](ROS2.md) 使用系统兼容的运动学依赖，安装基础 arm，省略 `kinetix` extra。启动个人 fork 的 ROS2 节点前设置相同环境变量，即可沿用现有 PP 控制调用；这不增加 ROS2 的 MIT/CSP Topic 或 Service。

## 控制与生命周期

- arm 每个实例独占自己的连接，双臂使用不同 CAN 通道。
- `send()` 仍是非阻塞 FIFO 入队，返回 `None`；保留 2000 个待发帧的容量和成功发送后约 0.3 ms 的最小调度间隔。此间隔是软件调度策略，不是实时性保证。
- 运动目标、寄存器读取、模式设置、使能/失能、标定和停止命令使用同一个 FIFO，不合并、不重排。`emergency_stop()` 保留各型号现有命令及停止语义，详见型号 API。
- 物理发送回执由内部 worker 消费，不让 motor 调用等待回执；电机回复仍由现有 relay 等待。回执表示 backend 接受发送，不表示电机执行完成。
- A7 和 P7 使用标准帧精确路由，P7 同时保留 Flash 响应路由。A7lite 从扩展 ID 提取 motor ID，状态位和通信类型仍由原 motor 解码，原始消息不改写。
- 构造失败会回收已创建的高层连接和后台资源。总线故障、连续发送失败或接收队列溢出会停止该后端；溢出不会被当成正常反馈继续运行。
- `close()` 可重复调用，包括故障后再次关闭。后端关闭失败时保留资源引用以便重试；停止软件连接不等于电机急停或失能。

高层路径中的队列满仍抛 `queue.Full`，故障后发送抛 arm `CANError`，正常关闭后发送抛 `RuntimeError`。输入校验、生命周期及超时错误映射到 arm 的 `ValidationError`、`StateError`、`TimeoutError`。

## 故障恢复与回退

当前不自动调用 transport 的 `recover()`。仅重新打开 CAN 无法恢复电机使能、控制模式及缓存状态；出现故障后，应停止应用的目标发送，关闭旧 arm，再构造新 arm 并按应用流程检查状态、配置模式和使能。未发送的旧队列不会重放。

回退时先关闭当前 arm，再取消变量并创建新实例：

```bash
unset LINKERBOT_ARM_TRANSPORT
# 或明确选择默认后端：
export LINKERBOT_ARM_TRANSPORT=dispatcher
```

变量在每次构造时读取，已存在实例不会切换后端。其他值会在打开通道前报错。

## 验证边界

高层后端仍为显式选择项。默认切换需完成相应设备上的延迟、反馈、停止及低速动作验收；virtual/vcan 测试不能代替这些结果。当前支持范围不包含臂手共用通道、CAN/CAN FD 混接或自动恢复运动。
