# 维护约定

- 保持线性历史：功能分支基于最新 `origin/master` 开发，同步主分支使用 rebase，不创建 merge commit。PR 合并使用 squash、rebase 或 fast-forward；变基后的分支使用带明确远程旧提交校验的 `--force-with-lease` 推送。
- arm 功能在本仓库维护，ROS2 消息/服务/启动配置在 `linker_arm_ros2` 维护。
- 公共导入路径和已有函数调用保持兼容，包括现有集成使用的 `_set_angles` 与 motor 接口。
- 新增功能优先用新方法或可选参数；修改已有签名前应提供明确迁移方案，不能直接重新生成基线掩盖破坏性变更。
- `tests/compat/upstream_api.json` 固定初始来源。`tools/check_upstream.py` 用于确认初次提取，
  后续有意修改实现后它可能报告差异；日常兼容性门禁使用 pytest 中的 API 测试。
- 共享通信代码与完整 SDK 的修复通过独立 commit 审阅、回归和按需移植，不自动复制覆盖。

```bash
python -m pip install -e '.[kinetix,test,dev]'
python -m pytest
python -m build
```

测试默认排除硬件和交互用例。需要实际机械臂时，明确指定型号、CAN 和 marker，例如：

```bash
CAN_INTERFACE=can0 ARM_SIDE=left python -m pytest tests/arm/a7 -m 'hardware and not interactive'
```

修改打包或 URDF 后，必须在源码目录之外安装 wheel 验证导入和六个模型的加载。
修改 ROS2 接入后，在安装新 SDK 的环境运行 ROS2 仓库 `tests/`；带 rclpy 的环境会额外运行真实节点测试。
发布前记录 Python、NumPy、SciPy、Pinocchio 版本以及真机验收结果，并更新 CHANGELOG。
