# 安装与环境配置

SDK 需要 Python 3.10+、NumPy 1.24+、SciPy 1.10+、Pydantic 2.x，
以及 `linkerbot-transport[can]==1.0.0`。A7、A7lite、P7 构造时均需要 Pinocchio。

## 独立 Python 环境

在 arm 仓库目录创建并激活环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

transport 托管在公司 Gitea。具有 SSH 访问权限时，可安装对应 1.0.0 的固定源码版本：

```bash
python -m pip install 'linkerbot-transport[can] @ git+ssh://git@git.linkerhub.work:12222/zhuzhixiang/linkerbot-transport.git@e8c8bf7cc424cffa0234e659537c64f102b22426'
```

已有公司包源认证的环境，也可以安装发布包：

```bash
python -m pip install --index-url https://gitea.linkerhub.work/api/packages/zhuzhixiang/pypi/simple \
  --extra-index-url https://pypi.org/simple 'linkerbot-transport[can]==1.0.0'
```

包源要求登录；凭据通过已有 pip、keyring 或 netrc 配置提供。安装 transport 后安装 arm：

```bash
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

## 版本管理

arm 的依赖声明固定 transport 1.0.0。安装其他版本会产生依赖冲突；请使用与 arm
发行版本匹配的组合。通过源码部署时固定 tag 或 commit，生产环境避免依赖可随时变化的 editable 源码。
