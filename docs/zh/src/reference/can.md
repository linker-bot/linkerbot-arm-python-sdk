# CAN 接口

A7、A7lite 和 P7 使用经典 CAN，波特率为 **1 Mbps**。
构造函数的 `interface_name` 指定接口，`interface_type` 选择 python-can 后端，默认 `socketcan`。

## Linux / SocketCAN

查看系统接口，确认与机械臂连接的 CAN 名称：

```bash
ip -details link show
```

以 `can0` 为例，在启动 SDK 前配置链路：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
```

连接并读取状态：

```python
from linkerbot_arm import A7

with A7(side="left", interface_name="can0") as arm:
    print(arm.can_interface)
    print(arm.get_angles())
```

| 参数 | 说明 |
| --- | --- |
| `side` | 左臂 `"left"` 或右臂 `"right"` |
| `interface_name` | CAN 接口名称，例如 `"can0"` |
| `interface_type` | python-can 后端类型，默认 `"socketcan"` |

使用多个 USB-CAN 适配器时，分别确认接口与机械臂的对应关系，不依赖插入顺序确定左右臂。
例如左右臂分别配置到 `can0` 和 `can1` 后：

```python
from linkerbot_arm import A7

with A7("left", "can0") as left, A7("right", "can1") as right:
    print(left.get_angles())
    print(right.get_angles())
```

## Windows / PCAN

安装 PCAN 驱动并按[安装指南](../../../INSTALLATION.md)准备 Python 与 Pinocchio 环境后：

```python
from linkerbot_arm import A7

with A7("left", "PCAN_USBBUS1", interface_type="pcan") as arm:
    print(arm.get_angles())
```

其他后端的名称和驱动要求见 [python-can 文档](https://python-can.readthedocs.io/en/stable/interfaces.html)。

## 启动报错与关节编号

A7、A7lite、P7 的两臂均按 CAN ID 从小到大对应关节 1–7：

| 关节编号 | 右臂 CAN ID | 左臂 CAN ID |
| --- | --- | --- |
| 1 | 51 | 61 |
| 2 | 52 | 62 |
| 3 | 53 | 63 |
| 4 | 54 | 64 |
| 5 | 55 | 65 |
| 6 | 56 | 66 |
| 7 | 57 | 67 |

启动探测失败时，异常信息同时显示左右臂、关节编号与 CAN ID。例如：

```text
Right arm joint 3 (CAN ID 53) did not respond during startup discovery. Expected 7 joints, 6 responded. Check CAN communication, wiring, and power.
```

这表示**右臂关节 3 未在探测等待时间内响应**；53 是节点的 CAN ID，不是错误码。
多个关节未响应时会逐一列出。检查所选通道、通信状态、接线和供电；
单次探测超时本身不能判定电机损坏。
启动时的主动上报缺失和初始反馈缺失提示也使用相同的关节命名。

## 底层 dispatcher

需要直接使用通信接口时：

```python
from linkerbot_arm.comm import CANMessageDispatcher, CanInterface
```

`CANMessageDispatcher(interface_name, interface_type="socketcan")` 构造时打开 CAN 并启动收发线程。
它支持 `subscribe(callback)`、`unsubscribe(callback)`、`send(message)`、`stop()` 和上下文管理器。
`can_interface` 返回包含 `interface_name`、`interface_type` 的冻结 `CanInterface` 对象。

`send()` 异步入队并返回 `None`，不表示电机已完成动作。队列满抛出 `queue.Full`，
总线故障后的发送抛出 `linkerbot_arm.exceptions.CANError`，停止后的发送抛出 `RuntimeError`。
