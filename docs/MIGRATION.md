# 从完整 SDK 迁移

## 原有代码

以下调用路径保持原样：

| 层级 | 示例 |
| --- | --- |
| 顶层类与模型 | `from linkerbot import A7, A7lite, P7, Pose, ControlMode` |
| arm 公共导出 | `from linkerbot.arm import State, WayPoint` |
| 深层导入 | `from linkerbot.arm.a7.a7 import A7` |
| motor | `from linkerbot.arm.p7.motor_v2 import MotorV2` |
| 运动学 | `from linkerbot.arm.kinetix import ArmKinetix` |
| 通信与异常 | `from linkerbot.comm import CANMessageDispatcher`、`from linkerbot.exceptions import StateError` |

构造函数、默认参数、返回值、上下文管理器和全部 arm 方法保持一致，包括现有集成使用的私有方法。
独立发行的起始版本沿用 API 基线 `0.5.4`，此后由 arm 仓库独立维护版本。

## Python 环境

建议用新的虚拟环境安装并验收。若替换现有环境，先检查旧发行：

```bash
python -m pip show linkerbot linkerbot-py linkerbot-arm
```

确认该环境仅用于机械臂后，卸载已安装的旧 SDK，再从新仓库安装：

```bash
python -m pip uninstall linkerbot linkerbot-py
python -m pip install -e '/path/to/linkerbot-arm[kinetix]'
python -c "import linkerbot; from linkerbot import A7, A7lite, P7; print(linkerbot.__file__)"
```

`linkerbot-arm`、`linkerbot`、`linkerbot-py` 不能混装：pip 的发行名不同，并不会自动发现它们覆盖同一组文件。
若已混装，应移除这些发行后重新安装选定的一个。需要 `linkerbot.hand` 的现有应用仍应使用完整 SDK。

## ROS2

安装时使用 [ROS2 指南](ROS2.md) 中的系统依赖方案。代码支持：

1. 当前 Python 环境已安装的 SDK（保留原有最高优先级）。
2. `LINKERBOT_SDK_SRC=/path/to/linkerbot-arm/src`，也接受仓库根目录。
3. ROS2 仓库旁的 `linkerbot-arm/src`，或祖先工作空间的 `src/linkerbot-arm/src`。
4. 同样布局下的旧 `linkerbot-python-sdk/src`。

如果已安装旧 SDK，环境变量不会覆盖它；使用隔离环境或卸载旧包后切换。
发布部署时固定 SDK tag/commit；新包尚未推送/发布时使用本地路径安装。
SDK 仓库本身不是 ROS package，不需要添加为 `package.xml` 中不存在的 rosdep key。

## 回滚

切回旧 SDK 的已验证 commit 或安装包即可，ROS2 的新 loader 仍支持旧目录。
原仓库仍保留完整源码，ROS2 Topic、Service、配置和 SDK 调用签名没有因拆分改变。
