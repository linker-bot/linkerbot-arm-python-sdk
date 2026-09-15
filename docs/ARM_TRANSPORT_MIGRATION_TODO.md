# linkerbot-arm 模块边界与 Transport 迁移 TODO

本文是 `linkerbot-arm`、`linkerbot-hand`、`linkerbot-transport` 和 `linkerbot` 聚合包的共同执行计划。
每完成一个阶段，都要记录实际修改、测试结果、剩余风险和下一阶段；未通过阶段门禁时停止推进，不跨阶段堆积改动。

## 目标架构

```text
linkerbot-transport  →  linkerbot_transport
linkerbot-arm        →  linkerbot_arm
linkerbot-hand       →  linkerbot_hand
linkerbot            →  依赖聚合 + 旧 linkerbot 导入兼容门面
```

目标安装组合：

```bash
pip install linkerbot-arm linkerbot-hand linkerbot-transport
pip install linkerbot
```

arm 和 hand 的真实实现不再放在 `linkerbot` 包内。`linkerbot` 只负责依赖、懒加载和兼容转发。

## 执行规则

- 第一阶段只替换模块边界和低层 dispatcher，不改变电机协议、CAN ID、控制周期、运动学和 ROS2 语义。
- 第二阶段才评估 `CANTransport` 高层生命周期；它不作为第一次拆分的前置条件。
- 每个仓库遵循自己的 `AGENTS.md`。`linkerbot-transport` 的任何实现、测试、构建或文档改动，都必须先有 Issue。
- 保留其他仓库现有未提交修改，不重置、不覆盖、不纳入本次提交。
- 每个阶段使用独立 PR 和 Conventional Commits 提交；阶段 N 完成验收并合并到 `master` 后，再从更新后的 `master` 开始阶段 N+1。
- 保持线性历史，同步最新 `origin/master` 使用 rebase；PR 使用 squash、rebase 或 fast-forward 合并，不引入 merge commit。
- 完成项同时更新本 TODO，并记录实际验证结果；未验收项目保持未勾选。
- 真机测试按“mock → vcan → 单关节低速 → 多关节低速 → 双臂/共享总线”顺序执行。

## 分阶段合并顺序

1. 阶段 1：PR #2 已 squash 合并到 `master`，基线提交 `67d4757`，同时带入阶段 0 的基线文档。
2. 阶段 2：PR #3 已 squash 合并到 `master`，基线提交 `51c1ec2`。
3. 阶段 3：`refactor/phase-3-transport-1` 从 `51c1ec2` 建立，实现低层 dispatcher 接入；单独提交 PR，合并后再开始阶段 4。

阶段 2 的旧阶段 1 提交链和同步 merge 已从新历史中移除，PR #3 仅包含阶段 2 的增量。
阶段 0 的历史分支保留作追踪，不需要重复合并。

## 阶段 0：建立协作与版本基线

- [x] 在 `linkerbot-arm` 创建总 Issue：arm 命名空间迁移和 transport 替换。
- [x] 在 `linkerbot-transport` 创建关联 Issue：确认 dispatcher 兼容面；如果不改 transport 源码，只记录为依赖审查 Issue。
- [x] 在 `linkerbot-hand` 创建关联 Issue：确认 arm、hand、transport 可共存安装。
- [x] 记录三个仓库的本地基线 commit 和分支，见 [阶段 0 记录](PHASE0_BASELINE.md)。
- [ ] 补齐三个仓库默认分支和实际发布源的核验记录。
- [x] 固定版本目标：`linkerbot-transport 1.x`、`linkerbot-arm 0.6.x`、聚合包 `linkerbot 1.0.x`。
- [x] 保存迁移前 arm 与 ROS2 的验证记录。
- [x] 补齐 transport 有效测试基线：1.0.0 / `e8c8bf7`，360 passed（阶段 3）。
- [ ] 补齐 hand 的有效测试基线；阶段 0 仅记录了环境和依赖错误。

