# 阶段 1：Arm API 与 ROS2 调用清单

本清单由当前源码和 ROS2 实际调用生成，作为 `linkerbot → linkerbot_arm` 迁移前的兼容基线。快照位于 `tests/fixtures/api_surface_snapshot.json`。

## 公开导入路径

```python
from linkerbot import A7, A7lite, P7
from linkerbot import Pose, ControlMode, CanInterface
from linkerbot.arm import A7, A7lite, P7, Pose, State, WayPoint, ControlMode
from linkerbot.arm.a7.motor import A7Motor, SensorType
from linkerbot.arm.p7.motor_v2 import MotorV2
from linkerbot.comm.can import CANMessageDispatcher, CanInterface
from linkerbot.exceptions import (
    LinkerbotError, TimeoutError, CANError, ValidationError, StateError,
)
```

`linkerbot.arm` 目前额外公开 `State` 和 `WayPoint`；顶层 `linkerbot` 当前不导出这两个名称。迁移时需保留这个差异，不能凭直觉扩大或缩小顶层 API。

## 三种 Arm 的共同调用面

构造函数、`close()`、上下文管理器以及以下方法必须保持签名和行为：

- 生命周期：`enable`, `disable`, `reset_error`, `emergency_stop`, `close`
- 运动：`_set_angles`, `move_j`, `move_p`, `move_l`, `home`, `is_moving`, `wait_motion_done`
- 状态：`get_state`, `get_angles`, `get_control_angles`, `get_velocities`, `get_control_velocities`, `get_control_acceleration`, `get_torques`, `get_temperatures`, `get_pose`
- 参数：`set_control_mode`, `set_velocities`, `set_accelerations`, `set_position_kps`, `set_velocity_kps`, `set_velocity_kis`
- 标定与运动学：`calibrate_zero`, `forward_kinematics`, `inverse_kinematics`, `set_joint_limits`, `get_joint_limits`

A7/P7 另有 `start_polling`, `stop_polling`, `save_params`。A7lite 不提供这三个 arm 级方法，另有 `set_velocity_filt_gains`。

## ROS2 实际依赖

代码位置：`linker_arm_ros2/linker_arm_ros2/sdk_adapter.py`、`sdk_loader.py`、`arm_factory.py`、`scripts/test_lifecycle.py`、`scripts/calibrate_arm_zero.py`。

- SDK 类实际导入：`from linkerbot import A7, A7lite, P7`。
- SDK loader 优先发现 `linkerbot-arm/src`，当前仍检查 `linkerbot/arm` 目录。
- ROS2 adapter 直接调用：`enable`, `disable`, `reset_error`, `_set_angles`, `move_j`, `home`, `emergency_stop`, `set_velocities`, `set_accelerations`, `set_position_kps`, `get_angles`, `get_velocities`, `get_torques`, `calibrate_zero`, `close`。
- 生命周期脚本调用 `_set_angles`、使能/失能、状态读取、回零和 `close`；没有直接访问 `_motors` 或 `_can_dispatcher`。
- 标定脚本导入 `linkerbot.arm.A7/A7lite` 并访问 `_motors`，同时使用标定、状态读取、使能/失能、回零和 `close`；没有直接访问 `_can_dispatcher` 或 `_set_angles`。
- `_can_dispatcher` 是 SDK 内部待补测的生命周期对象。
- 旧 `LINKERBOT_SDK_SRC` 环境变量和 `linkerbot` 源码发现逻辑必须保留一个过渡周期。

## 阶段 1 验收

- [x] 从实际源码生成类、构造函数和方法签名快照。
- [x] 记录 SDK adapter、loader、生命周期和标定脚本的实际调用。
- [x] 标记 `_set_angles`、`_motors`、`_can_dispatcher` 等内部兼容面。
- [x] 为当前实现增加快照一致性测试；原始方法签名另由 `tests/compat/upstream_api.json` 及 AST 测试固定。
- [x] 已覆盖 ValidationError 导出身份、Pose 转换、`_set_angles` 及方法默认参数。
- [ ] 补齐属性、枚举、异常层级、全部返回模型及构造/上下文管理器行为测试。

## 阶段 1 已交付记录（验收未完成）

- 分支 / Issue：`chore/phase-1-api-inventory` / `linkerbot-arm#1`
- 提交：`3ea0c77`, `9e3bd34`
- 已运行检查：`PYTHONPATH=src .venv-min/bin/python -m pytest -q tests/test_api_snapshot.py`
- 测试结果：1 passed
- 下一步：补齐主 TODO 中阶段 1 的剩余兼容门禁。
