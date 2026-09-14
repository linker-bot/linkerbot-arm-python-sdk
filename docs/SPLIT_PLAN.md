# arm 独立仓库拆分计划与架构决策

## 基线与验收范围

- SDK：`linkerbot-python-sdk` 0.5.4，commit `c6167ba`（完整哈希见接口基线 JSON）。
- ROS2：`linker_arm_ros2`，commit `985b57e4606b25487e891565c4d843723311eea3`。
- 依据源码核对 `arm_node.py`、`arm_factory.py`、`sdk_adapter.py`、两个 launch 文件和两个辅助脚本；旧文档仅作参考。
- 兼容范围包括所有 arm 层级的导入、函数参数（含默认值、关键字参数）、属性、模型、异常、枚举、底层 motor，
  以及 ROS2 使用的 `_set_angles`、`_motors`。手部 API 属于完整 SDK，不随 arm 包发布。

## 实施步骤

1. **已完成：盘点接口与依赖。** 三款 arm 相互共享 motor、common、kinetix；P7 前五个关节复用 A7Motor，
   后两个使用 MotorV2，不能只按 A7/A7lite 的文档范围复制。
2. **已完成：提取可独立安装的仓库。** 迁入 arm、comm、exceptions、relay、motion_timer、queue、类型标记和六份 URDF，
   保留许可证；去掉 hand 和仅供 hand 使用的 TOML 依赖。
3. **已完成：整理安装边界。** 发行名 `linkerbot-arm`，导入名 `linkerbot`；支持系统 NumPy 1.x，
   Pinocchio 保留在 `kinetix` extra，允许 ROS2 自行提供二进制依赖。
4. **已完成：接入 ROS2。** 一个不依赖 rclpy 的 loader 供适配器与辅助脚本共用，识别新旧目录与环境变量。
5. **已完成：验证与交付。** 接口基线、上游文件逐字节对照、共享模块回归、真实 FK/IK、ROS2 适配器/节点测试、
   wheel/sdist 构建及独立安装验证均已通过；最终结果记录在 [验证记录](VALIDATION.md)。

## 架构

```text
linker_arm_ros2: Topic / Service / launch / 配置
  └─ ArmProtocol → LinkerBotSDKAdapter → sdk_loader
       └─ linkerbot-arm 发行包（Python 名仍为 linkerbot）
            ├─ arm/a7、arm/a7_lite、arm/p7：机型行为与 motor
            ├─ arm/common：模型与控制模式
            ├─ arm/kinetix：FK、IK、轨迹规划、URDF
            └─ comm、exceptions、relay、motion_timer、queue
```

保留现有分层与单份实现，不增加类包装、模块别名映射或第二套 `linkerbot_arm` 导入路径。
这样对象身份、异常捕获、内部相对导入和用户深层导入都不会因拆分改变。
CAN FD 虽非当前 arm 的传输方式，但属于既有 `linkerbot.comm` 公共导出，且不增加必装依赖，连同回归测试保留。
当前不再拆第三个公共基础包，避免多仓库发布顺序和版本耦合。

A7/A7lite/P7 的行为实现保持逐字节一致，仅运动学入口的安装提示改为新发行名。
后续可基于已有测试逐步提取重复运动算法；本次不同时重构硬件时序、急停、运动控制或 motor 协议。

## 代码确认的重要细节

- 三款 arm 顶层直接导入 NumPy/SciPy，构造时加载 Pinocchio。旧 ROS2 文档“核心不直接 import NumPy/SciPy”不成立。
- ROS2 `_ARM_CLASSES` 已包含 `p7`；两个独立硬件脚本仍仅支持 A7/A7lite，此次只统一加载逻辑。
- 节点的 `set_angles` 经适配器转给 `_set_angles`；不能换成会触发运动计时器的 `move_j`。
- `world_frame` 和 `tcp_offset` 是节点参数并透传给 SDK；当前 launch 没有从 YAML 传入这两个参数，使用节点默认值。
- `position_kp` 的节点应用逻辑仅在 `a7lite` 生效。
- 原有部分 basic/lifecycle 测试未带 hardware 标记，本仓库已补齐，默认 pytest 排除全部硬件测试。

## 维护与迁移边界

新旧发行包占用同一 Python 模块路径，不能混装；这项约束来自保持全部旧导入兼容。
同进程控制手和臂的项目暂时保留完整 SDK。若以后也拆分手部，应统一规划命名空间和公共包发行，
不能让两个发行包继续各自拥有相同文件。

旧仓库保留为来源和回滚基线，没有删改其 hand 或 arm 源码。独立 arm 仓库作为后续 arm 维护入口；
是否在完整 SDK 中停止发布 arm、改为聚合发行，需要配合完整 SDK 的后续版本迁移单独处理。
新仓库采用独立历史，记录来源 commit 和校验清单，不复制无关的 hand Git 历史。
