# ROS2 接入

本文现有安装与 loader 说明针对 `arm-sdk-split-0.5.4`。
当前 0.6.0 开发分支使用 `linkerbot_arm`，现有 ROS2 loader 仍查找 `linkerbot.arm`，接入迁移尚未完成。
新命名空间下的 ROS2 验证将按 [TODO 阶段 5](ARM_TRANSPORT_MIGRATION_TODO.md) 执行。

`linker_arm_ros2` 通过 `ArmProtocol → LinkerBotSDKAdapter` 调用 SDK。
实际支持 A7、A7lite、P7；流式控制继续使用 `_set_angles`。

## 系统依赖方式

ROS2 的 Python、NumPy 和 Pinocchio 必须与其二进制环境一致。若系统尚未提供依赖，可按发行版安装，
例如 Jazzy（Humble 替换发行版名称）：

```bash
sudo apt install python3-venv python3-numpy python3-scipy ros-jazzy-pinocchio
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 -m venv --system-site-packages /path/to/ros-arm-venv
source /path/to/ros-arm-venv/bin/activate
python -m pip install -c /path/to/linkerbot-arm/constraints/ros2.txt -e /path/to/linkerbot-arm
```

这里安装**基础包**，Pinocchio 由 ROS2 提供；纯 Python 的 `[kinetix]` extra 可能安装 NumPy 2 的配套二进制，
不能用于替换 ROS2 的系统二进制组合。
系统包一般提供 NumPy 1.26/SciPy 1.11（Jazzy）或兼容版本，新 SDK 不再强制 NumPy 2。
SDK 的最低要求是 NumPy 1.24 / SciPy 1.10；较旧的 Humble 系统版本需在隔离环境满足最低版本并验证 ABI。

也可以直接使用源码，在运行节点的系统 Python 已具备四项基础依赖和 Pinocchio 的前提下设置：

```bash
export LINKERBOT_SDK_SRC=/path/to/linkerbot-arm/src
```

使用源码不会绕过运行时依赖。三款机械臂构造时都需要运动学，即使只调用关节控制也如此。

## 工作空间

```text
workspace/
  src/
    linker_arm_ros2/
    linkerbot-arm/
```

从 workspace 构建：

```bash
colcon build --packages-select linker_arm_ros2 --symlink-install
source install/setup.bash
```

也支持两个仓库并列的本地开发目录。运行节点的解释器必须能够看到上述依赖；仅激活 venv 不保证
`/usr/bin/colcon` 生成的入口会使用 venv。使用系统入口时依赖应由系统环境提供；
若使用 venv 部署，可在该 venv 安装 `colcon-common-extensions` 并使用它的 `colcon` 构建。

无需连接 CAN 的检查（从 ROS2 仓库运行）：

```bash
python -c "from linker_arm_ros2.sdk_loader import ensure_sdk_importable; ensure_sdk_importable(); import linkerbot; print(linkerbot.__file__)"
python -c "import numpy, scipy, pinocchio; from linkerbot.arm.kinetix import ArmKinetix; print(ArmKinetix.from_builtin('p7', 'left').forward_kinematics([0.0]*7))"
python -m pytest tests
```

第二条命令适用于已安装 SDK 或已将 SDK 的 `src` 加入 `PYTHONPATH` 的环境。
真实机械臂验收需覆盖连接、关节反馈、流式控制、回零、急停、失能和关闭；无硬件测试不替代这些验收。
