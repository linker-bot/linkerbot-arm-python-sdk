# H75 机械臂

H75 为七自由度机械臂，使用维一 CAN 协议和 IQ24 大端编码。
本实现来源于完整 SDK 的 `feat/h75_arm@9041b05`，接入独立 SDK 的通信、轮询和运动管理。

## 快速开始

先按[安装指南](../../../../INSTALLATION.md)安装当前 transport 源码与运动学依赖，
完成 [CAN 配置](../can.md)。H75 使用经典 CAN，波特率为 1 Mbps。

```python
from linkerbot_arm import H75

with H75(side="left", interface_name="can0") as arm:
    print(arm.get_angles())       # 关节 rad
    print(arm.get_currents())     # 电流 A
    print(arm.get_pose())         # TCP 位姿
```

构造会检查七个电机、读取初始状态并启动轮询，不自动使能、松闸或标零。
导入 `H75` 不加载 Pinocchio；创建 H75 或独立运动学模型时需要 Pinocchio。

| 构造参数 | 默认值 | 说明 |
| --- | --- | --- |
| `side` | 必填 | `"left"` 或 `"right"` |
| `interface_name` | 必填 | 如 `"can0"` 或 `"PCAN_USBBUS1"` |
| `interface_type` | `"socketcan"` | python-can 接口类型；PCAN 使用 `"pcan"` |
| `tcp_offset` | `[0.0, 0.0, 0.0]` | 相对末端 link 的 XYZ 平移，单位 m |
| `world_frame` | `"urdf"` | `"urdf"` 或 `"maestro"` |
| `motor_configs` | `None` | 仅关键字参数；7 个 `H75MotorConfig`，省略时使用来源分支默认值 |

CAN ID：左臂 `61–67`，右臂 `51–57`，按 J1–J7 排列；Python 列表索引为 `0–6`。
七个电机共用一条连接。默认 CANTransport；兼容 `LINKERBOT_ARM_TRANSPORT=dispatcher`。
后端选择、队列与关闭说明见[通信管理](../../../../TRANSPORT.md)。

## 控制模式与抱闸

| SDK 模式 | 维一模式值 | 用途 |
| --- | --- | --- |
| `ControlMode.PP` | `0x06` | 驱动 S 曲线位置模式；回零与点位运动 |
| `ControlMode.CSP` | `0x03` | 普通位置模式；由主机提供流式目标，无驱动轨迹规划 |

`enable()` 默认选择 PP；显式选择过 CSP 时再次使能仍使用 CSP。H75 不支持 MIT。
切换模式需要先失能，运动中或电机已使能时会抛出 `StateError`。

第 1、2 关节带抱闸：SDK 逐个使能电机，并通过新的 `0x2B` 查询确认已使能；
七关节均确认后，才发送两关节松闸指令。
失能时先发抱闸指令，再发七关节失能指令。其他五关节不发送抱闸指令。
模式、使能、抱闸等生命周期开关等待实际发送回执，单帧发送超时或失败直接报错。
未开始发送的超时命令会过期，已在发送中的帧无法撤回。发送完成和使能状态读回仍不代表抱闸机械动作已完成。
两种标准后端均支持该路径；自定义底层 dispatcher 必须提供受确认的发送能力，SDK 不会把普通入队当作发送成功。

## 生命周期与异常

| 方法 | 行为 |
| --- | --- |
| `enable()` | 清错、选择模式、使能、松闸；中途失败尝试抱闸和失能，保留原始异常 |
| `disable()` | 取消后续运动提交，先抱闸再失能；抱闸发送失败时不发送该关节失能；继续处理其他关节并报告错误 |
| `reset_error()` | 向各电机发送清错指令 |
| `emergency_stop()` | 取消后续运动提交，整组提交缓存角度作为保持目标；不自动抱闸或失能 |
| `home()` | 移动到七个零角度，需要 PP；不是标零 |
| `home_cancellable(cancel_event)` | 可取消等待的回零；停止电机仍需调用停止或失能 |
| `calibrate_zero()` | 要求失能且无 SDK 运动；发送标零和保存指令，会改变 EEPROM |
| `save_params()` | 无 SDK 运动时向各电机发送保存命令，不自动读回验证 |
| `close()` | 先拒绝新命令，等待已有规划/运动及参数恢复，再停止轮询并关闭连接；失败可重试，不自动失能 |

使用 `with` 自动关闭连接；运动结束或异常时仍应按实际需求显式失能。
连接中途失败会清理后台任务和通信连接。通信错误按 `CANError`、`TimeoutError` 传播；
构造参数错误使用 `ValueError` / `ValidationError`，未响应关节使用 `StateError` 并包含左右臂、关节及 CAN ID。

## 功能模块

- [运动控制](motion.md)：PP、CSP、回零、轨迹与停止
- [运动学](kinematics.md)：坐标系、关节限位、FK/IK
- [状态读取](state.md)：电流、速度、温度及缓存含义
- [参数配置](config.md)：减速比、固件速度补偿、独立减速度与标零工具

关闭等待期间仍可急停或失能；取消不代表规划线程已经退出，SDK 会等其清理完成。
关闭期间发生的轨迹恢复错误会向关闭调用方报告。不要从正在执行该机械臂轨迹的回调内调用 `close()`，应在该调用返回后关闭。
