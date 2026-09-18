# ROS2 接入

`linkerbot_arm` 可在 ROS2 的 Python 环境中使用。
个人 [linker_arm_ros2 fork](https://gitea.linkerhub.work/zhuzhixiang/linker_arm_ros2)
已首选 `linkerbot_arm`，保留原有 PP `_set_angles()` 调用链。部署其他分支时需核对实际
adapter/loader；仍导入 `linkerbot` 的旧适配器需先迁移，不能仅替换 SDK 安装。

## Python 与运动学依赖

ROS2 的 Python、NumPy、SciPy 和 Pinocchio 必须与其二进制环境一致。以 Jazzy 为例：

```bash
sudo apt install python3-venv python3-numpy python3-scipy ros-jazzy-pinocchio
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 -m venv --system-site-packages /path/to/ros-arm-venv
source /path/to/ros-arm-venv/bin/activate
```

在该环境中按[安装指南](INSTALLATION.md)先安装 transport 1.0.0，然后安装基础 SDK：

```bash
python -m pip install -c /path/to/linkerbot-arm/constraints/ros2.txt -e /path/to/linkerbot-arm
```

基础包使用系统提供的 Pinocchio；不要用独立环境的 `kinetix` extra 替换 ROS2 的二进制依赖组合。
SDK 至少需要 NumPy 1.24 / SciPy 1.10。Humble 等较旧系统需要在兼容环境中满足这些最低版本。
三款机械臂的构造函数均加载运动学，即使应用只做关节控制也需要 Pinocchio。

## 不连接硬件的检查

```bash
python -c "import linkerbot_arm; from linkerbot_arm import A7, A7lite, P7; print(linkerbot_arm.__file__)"
python -c "import numpy, scipy, pinocchio; from linkerbot_arm.arm.kinetix import ArmKinetix; print(ArmKinetix.from_builtin('p7', 'left').forward_kinematics([0.0] * 7))"
```

运行节点的解释器也必须能够导入这些依赖。激活 venv 不保证系统 `/usr/bin/colcon`
生成的入口使用同一解释器；使用 venv 部署时，在该环境中安装和使用 colcon。
SDK 是 Python 包，不是 ROS package；无需把它作为独立 ROS package 参与 colcon 构建。

## 适配器调用

三款 arm 都以 `side`、`interface_name` 等参数构造。现有集成可继续使用：

- `enable()`、`disable()`、`reset_error()` 管理电机。
- `_set_angles(angles)` 转发七个关节目标；`move_j()` / `home()` 支持 `blocking` 参数。
- `get_angles()`、`get_velocities()`、`get_torques()` 获取反馈。
- `close()` 关闭连接；SDK 本身也支持上下文管理器。

个人 fork 的 loader 优先使用已安装的 `linkerbot_arm`，否则通过 `LINKERBOT_ARM_SRC`
查找仓库根目录或 `src`。旧 `LINKERBOT_SDK_SRC` 在该 fork 中保留过渡支持并输出提示，
旧完整 SDK 必须经该变量显式提供。优先把所需 SDK 安装到节点实际使用的 Python 环境。

可选高层 CAN 后端使用 [固定源码安装和环境变量](TRANSPORT.md)。在启动节点的环境设置
`LINKERBOT_ARM_TRANSPORT=cantransport` 即可选择；ROS2 调用保持原样，故障后不会自动恢复运动。
