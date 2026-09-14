# CAN FD 公共接口

独立 arm SDK 保留既有 `linkerbot.comm` 与 `linkerbot.comm.canfd` 的公共导出，
用于兼容调用公共通信组件的应用。当前 A7、A7lite、P7 驱动使用经典 CAN，连接方式见 [CAN](can.md)。

```python
from linkerbot.comm import (
    CANFDConfigOptions,
    CANFDInterface,
    CANFDMessage,
    CANFDMessageDispatcher,
    CANFDSendReceipt,
)
from linkerbot.comm.canfd import SocketCANFDBackend, dlc_to_length, length_to_dlc

assert length_to_dlc(12) == 9
assert dlc_to_length(9) == 12
```

`CANFDMessageDispatcher` 可通过 `interface` 参数接收满足 `CANFDBackend` 的后端；
不传时沿用厂商 `CANFDInterface`，接受 `device_index`、`channel_index`、`library_path`、`config`。
厂商模式需要另行提供对应系统和架构的动态库；导入模块本身不加载硬件动态库。
`SocketCANFDBackend` 通过 python-can 使用 Linux SocketCAN。

CAN FD 传输协议、发送回执、队列和关闭行为保持原样，并迁入了相应回归测试。
本发行不包含 L30、O20、O30i 等手部驱动；需要手部产品时使用完整 SDK，见 [迁移说明](../../../MIGRATION.md)。