阶段门禁：Issue、分支、基线 commit 和测试结果都已记录；没有修改实现文件。

回滚点：删除本阶段分支即可，不触碰代码。

## 阶段 1：建立兼容性与调用清单

目标是把“兼容所有 arm 接口”变成可自动验证的清单。

- [x] 扫描主要公开导入、深层导入、类、函数和异常，保存初步清单。
- [ ] 补齐属性、枚举及全部导出的兼容覆盖。
- [x] 扫描 ROS2、标定工具、生命周期工具的实际导入和调用。
- [x] 固定以下现有调用路径；0.6.0 命名空间迁移后，旧路径将由聚合包兼容门面提供：

  ```python
  from linkerbot import A7, A7lite, P7
  from linkerbot.arm import Pose, State, WayPoint, ControlMode
  from linkerbot.arm.a7.motor import A7Motor, SensorType
  from linkerbot.arm.p7.motor_v2 import MotorV2
  ```

- [x] 为 A7、A7lite、P7 保存构造函数和方法签名快照。
- [x] 使用 fake motor 验证 `_set_angles`、限位检查和 `_motors` 角度转发。
- [x] 补齐构造后 `_motors`、`_can_dispatcher` 与正常关闭资源释放测试（阶段 3，三型号/左右臂）。
- [x] 验证已有方法签名和默认参数、Pose 转换及 ValidationError 导出身份。
- [x] 补齐异常层级、位置参数、pickle 和三型号上下文管理器行为测试（阶段 3）。
- [ ] 补齐全部返回模型的行为测试。
- [x] 按 A7、A7lite、P7 分别记录构造时打开 CAN、检查电机、读取初始状态及后台任务的实际顺序，见 [阶段 3 记录](PHASE3_TRANSPORT.md)。

阶段门禁：旧版本基线测试通过，兼容快照可在新旧实现上运行。

回滚点：只回滚新增测试和快照，不改运行代码。

## 阶段 2：将 arm 真实实现迁移到 `linkerbot_arm`

目标目录：

```text
src/linkerbot_arm/
├── __init__.py
├── arm/                 # 包含 common/、kinetix/ 及各型号
├── comm/                # 保留 CAN 兼容入口；阶段 4 清理剩余重复后端
├── motion_timer.py
├── relay.py
├── queue/
└── exceptions.py
```

- [x] 将 `src/linkerbot/arm` 迁移到 `src/linkerbot_arm/arm`。
- [x] 将内部导入全部改为 `linkerbot_arm.*`。
- [x] 保留 A7、A7lite、P7 的类结构、方法签名、私有方法和 URDF 资源。
- [x] 保留 `motion_timer`、`relay`、`queue` 作为 arm 的本地运行时工具。
- [x] 将 `linkerbot-arm` 的发行包名和 Python 模块名分离：发行名为 `linkerbot-arm`，模块名为 `linkerbot_arm`。
- [x] 确保源码树和 wheel 均不包含 `linkerbot/arm`。
- [x] 暂时不增加 `linkerbot` 兼容 shim；兼容 shim 统一放到后续聚合包。

阶段门禁：

- [x] `from linkerbot_arm import A7, A7lite, P7` 成功。
- [x] 在源码目录之外安装 wheel，加载六份 URDF 并验证 12 种 FK/IK 组合。
- [x] API 快照通过。
- [x] 运动学、fake motor、无硬件测试通过；构造与正常关闭生命周期测试在阶段 3 补齐。
- [x] arm 源码和测试不再依赖旧 `linkerbot` 模块路径。

回滚点：恢复命名空间迁移前的 arm commit；不涉及 transport 和 ROS2。

## 阶段 3：替换为 `linkerbot_transport` 的低层 dispatcher

这是第一次可交付的 transport 迁移，优先保证行为不变。

### 导入映射

