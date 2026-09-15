# 拆分验证记录

验证日期：2026-09-14。对照 SDK `c6167ba1a0fc72de074985fbb001e1e5ee75b739`，
ROS2 原始基线 `985b57e4606b25487e891565c4d843723311eea3`。

## 已完成

| 检查 | 结果 |
| --- | --- |
| 上游源码和资源对照 | 41 个文件核对通过；arm 实现和 URDF 完全一致，仅运动学入口的安装提示改名 |
| 调用兼容性基线 | 396 个函数/方法签名，包含默认值、返回注解、装饰器与私有方法 |
| 独立 Python 3.13.14 | 366 项通过，38 项硬件测试排除；NumPy 2.5.3 / SciPy 1.18.1 / Pinocchio 4.1.0 |
| 最低版本 Python 3.10.20 | 354 项通过，12 项运动学跳过，38 项硬件测试排除；NumPy 1.24.0 / SciPy 1.10.0 / Pydantic 2.0 / python-can 4.6.1 |
| ROS2 系统依赖 Python 3.12.3 | 354 项 SDK 测试通过；系统 NumPy 1.26.4 / SciPy 1.11.4 |
| ROS2 官方 Pinocchio + NumPy 1.x | 补充的 12 项真实 FK/IK 测试通过；官方 Pinocchio 4.1.0、coal、eigenpy 包解压到临时目录加载 |
| ROS2 适配器与实际节点 | 64 项通过；使用真实 rclpy、JointState、Trigger，机械臂替身不连接 CAN |
| ROS2 构建 | Jazzy 下 `colcon build --packages-select linker_arm_ros2 --symlink-install` 通过 |
| launch 解析 | 单臂与双臂 `--show-args` 均通过 |
| 独立安装 wheel | 在 `/tmp` 使用单独环境运行全部测试：366 项通过，38 项硬件测试排除；`uv pip check` 通过 |
| 辅助脚本入口 | 标定与生命周期脚本的 `--help` 均通过，无需连接 CAN |
| 静态检查 | SDK、测试与工具 Ruff 检查通过；新增 ROS2 loader 与测试检查通过 |

运动学覆盖 A7/A7lite/P7 × 左右臂 × URDF/Maestro 坐标系，共 12 种组合，包含 TCP 偏移和 FK/IK 往返。
真实流式方法使用 fake motor 验证角度转发、限位拒绝和 `check_limits`；ROS2 adapter 使用真实 SDK 类的 autospec，
检查构造参数、协议全部 15 个方法、返回值和异常传播。

## 安装与交付检查

wheel/sdist 包含六份 URDF、`py.typed` 和许可证，且不包含 hand 模块。
打包后在源码目录以外安装 wheel 并运行兼容性测试，避免被源码路径掩盖打包遗漏。
最终构建产物位于仓库 `dist/`（不纳入 Git）。

测试环境均在本仓库 `.venv*` 中，ROS2 官方二进制包仅解压到 `/tmp/linkerbot-arm-ros-deps`；
未修改系统 Python、ROS2 软件包或 CAN 配置。原完整 SDK 工作区保持不变。

## 实测中处理的问题

- ROS2 Jazzy 的 `launch_testing` 插件与 pytest 9 的 hook 不兼容；测试 extra 限定 pytest `<9`，以 8.4.2 验证。
- 保留上游 arm 三处 import 顺序，Ruff 配置仅针对这三处豁免排序，不改控制实现。
- 已有真机 basic/lifecycle 测试缺少 hardware 标记，迁入时统一补齐，默认测试不会尝试打开 can0。

## 验证边界

本次没有连接实际机械臂，没有执行标定、使能、运动或急停实机操作。
协议和时序实现保持上游内容，但部署现场仍需对 A7、A7lite、P7 做硬件验收。
拆分基线及阶段 0～2 分支已推送到新 SDK 仓库 origin；当前尚未合并到 master、发布包或执行真机验收。

## 命名空间 PR 复核（2026-09-15）

本节验证 `linkerbot_arm` 开发分支；上文的 ROS2 64 项测试和 colcon 结果仅适用于拆分基线。
当前 ROS2 loader 仍导入 `linkerbot.arm`，不能以历史结果证明新命名空间已兼容 ROS2。

| 检查 | 结果 |
| --- | --- |
| Python 3.10.20 最低依赖 | 355 passed，12 项因未安装 Pinocchio 跳过，38 项硬件测试排除 |
| Python 3.13.14，源码目录外安装 wheel | 367 passed，38 项硬件测试排除；六份 URDF、12 种 FK/IK 组合通过 |
| wheel/sdist | 构建通过；各含六份 URDF；wheel 包含 `py.typed`，不含 `linkerbot/` |
| 静态与依赖检查 | `ruff check src tests tools`、`git diff --check`、`uv pip check` 通过 |

