# ROS2 接入

[linkerbot-arm-ros2-sdk](https://github.com/linker-bot/linkerbot-arm-ros2-sdk) 将 `linkerbot_arm` 接入 ROS2，支持 A7、A7 Lite、P7。ROS2 包名仍为 `linker_arm_ros2`，无需 hand SDK 或旧聚合 SDK。

## 安装与环境

| 系统 | ROS2 | Python |
| --- | --- | --- |
| Ubuntu 22.04 | Humble | 3.10 |
| Ubuntu 24.04 | Jazzy | 3.12 |

使用对应 ROS 的系统 Python、APT Pinocchio 和读取系统包的 venv。ROS2 仓库提供 `constraints/ros-humble.txt`、`constraints/ros-jazzy.txt`，均使用 NumPy 1.26.4、SciPy 1.13.1；不要直接复用另一发行版的环境或构建结果。

完整安装流程见 ROS2 [安装与构建](https://github.com/linker-bot/linkerbot-arm-ros2-sdk/blob/main/docs/INSTALLATION.md)，开发预览见[ROS2 使用手册](https://doc.linkerhub.work/sdk-doc/#/linkerbot-arm-ros2/docs/environment_setup.md)。SDK 使用 ROS2 仓库 `requirements/source-versions.txt` 的配套提交，transport 从当前 `main` 安装，不限制版本号、tag 或旧提交。

APT 方案安装基础 SDK，不添加 `[kinetix]`；APT 提供 `pinocchio` 模块，没有 PyPI `pin` 发行元数据。即使只使用关节控制，SDK 构造仍需要 Pinocchio。独立 SDK 的通用 `constraints/ros2.txt` 不能替代 ROS2 的发行版 profile。

## 解释器与 SDK 来源

激活 ROS venv 后用当前 Python 构建，并检查生成节点的解释器：

```bash
python /usr/bin/colcon build --packages-select linker_arm_ros2 --symlink-install
head -n 1 install/linker_arm_ros2/lib/linker_arm_ros2/arm_node
python -c "import sys, linkerbot_arm; print(sys.executable, linkerbot_arm.__file__)"
```

loader 优先使用可导入的 `linkerbot_arm`，随后查找 `LINKERBOT_ARM_SRC`、旧兼容变量 `LINKERBOT_SDK_SRC` 以及附近旧目录名 `linkerbot-arm`。新目录 `linkerbot-arm-python-sdk` 应安装到当前环境，或显式指定：

```bash
export LINKERBOT_ARM_SRC=/absolute/path/to/linkerbot-arm-python-sdk/src
```

变量也接受仓库根目录，但不会覆盖已可导入的 SDK；变更后重启进程。它们不加载旧聚合包的 `linkerbot` 命名空间。节点在打开 CAN 前检查 `home_cancellable` 和 `get_feedback` 能力。

默认后端为 `CANTransport`；需要低层 dispatcher 时，在启动节点前设置 `LINKERBOT_ARM_TRANSPORT=dispatcher`，详见[通信后端](TRANSPORT.md)。只影响新实例，不自动恢复故障后的运动。

## 调用与响应

- 流式目标：`ArmNode → LinkerBotSDKAdapter.set_angles → SDK._set_angles`，保留 PP 调用链及 `None` 返回值。成功表示队列准入，不确认电机执行。
- 使能、失能、速度和模式配置等待物理发送回执，失败向调用者传播；回执表示 backend 接受发送，不是电机执行确认。
- ROS2 的速度配置使用后台生命周期 worker，保留最新合法待发目标并按年龄丢弃过期目标，不阻塞单线程执行器。
- P7 流式目标受 SDK 速度/加速度限幅，首帧保持测量位置，需要连续输入；SDK 主机轨迹期间拒绝并行外部目标。
- A7 Lite 软件停止持续锁存，须显式使能或成功回零才恢复，不会等待两秒自动恢复。

普通生命周期任务忙碌时服务返回失败、流式目标暂停接收。停止服务可以取消任务并清除待发目标，原请求返回失败；停止响应仍受 SDK 调用和 worker 退出时间影响。速度配置期间只有最新合法目标会保留。

## 可取消回零

`home_cancellable(cancel_event: threading.Event) -> None` 由任务线程调用。停止方设置事件，再调用 `emergency_stop()` 或 `disable()`，随后等待任务退出。事件本身只取消软件等待和新目标提交，不自行发送硬件停止命令，也不撤回已进入 FIFO 的帧。

旧 `home(blocking=...)`、`move_j(..., blocking=...)` 保持兼容。P7 的 `blocking=False` 仍同步发送整段主机轨迹，只省略末次等待。软件停止不能替代硬件急停。

## 反馈与检查

ROS2 使用 `get_feedback()` 检查七关节全部位置、速度、力矩。缺失、非有限、过期、SDK 关闭或总线故障会暂停 JointState；完整新反馈恢复后继续。反馈暂停本身不发送停止或失能。

SDK 保留原始主机接收时间；重复缓存不刷新年龄。ROS2 时间戳保守映射最老发布字段，不是硬件同步采样时间。数组接口 `get_angles()` / `get_velocities()` / `get_torques()` 仍保留缓存读取，但不保证新鲜度。详见[反馈接口](FEEDBACK.md)。

ROS2 环境检查脚本会验证 ROS 导入、SDK 能力和六个 URDF FK，不创建设备或打开 CAN：

```bash
python /path/to/linkerbot-arm-ros2/scripts/check_ros_environment.py
python -m pip check
```

## 接入范围

当前 ROS2 适配器不支持 H75，也未提供 MIT/CSP 话题或服务。独立标定与生命周期工具仅支持 A7 / A7 Lite。Humble/Jazzy 的 Docker 软件验证不代替真实 CAN、运动、停止和标定验证。
