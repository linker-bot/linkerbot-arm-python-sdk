# 安装与首条反馈

机械臂 SDK 提供 A7、A7 Lite、P7、H75 的七关节控制、状态读取和运动学接口。先完成环境安装与 CAN 连接，再选择对应型号；不要混用不同型号的构造类或关节限位。

## 1. 安装 SDK

按[安装与环境配置](../../INSTALLATION.md)安装 arm SDK、transport 和 Pinocchio，并运行不连接硬件的导入检查。ROS2 用户选择[Humble / Jazzy 接入](../../ROS2.md)的配套环境。

## 2. 连接设备

四款机械臂均使用 1 Mbit/s 经典 CAN。先按[CAN 接口](reference/can.md)配置适配器、确认接口与左右臂，再读取首条反馈。例如 A7 左臂：

```python
from linkerbot_arm import A7

with A7(side="left", interface_name="can0") as arm:
    feedback = arm.get_feedback()
    print(feedback.connected, feedback.oldest_received_at)
    if feedback.is_fresh(max_age_s=0.5):
        print([joint.angle for joint in feedback.joints])
```

此例不主动使能或回零；SDK 连接仍会启动查询及型号所需的初始化，P7 还会按需配置 PTM 模式并发送心跳。连接检查不能代替使能前的姿态检查。

## 3. 选择设备功能

<a id="models"></a>

每款型号下按运动控制、参数配置、状态读取、运动学分章，示例和限位以相应型号为准。

| 型号 | 主要区别 |
| --- | --- |
| [A7](reference/a7/README.md) | 七个 V1 电机，驱动器侧 PP 点位控制 |
| [A7 Lite](reference/a7lite/README.md) | PP、MIT、CSP 与混合控制能力，按模式选择接口 |
| [P7](reference/p7/README.md) | V1 / V2 混合关节，主机流式速度及加速度限幅 |
| [H75](reference/h75/README.md) | IQ24 协议、抱闸及独立电流换算 |

## 4. 补充说明

- [反馈新鲜度](../../FEEDBACK.md)：有效快照、主机接收时间与超时。
- [通信后端与故障恢复](../../TRANSPORT.md)：后端选择、队列背压及资源关闭。
- [迁移说明](../../MIGRATION.md)：从旧 SDK 调整导入和安装方式。

需要 ROS2 话题和服务时使用[ROS2 接入](../../ROS2.md)；ROS2 暂不提供 H75 或 SDK 的全部控制模式。