wheel 环境：NumPy 2.5.3、SciPy 1.18.1、Pinocchio 4.1.0、Pydantic 2.13.5、python-can 4.6.1、pytest 8.4.2。
产物与隔离环境位于 `/tmp/linkerbot-arm-pr-gj48plpn`。测试清除了 ROS2 的 `PYTHONPATH`，
设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，未运行真机用例。

复核修复了 Ruff 豁免目录仍指向旧命名空间的问题，以及快照将 Python 3.10/3.13 的 Enum
自动生成签名和方法差异误判为 SDK 变化的问题。枚举改为核对 SDK 成员名与值，
源码定义的方法仍由原始 AST 签名基线校验。

阶段 0/1 的剩余兼容门禁、transport 替换、详细文档迁移、ROS2 新导入适配和聚合包旧导入门面
尚未完成，实际完成情况见主 TODO。本分支的版本字段为 0.6.0，但尚未发布该版本。

## 阶段 3 低层 transport 验证（2026-09-15）

阶段 2 已经通过 PR #3 squash 合并为 `51c1ec2`；本阶段分支
`refactor/phase-3-transport-1` 从该提交建立，没有引入 merge commit。
实现说明、初始化顺序和回滚见 [阶段 3 记录](PHASE3_TRANSPORT.md)。

| 检查 | 本阶段实际结果 |
| --- | --- |
| 原始兼容基线 | 两个 JSON 未重写；396 个源码函数/方法签名及运行时基线检查通过，委托方法仍逐项核对 |
| Python 3.13.14 / 完整依赖 | 413 passed，38 项硬件用例排除 |
| Python 3.10.20 / 最低依赖 | 401 passed，12 项运动学因没有 Pinocchio 跳过，38 项硬件用例排除 |
| transport 1.0.0 自身测试 | 360 passed，使用 `e8c8bf7` checkout，运行源码/原测试与远端 `6c0724d` 相同 |
| 实际 ROS2 adapter | 49 passed；实际三型号类 autospec，15 个协议操作、默认参数、返回值、异常传递 |
| Linux vcan / SocketCAN | 13 passed；独立 user/network namespace，三 motor 实际帧收发与寄存器超时 |
| wheel / sdist | 构建成功，各含六份 URDF；无旧 `linkerbot/` 与 hand；依赖元数据包含 transport `[can]>=1.0,<2.0` |
| 源码目录外的干净 wheel 环境 | 413 passed / 38 deselected，含六模型、12 种 FK/IK；`uv pip check` 通过 |
| 静态检查 | Ruff、`git diff --check` 通过；arm/motor、运动学、URDF、本地 relay/timer/queue 源码相对阶段 2 无差异 |

新增 46 项回归覆盖三款 arm 左右臂构造和正常关闭、上下文异常传播、总线故障标记、
三种 motor 的标准/扩展 CAN 帧与反馈、异常层级与 pickle、冻结 CanInterface、
SendReceipt 忽略、旧发送异常、并发失败关闭，以及回调内关闭后的线程回收。
原通信测试保留到阶段 4，底层 monkeypatch 定位改为 transport 的实际实现模块。

完整 wheel 环境：transport 1.0.0、NumPy 2.5.3、SciPy 1.18.1、Pinocchio 4.1.0、
Pydantic 2.13.5、python-can 4.6.1、pytest 8.4.2。
最低依赖：NumPy 1.24.0、SciPy 1.10.0、Pydantic 2.0、python-can 4.6.1。
测试清除继承的 ROS2 `PYTHONPATH` 或显式设置为本分支 `src`，关闭 pytest 自动加载插件；
完整测试显式加载 `pytest_timeout`。源码外测试确认 arm/transport 均来自独立环境的 `site-packages`。

产物：`/tmp/linkerbot-arm-phase3-dist`；干净环境：`/tmp/linkerbot-arm-phase3-wheel-venv`。
transport 从认证 Gitea API 下载固定 commit 归档后安装，未冒充已发布 wheel 验证。
归档 SHA256：`5c4bf0dc08538804981c3980358e417484e4dfe7305407b03f019f8b09d3ba0e`。

ROS2 对照对象为现有工作区 `985b57e` 加已有修改，测试没有更改该仓库。
`tools/check_ros2_adapter.py` 在测试进程内提供旧名到 canonical 类的别名，并验证 `_ARM_CLASSES` 身份。
没有将这一结果当作正式 loader、rclpy 节点或 launch 的阶段 5 验收。
现有物理 CAN、完整 SDK、hand 与 transport 工作区均未修改；未进行使能、标定或真机运动。

阶段 3 保留的故障清理问题、即时反馈竞争及 transport 底层并发差异见实现记录。
阶段 4 清理、三包共存、聚合包兼容、正式 ROS2 接入和最终真机验收继续按 TODO 执行。
