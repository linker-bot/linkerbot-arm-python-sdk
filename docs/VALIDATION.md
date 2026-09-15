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