| 旧位置 | 新位置 |
| --- | --- |
| `linkerbot.comm.can.CANMessageDispatcher` | `linkerbot_arm.comm.can.CANMessageDispatcher` 兼容层 → `linkerbot_transport.can.can.CANMessageDispatcher` |
| `linkerbot.comm.can.types.CanInterface` | `linkerbot_arm.comm.can.CanInterface` 转出 `linkerbot_transport.can.CanInterface` |
| `linkerbot.exceptions.ValidationError` | 保留 arm 同名异常并继承 `linkerbot_transport.errors.ValidationError` |
| `linkerbot.exceptions.TimeoutError` | 保留 arm 同名异常并继承 `linkerbot_transport.errors.TimeoutError` |
| `linkerbot.relay.DataRelay` | `linkerbot_arm.relay.DataRelay` |
| `linkerbot.motion_timer.MotionTimer` | `linkerbot_arm.motion_timer.MotionTimer` |
| `linkerbot.queue.IterableQueue` | `linkerbot_arm.queue.IterableQueue` |

- [x] A7、A7lite、P7 通过 arm 兼容层使用 transport 的低层 dispatcher；更正实际深层导入路径。
- [x] 验证 dispatcher 的 `subscribe()`、`unsubscribe()`、`send()`、`stop()`、`can_interface` 行为。
- [x] 忽略 `send()` 新增的 `SendReceipt` 返回值，保持现有 motor 调用时序。
- [x] 保留 arm 的 `StateError`，使其继承 transport 的 `DeviceStateError`。
- [x] 将 arm 异常接入 transport 层级，同时保留旧类身份、位置参数、`queue.Full` 与 `CANError` 捕获。
- [x] 不把 `DataRelay` 移入 transport；它是 arm 电机响应同步工具，不是物理传输工具。
- [x] 不在此阶段使用 `CANTransport`，不引入显式 `open()` 生命周期。

实现调整：transport 直接导入不能保持原 `send()` 返回值和异常，因此采用薄兼容层；
CAN I/O、队列和线程仍全部委托 transport。具体差异、依赖来源和保留问题见 [阶段 3 记录](PHASE3_TRANSPORT.md)。

### 测试

- [x] fake dispatcher 与真实 virtual dispatcher 测试三种 motor 的协议帧和反馈；覆盖 P7 混合 motor 构造。
- [x] 测试真实 backend 错误回调仍能令三款 arm 进入关闭/故障状态，且仅回调一次。
- [x] 测试 polling 停止顺序、`close()` 幂等性和上下文管理器。
- [x] 运行 transport 自身完整测试：360 passed；未修改 transport 实现。
- [x] 运行 arm 无硬件测试和实际 ROS2 adapter 测试；后者采用测试进程别名，正式 loader 仍待阶段 5。
- [x] 使用隔离网络命名空间内的 vcan 做真实 SocketCAN 收发验证：13 passed。

阶段门禁：原始 API 与新增 arm 行为测试通过，控制周期、协议帧和 arm 初始化/关闭顺序保持原实现。
transport 自带的并发关闭修复及尚未完成的真机验收范围已记录，不以此宣称所有故障生命周期问题已解决。

回滚点：将 arm dispatcher 导入切回迁移前实现；保留 namespace 阶段成果。

## 阶段 4：删除 arm 内重复通信实现

- [ ] 清理 `linkerbot_arm/comm` 剩余重复后端；保留阶段 3 的 CAN 薄兼容入口，不能直接删除整个目录。
- [ ] 删除 arm 仓库中重复的 CAN/CAN FD 测试。
- [ ] 将 CAN/CAN FD 测试责任归还 `linkerbot-transport`。
- [x] 确认 arm 依赖声明为 `linkerbot-transport[can]>=1.0,<2.0`（阶段 3 提前完成，已检查 wheel 元数据）。
- [ ] 确认 arm wheel 不包含 `linkerbot.comm`、CAN FD 后端和 hand 模块。
- [ ] 保留 `linkerbot_arm.relay`、`linkerbot_arm.motion_timer` 和 `linkerbot_arm.queue`。

