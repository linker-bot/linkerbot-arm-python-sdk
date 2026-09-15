# 阶段 3：低层 dispatcher 接入记录

日期：2026-09-15。分支：`refactor/phase-3-transport-1`，基于阶段 2 合并后的
`master` / `51c1ec21c16a77761e5ee2ed9ec004f52a626fe4`。
关联 arm #1、transport #46；本阶段只修改 arm 仓库。

## 实际模块边界

```text
A7 / A7lite / P7 / motor
  → linkerbot_arm.comm.can.CANMessageDispatcher（兼容层）
    → linkerbot_transport.can.can.CANMessageDispatcher（队列、线程、CAN I/O）
```

transport 1.0.0 的 dispatcher 位于 `linkerbot_transport.can.can`，没有从
`linkerbot_transport.can` 导出。原计划的直接替换会改变 `send()` 返回值和异常，
因此保留 arm 原导入路径，通过继承委托工作线程、队列、收发和关闭流程。
arm 只适配构造校验异常、发送结果与异常，以及 backend shutdown 失败的处理策略。
兼容层依赖 transport 的 `_shutdown_bus` 扩展点，升级 1.x 时必须复跑本阶段测试。

三款 arm 和 motor 源码、CAN ID、协议、运动学、URDF、控制周期没有修改。
`DataRelay`、`MotionTimer`、`IterableQueue` 继续由 arm 维护。
本阶段没有使用 `CANTransport`、`open()`、`send_now()`、`immediate_dispatch()` 或 receipt 等待。
transport 新增方法的继承可见性不代表 arm 承诺支持高层调度模型。

| 调用/对象 | 兼容行为 |
| --- | --- |
| dispatcher 构造 | 相同位置参数、默认值；构造时立即打开 CAN |
| `send(msg)` | 仍异步入队，返回 `None`；忽略 transport 的 `SendReceipt` |
| 队列满 | transport `QueueFullError` 转回 `queue.Full` |
| 总线失效后发送 | transport `TransportError` 转回 arm `CANError` |
| 已停止后发送 | 保留 `RuntimeError` |
| `subscribe/unsubscribe/can_interface` | 委托 transport；重复订阅/取消订阅语义保留 |
| `stop()` | transport 负责 worker join；backend shutdown 失败记录日志且只尝试一次；线程无法停止仍抛 `RuntimeError` |
| `CanInterface` | 冻结 dataclass 原样转出；构造、字段、相等比较及旧导入可用，定义模块变为 transport |
| arm 异常 | 保留类名、定义模块、任意位置参数与 pickle；增加 transport 对应异常基类 |

异常对应关系：`LinkerbotError → LinkerbotError`、`CANError → TransportError`、
`TimeoutError → TimeoutError`、`ValidationError → ValidationError`、
`StateError → DeviceStateError`。因此新增了 transport 和部分 Python 内置异常类别的捕获能力；
并未将 arm 异常直接替换为不兼容的 transport 构造函数。

保留两个原始 API JSON 基线；源码签名检查对 dispatcher 显式解析继承/转出方法，
运行时检查只允许 `CanInterface` 定义模块以及异常构造的可反射性发生上述已说明的调整。

## 初始化与正常关闭顺序

左右臂 motor ID 分别为 61–67、51–57，顺序与关节顺序一致。

| 型号 | 初始化（打开 CAN、创建 motors、加载运动学之后） | 正常关闭 |
| --- | --- | --- |
| A7 | 检查全部电机 → 读取全部初始状态 → 验证初始状态 → 启动轮询 | 停止轮询 → 等待运动结束 → 停止 dispatcher → 标记关闭 |
| P7 | 与 A7 相同；前 5 个 A7Motor，后 2 个 MotorV2 | 与 A7 相同 |
| A7lite | 检查全部电机 → 逐个开启主动上报并读取初始状态 → 等待所有反馈 | 等待运动结束 → 停止 dispatcher → 标记关闭 |

