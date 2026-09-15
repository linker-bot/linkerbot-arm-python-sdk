# 阶段 0：协作与版本基线记录

更新时间：2026-09-15

## 仓库基线

| 仓库 | 本地分支 | 基线提交 | 版本 | 工作区状态 |
| --- | --- | --- | --- | --- |
| linkerbot-arm | `master` → `chore/phase-0-baseline` | `4f478aa` | 0.5.4 | clean |
| linkerbot-transport | `main` | `e8c8bf7` | 1.0.0 | 保留用户已有 `AGENTS.md` 未跟踪文件 |
| linkerbot-hand | `fix/quarantine-boundary-and-generation-signal`（与当时本地 `main` 同提交） | `56dd871` | 2.0.0 | 保留用户已有修改和未跟踪文件 |
| linker_arm_ros2 | `refactor/split-arm-sdk` | `985b57e` | ROS2 package 现行版本 | 保留用户已有修改 |

`linkerbot-arm` 的拆分基线包含原始实现提交 `64b8f47`，以及计划文档提交 `4f478aa`。原始 `linkerbot-python-sdk` 未修改。

## 远程基线

- `linkerbot-arm`：`master` 已推送到 `origin/master`。
- 基线标签：`arm-sdk-split-0.5.4`。
- 其他仓库的远程分支和提交只作审查依据；本阶段不修改、不提交、不重置这些仓库。

## 已完成验证

以下结果来自拆分前后专用环境的已完成验证记录：

- linkerbot-arm SDK 测试：366 项通过。
- linker_arm_ros2 测试：64 项通过。
- Python 3.10 最低依赖测试：通过。
- NumPy 1.x 与 ROS2 Pinocchio FK/IK：通过。
- arm wheel/sdist 构建及 wheel 外部安装：通过。
- ROS2 `colcon build`：通过。
- ROS2 launch 参数解析：通过。

## 本次环境复核

在系统 Python 中直接执行各仓库 `pytest -q` 未形成有效测试结果：

- arm：缺少源码安装路径，收集阶段无法导入 `linkerbot`。
- transport：缺少源码安装路径，收集阶段无法导入 `linkerbot_transport`。
- hand：系统环境缺少 `can`。
- 专用 uv 环境受到 ROS2 pytest 插件加载影响（缺少 `yaml`）；hand 的 uv 解析还受到本地 transport 版本解析限制。

这些是测试环境问题，不改变已保存的专用环境通过结果；阶段 1 前需要补充一条可复现的隔离测试命令，禁用无关 pytest 插件并使用本地 transport。

## 阶段 0 待办状态

- [x] arm 拆分基线提交并推送。
- [x] 固定 arm 版本和提交。
- [x] 保存已有 SDK/ROS2 验证结果。
- [x] 建立阶段 0 开发分支。
- [x] 在 Gitea 建立 arm 总 Issue：`linkerbot-arm#1`。
- [x] 在 transport 建立 dispatcher 兼容审查 Issue：`linkerbot-transport#46`。
- [x] 在 hand 建立共存安装审查 Issue：`linkerbot-hand#134`。
- [x] 为三个关联 Issue 补充验收条件、基线版本和关联关系；负责人沿用当前仓库维护者。

复核更正：阶段 0 的 Issue、arm 远程基线和阶段分支已建立，但 hand/transport 的有效测试结果、三个仓库发布源的核验记录尚未补齐。前述 SDK/ROS2 通过结果属于拆分基线，不能作为新命名空间下的 ROS2 验证结果。阶段 0 门禁尚未全部满足，执行状态以 `ARM_TRANSPORT_MIGRATION_TODO.md` 为准。