阶段门禁：从干净虚拟环境安装 arm、hand、transport 三个包不会发生文件覆盖。

回滚点：恢复删除前的重复通信目录；不回滚已验证的命名空间迁移。

## 阶段 5：迁移 ROS2 到 canonical arm API

- [ ] `sdk_adapter.py` 首选 `linkerbot_arm`。
- [ ] 适配器支持 A7、A7lite、P7 的新导入路径。
- [ ] `LINKERBOT_ARM_SRC` 成为新的源码路径变量。
- [ ] 旧 `LINKERBOT_SDK_SRC` 保留一个过渡周期，并明确标记为兼容入口。
- [ ] 删除 ROS2 对旧完整 SDK 源码目录的默认依赖。
- [ ] 保留 `set_angles()` 到 SDK `_set_angles()` 的现有调用链。
- [ ] 更新 ROS2 安装和环境文档。
- [ ] 验证单臂、双臂 launch 参数解析和 ROS2 节点 fake arm 测试。

阶段门禁：ROS2 直接依赖 `linkerbot-arm`，不依赖聚合包；Topic、Service、配置和调用语义不变。

回滚点：恢复旧 SDK loader，但保留新 arm 包可选支持。

## 阶段 6：将完整 SDK 改造成聚合包

该阶段在 arm 低层迁移稳定后执行，不与阶段 2/3 同时开发。

- [ ] 删除完整 SDK 中 arm 和 hand 的真实实现副本。
- [ ] 聚合包依赖：

  ```toml
  linkerbot-arm>=0.6,<1.0
  linkerbot-hand>=2.0,<3.0
  linkerbot-transport>=1.0,<2.0
  ```

- [ ] 实现 `linkerbot/__init__.py` 的懒加载转发。
- [ ] 实现 `linkerbot.arm` 到 `linkerbot_arm` 的兼容门面。
- [ ] 实现 `linkerbot.hand` 到 `linkerbot_hand` 的兼容门面。
- [ ] 实现 `linkerbot.comm` 到 `linkerbot_transport` 的兼容门面。
- [ ] 实现旧异常名到 transport/arm 异常的稳定映射。
- [ ] 覆盖深层导入，例如 `linkerbot.arm.a7.a7` 和 `linkerbot.hand.*`。
- [ ] 验证类身份：`linkerbot.A7 is linkerbot_arm.A7`。
- [ ] 验证只安装 arm 时不会加载 hand 依赖，反之亦然。

阶段门禁：旧 SDK 公开导入测试通过，并且三个独立包可以与聚合包按设计安装。

回滚点：保留旧聚合包版本，不修改 arm 和 hand 的真实实现。

## 阶段 7：评估高层 `CANTransport`

这是第二阶段架构升级，不是第一次拆分的必要条件。

- [ ] 先完成需求确认：是否需要共享 CAN、自动重连、健康状态和多设备 transport pool。
- [ ] 为 arm 创建内部 transport adapter，不直接改 motor 协议代码。
- [ ] 设计 `open()`、`close()`、`recover()` 与现有 arm 构造函数的兼容关系。
- [ ] 将 motor 的 callback 订阅映射到 `CANRouteKey` / route subscription。
- [ ] 定义普通控制帧、读取请求、标定、使能、失能各自的 receipt 等待策略。
- [ ] 定义 `TransportError`、`DeviceStateError`、`TimeoutError` 到 arm 旧异常的映射。
- [ ] 验证 transport pool 对双臂和 arm + hand 共用物理总线的行为。
- [ ] 在 mock、vcan 和真机上验证重连、队列拥塞、关闭竞争和急停。
- [ ] 完成性能对比：发送延迟、反馈延迟、CPU、丢帧和关闭耗时。

阶段门禁：高层 transport 的所有可观察行为都有测试；不满足时继续使用低层 dispatcher，不强行切换。

回滚点：通过 feature flag 或内部构造参数切回低层 dispatcher。

## 阶段 8：发布与真机验收

