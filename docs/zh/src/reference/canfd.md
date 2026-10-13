# CAN FD 接口

A7、A7lite、P7、H75 驱动使用经典 CAN，连接方式见 [CAN 接口](can.md)。
当前包还提供 CAN FD 通信组件，可供已有直接调用这些组件的应用使用：

```python
from linkerbot_arm.comm import (
    CANFDConfigOptions,
    CANFDInterface,
    CANFDMessage,
    CANFDMessageDispatcher,
    CANFDSendReceipt,
)
from linkerbot_arm.comm.canfd import SocketCANFDBackend, dlc_to_length, length_to_dlc

assert length_to_dlc(12) == 9
assert dlc_to_length(9) == 12
```

`CANFDMessageDispatcher` 可通过 `interface` 参数接收满足 `CANFDBackend` 的后端；
不传时使用厂商 `CANFDInterface`，接受 `device_index`、`channel_index`、`library_path`、`config`。
厂商模式需要另行提供对应系统和架构的动态库；导入模块本身不加载硬件动态库。
`SocketCANFDBackend` 通过 python-can 使用 Linux SocketCAN。

`send(message)` 返回 `CANFDSendReceipt`，兼容 `concurrent.futures.Future`。
成功入队后不能取消；`receipt.result(timeout=...)` 在实际发送成功后返回 `None`，
发送失败抛出 arm 的 `CANError`。队列满时 `send()` 抛出 `queue.Full`；
停止 dispatcher 时，尚未完成的回执抛出 arm 的 `StateError`。

`stop()` 等待收发线程后关闭接口；线程未按时结束会记录警告并返回，可稍后再次调用。
接口关闭异常会记录警告。直接调用厂商 `CANFDInterface.close()` 时，关闭失败抛出
`CANError`，保留通道和库引用，之后可再次调用 `close()` 重试；只有资源实际释放后，
transport 才解除占用。`SocketCANFDBackend.close()` 不传播关闭错误，会记录警告，
阻止后续收发并保留关闭重试能力；关闭自己的 socket 不会把共享 CAN 接口设为 down。
