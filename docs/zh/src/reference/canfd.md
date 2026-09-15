# CAN FD 接口

A7、A7lite、P7 驱动使用经典 CAN，连接方式见 [CAN 接口](can.md)。
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
