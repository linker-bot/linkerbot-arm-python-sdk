# 安装与环境配置

SDK 需要 Python 3.10+、NumPy 1.24+、SciPy 1.10+、Pydantic 2.x，
以及 `linkerbot-transport[can]==1.0.0`。A7、A7lite、P7 构造时均需要 Pinocchio。

## 独立 Python 环境

在 arm 仓库目录创建并激活环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

当前源码需要 transport 的整组准入能力，两个 CAN 后端都使用以下固定源码清单。
版本号仍为 1.0.0，已有发布包不包含这些新增能力，不能仅依据版本号判断是否满足要求。
具有公司 Gitea SSH 访问权限时，安装 transport 后再安装 arm：

```bash
python -m pip install --force-reinstall --no-deps -r requirements/transport.txt
python -m pip install -e '.[kinetix]'
```

`kinetix` extra 安装 PyPI 的 `pin`，Python 模块名为 `pinocchio`。
如果环境已提供兼容的 Pinocchio，可安装基础包 `python -m pip install -e .`。
Windows 使用 Conda 的 `pinocchio` 包，并在相同环境中安装基础 SDK。
ROS2 的系统依赖组合见 [ROS2 接入](ROS2.md)。

## 检查安装

以下命令不连接 CAN：

```bash
python -c "from linkerbot_arm import A7, A7lite, P7, Pose; print('SDK imports OK')"
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
