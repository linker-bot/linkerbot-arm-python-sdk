# 安装与环境配置

SDK 需要 Python 3.10+、NumPy 1.24+、SciPy 1.10+、Pydantic 2.x，
以及 `linkerbot-transport[can]==1.0.0`。A7、A7lite、P7、H75 构造时均需要 Pinocchio。
这些是通用 SDK 的最低依赖；当前运动学验证基线为 Pinocchio 4.1.0。

## 独立 Python 环境

以下是安装 PyPI Pinocchio 的独立环境路线。在未加载 ROS2 `setup.bash` 的终端中，
从 arm 仓库目录创建并激活环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

用于 PyPI Pinocchio 的独立 venv 仍会读取终端已有的 `PYTHONPATH` 和动态库搜索路径；已加载的 ROS 环境可能
让 Python 3.13 误读 Jazzy 的 Python 3.12 扩展。安装后检查下面的解释器和模块路径。

当前源码需要 transport 的整组准入能力，两个 CAN 后端都使用
[固定源码清单](../requirements/transport.txt)。
版本号仍为 1.0.0，已有发布包不包含这些新增能力，不能仅依据版本号判断是否满足要求。
具有公司 Gitea SSH 访问权限时，安装 transport 后再安装 arm：

```bash
python -m pip install --force-reinstall --no-deps -r requirements/transport.txt
python -m pip install -e '.[kinetix]'
```

`kinetix` extra 声明 `pin>=4.1.0`，Python 模块名为 `pinocchio`；它只负责 pip 安装依赖，
不启用或禁用 SDK 的运动学功能。
如果环境已提供兼容的 Pinocchio，可安装基础包 `python -m pip install -e .`。
如果已有库来自 ROS APT，且 Python 与该 ROS 发行版匹配，可先加载对应 `setup.bash`，
再使用能读取这些系统包的环境安装基础 SDK；具体方法见 [ROS2 接入](ROS2.md)。
Windows 使用 Conda 的 `pinocchio` 包，并在相同环境中安装基础 SDK。
ROS2 的系统依赖组合见 [ROS2 接入](ROS2.md)。

独立 Python 环境的 PyPI Pinocchio 4.1.0 依赖 cmeel-boost 1.90，后者要求 NumPy >=2。
该组合可与匹配的 SciPy 一起使用；不要将 ROS 的 NumPy 1.x 部署约束用于 `[kinetix]` 安装。
`constraints/ros2.txt` 保留已测的 NumPy 1.x、SciPy <1.14 范围，
`constraints/ros-jazzy.txt` 固定已验证的 Jazzy 部署版本；它们均不改变通用 SDK 的最低依赖。

## 检查安装

以下命令不连接 CAN：

```bash
python - <<'PY'
import sys
from importlib.metadata import version
print("Python:", sys.version, sys.executable)
import numpy, scipy, pinocchio, linkerbot_arm, linkerbot_transport
for module in (numpy, scipy, pinocchio):
    print(module.__name__, module.__version__, module.__file__)
for name, module in (("linkerbot-arm", linkerbot_arm), ("linkerbot-transport", linkerbot_transport)):
    print(name, version(name), module.__file__)
PY
python -c "from linkerbot_arm.arm.kinetix import ArmKinetix; print(ArmKinetix.from_builtin('a7', 'left').forward_kinematics([0.0] * 7))"
python -m pip check
```

六份左右臂 URDF 随安装包提供，无需设置额外资源路径。
完成安装后，按 [CAN 接口配置](zh/src/reference/can.md)连接硬件。
四种型号默认使用 `CANTransport`，无需设置环境变量；如需低层后端，在启动应用前设置
`LINKERBOT_ARM_TRANSPORT=dispatcher`。详见 [后端选择与故障恢复](TRANSPORT.md)。

## 版本管理

arm 的依赖声明暂时固定 transport 1.0.0，源码能力由 `requirements/transport.txt` 的
提交锁定。安装其他版本会产生依赖冲突；安装缺少批次 API 的旧源码会在打开 CAN 前报错。通过源码部署时固定 tag 或 commit，生产环境避免依赖可随时变化的 editable 源码。
