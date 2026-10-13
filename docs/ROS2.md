# ROS2 接入

`linkerbot_arm` 可在 ROS2 的 Python 环境中使用。
个人 [linker_arm_ros2 fork](https://gitea.linkerhub.work/zhuzhixiang/linker_arm_ros2)
使用 `linkerbot_arm`，保留原有 PP `_set_angles()` 调用链。部署其他分支时需核对实际
adapter/loader；仍导入 `linkerbot` 的旧适配器需先迁移，不能仅替换 SDK 安装。

## Python 与运动学依赖

ROS2 的 Python、NumPy、SciPy 和 Pinocchio 必须与其二进制环境一致。
当前已验证的 Jazzy 组合为 Ubuntu 24.04、Python 3.12、NumPy 1.26.4、
SciPy 1.13.1，以及 APT 提供的 Pinocchio 4.1.0 / eigenpy 3.13.0。
Ubuntu 系统 SciPy 为 1.11.4；已验证组合在读取系统包的 venv 中使用 SciPy 1.13.1，
由 [Jazzy 部署锁](../constraints/ros-jazzy.txt)固定 NumPy 和 SciPy。

安装系统运动学依赖并创建读取系统包的环境：

```bash
sudo apt install python3-venv python3-numpy python3-scipy ros-jazzy-pinocchio
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 -m venv --system-site-packages /path/to/ros-arm-venv
source /path/to/ros-arm-venv/bin/activate
```

在该环境中通过 [transport 固定源码清单](../requirements/transport.txt)安装依赖，
再安装基础 SDK：

接入个人 ROS2 fork 的生命周期任务时，以该仓库 `requirements/source-versions.txt` 的
配套 arm/transport 提交为准。SDK checkout 必须来自该清单中的版本，包含
`constraints/ros-jazzy.txt`；旧提交提供的约束文件不能替代这份部署锁。

```bash
python -m pip install --force-reinstall --no-deps -r /path/to/linkerbot-arm/requirements/transport.txt
python -m pip install -c /path/to/linkerbot-arm/constraints/ros-jazzy.txt -e /path/to/linkerbot-arm
```

基础包使用系统提供的 Pinocchio。APT 包提供 `pinocchio` 模块，但没有 PyPI `pin` 发行元数据，
因此该安装不带 `kinetix` extra，也不在部署锁中加入 pip `pin`。
当前 PyPI Pinocchio 4.1.0 的 cmeel-boost 依赖要求 NumPy >=2，与上述 NumPy 1.x 锁不兼容。
`kinetix` 只声明 pip 安装依赖，不开关功能；已有兼容 Pinocchio 的基础包同样提供运动学。

通用 SDK 至少需要 Python 3.10、NumPy 1.24、SciPy 1.10。
保留的 [ros2.txt](../constraints/ros2.txt) 表示已测 NumPy 1.x / SciPy <1.14 范围，
不是所有 ROS2 版本的硬性要求。Humble 需使用其 Python 3.10，完整二进制依赖组合尚未验证，
不能直接沿用 Jazzy 的 Python 3.12 环境或声明其部署锁已适用。
独立 SDK 各型号的构造函数均加载运动学，即使应用只做关节控制也需要 Pinocchio。

## 不连接硬件的检查

```bash
python - <<'PY'
import sys
from importlib.metadata import version
print("Python:", sys.version, sys.executable)
import numpy, scipy, pinocchio, eigenpy, linkerbot_arm, linkerbot_transport
for module in (numpy, scipy, pinocchio, eigenpy):
    print(module.__name__, module.__version__, module.__file__)
for name, module in (("linkerbot-arm", linkerbot_arm), ("linkerbot-transport", linkerbot_transport)):
    print(name, version(name), module.__file__)
PY
python -c "from linkerbot_arm.arm.kinetix import ArmKinetix; print(ArmKinetix.from_builtin('p7', 'left').forward_kinematics([0.0] * 7))"
```

运行节点的解释器也必须能够导入这些依赖。在 `--system-site-packages` 环境中，
普通 `pip install colcon-common-extensions` 可能直接使用已满足依赖的 APT 包，
不会生成 venv 的 colcon 入口。Ubuntu Jazzy 已有 `/usr/bin/colcon` 时，在激活上述 venv 后，
从 ROS 工作空间用当前 Python 执行该入口，再核对生成节点的 shebang：

```bash
python /usr/bin/colcon build --packages-select linker_arm_ros2 --symlink-install
head -n 1 install/linker_arm_ros2/lib/linker_arm_ros2/arm_node
python -c "import sys; print(sys.executable)"
```

节点首行应指向当前 venv 的解释器。其他环境如果已经提供 venv 的 colcon 入口，
也可以直接使用 `colcon build`，但须核对其解释器及生成节点的 shebang。
SDK 是 Python 包，不是 ROS package；无需把它作为独立 ROS package 参与 colcon 构建。

新旧 SDK 的命名空间不同，但同环境共存仍要求依赖兼容。当前旧完整 SDK 要求
NumPy >=2.2.6，与 Jazzy 部署锁没有交集；需要继续使用旧 SDK 时，保留其独立环境。

## 适配器调用

现有 ROS2 接入的 A7、A7lite、P7 都以 `side`、`interface_name` 等参数构造。现有集成可继续使用：

- `enable()`、`disable()`、`reset_error()` 管理电机。
- `_set_angles(angles)` 转发七个关节目标；`move_j()` / `home()` 支持 `blocking` 参数。
- `get_angles()`、`get_velocities()`、`get_torques()` 获取反馈。
- `close()` 关闭连接；SDK 本身也支持上下文管理器。

本轮配套 SDK 源码中的 P7 `_set_angles()` 会按关节速度、加速度限幅：首周期保持缓存反馈位置，
需要连续外部控制指令才能趋向目标；SDK 主机轨迹运行期间拒绝并行外部目标。
A7lite 软件停止持续锁存，显式 `enable()` 或成功完成 PP `home()` 后才恢复。
这些行为须使用包含本轮修复的源码，既有发行版或旧 source lock 不会因版本号相同而自动获得修复。

个人 fork 的 loader 优先使用当前 Python 可导入的 `linkerbot_arm`，否则通过
`LINKERBOT_ARM_SRC` 查找仓库根目录或 `src`，再自动查找并列或工作空间中的 `linkerbot-arm`。
未设置新变量时，旧 `LINKERBOT_SDK_SRC` 作为兼容别名保留并输出迁移提示。
两个变量都只接受含 `linkerbot_arm` 的新 SDK 源码；不再解析旧完整 SDK 的 `linkerbot`
命名空间，也不将旧源码或已安装的旧包作为回退来源。当前节点会在打开 CAN 前拒绝
缺少 `home_cancellable` 的新 SDK，见下文。
优先把所需 SDK 安装到节点实际使用的 Python 环境；源码变量不会覆盖已安装的新 SDK。

完成 [固定源码安装](TRANSPORT.md) 后，A7、A7lite、P7 默认使用 `CANTransport`，启动节点无需
额外设置环境变量。需要 dispatcher 时，在启动节点的环境设置
`LINKERBOT_ARM_TRANSPORT=dispatcher`；取消该变量会恢复默认的 `CANTransport`。
ROS2 构造和控制调用保持原样；后端选择仅影响新建实例，故障后不会自动恢复运动。

## 可取消回零

A7、A7lite、P7 提供 `home_cancellable(cancel_event: threading.Event) -> None`，供 ROS2
等生命周期任务使用。现有 `home(blocking=...)` / `move_j(..., blocking=...)` 调用不变。
任务线程运行 `home_cancellable(event)`；停止方先 `event.set()`，再调用 `emergency_stop()`
或 `disable()`，然后等待任务线程退出。取消事件在回零进入 SDK 之前已经设置时，不提交目标。
P7 在每个目标准入前检查取消，停止方与正在准入的目标批次串行化。

该事件停止软件等待和新的回零目标提交，**不会自行向电机发送停止命令**；已经进入 CAN FIFO
的帧保持原有顺序，不自动清队列或重放。软件停止仍有 SDK 调用、排队与驱动耗时，不是硬件急停。
P7 的 `home()` / `move_j()` / `move_p()` 在 `blocking=False` 时仍同步发送整段轨迹，只省略末次等待。

个人 ROS2 fork 已将启动、使能和回零接入后台生命周期任务，回零使用 `home_cancellable`。
节点在打开 CAN 前检查该能力；缺少时提示更新配套源码，不退回不可取消回零。
状态发布和服务在启动任务前建立，任务运行时持续可用；重复普通请求返回 busy，
流式目标暂不接受。`disable` / `emergency_stop` 取消当前任务并调用 SDK 停止，
被取消的原请求返回 `success=false`。服务保持 `Trigger` 类型，响应等待操作实际返回。
停止状态锁存，只有显式使能或回零成功后才恢复流式目标准入；这些软件控制仍受 SDK、
CAN 排队和驱动耗时影响。安装该 fork 的 `requirements/source-versions.txt` 指定的源码组合。

## H75 接入范围

独立 SDK 已提供 `H75`，当前 ROS2 适配器仅注册 A7、A7lite、P7，H75 需另行接入。
接入时应显式加载 `linkerbot_arm.H75`，分别处理 PP/CSP，使用 A 单位的电流反馈；
不能将 `get_currents()` 结果填作 Nm 力矩，且 CSP 流式限速需要调用方实现。