A7/P7 轮询参数仍为位置/速度 10 ms、扭矩 50 ms、温度 1 s；MotorV2 心跳仍为 200 ms。
发送参数仍为 1 Mbps、队列 2000、间隔 300 μs、backend send 超时 100 ms、连续错误阈值 10。

## 依赖来源与 CI

实际验证的 transport 为 `1.0.0`，源码 commit
`e8c8bf7cc424cffa0234e659537c64f102b22426`。核对远程 `main`
`6c0724ddeef3af510fde5b865ffc1c3c26fae1b1`，运行源码和原有测试相同；新增内容为发布/CI 工具等。
没有修改 transport 工作区。

公司包源为 `https://gitea.linkerhub.work/api/packages/zhuzhixiang/pypi/simple`，
匿名访问返回 401。已有包源认证的环境可使用：

```bash
python -m pip install --index-url https://gitea.linkerhub.work/api/packages/zhuzhixiang/pypi/simple \
  --extra-index-url https://pypi.org/simple 'linkerbot-transport[can]>=1.0,<2.0'
python -m pip install -e '.[kinetix,test,dev]'
```

凭据通过已有 pip/keyring/netrc 配置提供，不写入仓库。源码开发和本次验证采用 README 中的
固定 commit 安装，或先从已确认 commit 的本地 transport 仓库安装，再安装 arm。
未将本地源码构建结果声称为公司包源发布产物验证。

CI 用 Gitea API + job token 下载固定 commit 的归档并预先安装，再解析 arm 依赖。
实例要求公共仓库也登录；限制跨仓库读取的 runner 可配置只读 `TRANSPORT_READ_TOKEN` secret。
下载失败直接终止，不能回退到不相关的公共 PyPI 版本。
本地已用认证 API 下载同一归档并在干净环境安装；实际 Actions job token 权限仍由远端 CI 验证。

## 验证与边界

详细结果见 [验证记录](VALIDATION.md) 的阶段 3 部分。可复现命令：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src python -m pytest -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src python tools/check_ros2_adapter.py ../linker_arm_ros2
unshare --user --map-root-user --net sh -c 'ip link add vcan-arm-phase3 type vcan && ip link set vcan-arm-phase3 up && ARM_TEST_VCAN=vcan-arm-phase3 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src .venv/bin/python -m pytest tests/test_transport_frames.py -q'
```

vcan 在独立网络命名空间内创建，退出后销毁；没有操作现有物理 CAN。
ROS2 验证读取工作区实际 `sdk_adapter.py` 和 `tests/test_sdk_adapter.py`，
通过测试进程中的 `linkerbot` / `linkerbot.arm` 别名指向 canonical arm；
明确校验 `_ARM_CLASSES` 的类身份。这是调用契约验收，正式 loader 仍待阶段 5。

以下边界保留并记录，不能据此宣称完整迁移或真机验收完成：

- transport 在 stop 后阻止继续回调、串行处理发送与关闭。这些底层并发修复随依赖引入，
  测试覆盖正常关闭、并发关闭、shutdown 失败和卡住的 worker；真机延迟/负载尚未测量。
- 原 arm 的 `_on_bus_error()` 只记录错误并设置 `_closed=True`，后续 `close()` 会提前返回；
  自动故障清理和构造失败清理仍需专门处理。本阶段测试显式释放 dispatcher，未声称此问题已修复。
- 原 motor 的寄存器读取仍为先发送再等待 relay；即时反馈可能发生竞争，本阶段保留原时序。
- CAN FD 副本及原通信测试留待阶段 4 清理；必须保留已被 arm 使用的薄兼容入口。
- arm/hand/聚合包共存、ROS2 正式导入、三款机械臂低速与双臂验收尚待后续阶段。

回滚时回退本阶段 PR，恢复阶段 2 `51c1ec2` 的独立 CAN 实现；保留 `linkerbot_arm` 命名空间。