- [ ] 对完成 transport 替换后的最终发布候选重新构建 wheel/sdist，检查包内容和依赖元数据；阶段 2 产物检查已完成。
- [ ] 在干净环境安装 arm、hand、transport，运行导入和测试矩阵。
- [ ] 在干净环境安装聚合包，运行旧导入兼容测试。
- [ ] ROS2 Jazzy 环境完成 NumPy、SciPy、Pinocchio 和 transport 组合验证。
- [ ] A7、A7lite、P7 完成单臂低速真机验证。
- [ ] 完成双臂独立 CAN 验证。
- [ ] 如启用高层 transport，再完成共享总线验证。
- [ ] 更新 CHANGELOG、迁移指南、版本兼容矩阵和回滚说明。
- [ ] 通过 PR 审查后再发布；未授权不合并、不删除分支、不关闭 Issue。

## 每一步的交付记录模板

```markdown
### Step N 完成记录

- 分支 / Issue：
- 修改仓库与提交：
- 实际修改：
- 已运行检查：
- 测试结果：
- 未完成事项：
- 剩余风险：
- 回滚方式：
- 下一步：
```

## 最终验收标准

- [ ] `linkerbot-arm` 只发布 `linkerbot_arm`，不再发布真实 `linkerbot` 实现。
- [ ] arm 不再复制 CAN/CAN FD transport 实现。
- [ ] arm、hand、transport 可在同一环境共存安装。
- [ ] 聚合包继续支持原有 `linkerbot.*` 调用。
- [ ] ROS2 直接依赖 `linkerbot-arm`。
- [ ] 低层 dispatcher 迁移不改变 arm 控制行为。
- [ ] 高层 `CANTransport` 只有在独立门禁全部通过后才启用。
- [ ] 真机验证结果与未验证范围均记录在发布文档中。

## 当前交付与验收记录

- 分支：`refactor/phase-3-transport-1`，基于阶段 2 squash 合并提交 `51c1ec2`。
- 阶段 3 实现、兼容测试、vcan 和独立 wheel 验证已完成，待本阶段 PR 审核合并。
- 阶段 0/1 尚有上述未勾选项，不据此宣称完整迁移、所有返回模型或真机验收完成。
- 验证结果与执行环境见 [验证记录](VALIDATION.md) 的阶段 3 部分。
- 下一步：阶段 3 合并后从更新的 `master` 开始阶段 4；ROS2 正式接入和旧导入门面分别在阶段 5、6 完成。

## 阶段 1 独立 PR 复核

- 分支：`chore/phase-1-api-inventory`，目标 `master`；包含阶段 0 的基线文档。
- SDK 仍为 0.5.4，源码仍位于 `src/linkerbot`。
- 同步了 Enum 快照测试修复、API 清单和验收状态更正；没有修改运行实现。
- Python 3.10：355 passed，12 项运动学测试跳过，38 项硬件测试排除。
- Python 3.13（含 Pinocchio）：367 passed，38 项硬件测试排除。
- Ruff、`git diff --check` 通过；测试均显式使用本分支 `src`。
- 此处测试结果属于阶段 1 独立分支的验证记录。PR #2 已于 2026-09-15 合并；合并不自动改变前文尚未完成的测试待办。

## 阶段 2 线性历史与冲突处理（2026-09-15）

- [x] 确认远程默认分支为 `master`，阶段 1 squash 提交为 `67d4757`。
- [x] 将阶段 2 变基到该提交，移除旧同步 merge，分支增量中 merge commit 数量为 0。
- [x] 解决 API 快照、导入和 TODO 冲突，保留阶段 1 的 Enum 修复以及阶段 2 的 `linkerbot_arm` 命名空间。
- [x] 对比变基前 `c0d1be9`，SDK 源码、测试、打包与 Ruff 配置内容完全一致。
- [x] 变基后复测：Python 3.10 为 355 passed / 12 skipped / 38 deselected；Python 3.13 为 367 passed / 38 deselected；Ruff、差异空白检查通过。
