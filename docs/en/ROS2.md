# ROS2 Integration

[linkerbot-arm-ros2-sdk](https://github.com/linker-bot/linkerbot-arm-ros2-sdk) connects `linkerbot_arm` to ROS2 for A7, A7 Lite, and P7. The ROS2 package remains `linker_arm_ros2`; the hand SDK and old aggregate SDK are unnecessary.

## Installation and Environment

| Operating system | ROS2 | Python |
| --- | --- | --- |
| Ubuntu 22.04 | Humble | 3.10 |
| Ubuntu 24.04 | Jazzy | 3.12 |

Use the distribution's system Python, APT Pinocchio, and a venv with system packages. The ROS2 repository provides `constraints/ros-humble.txt` and `constraints/ros-jazzy.txt`, both using NumPy 1.26.4 and SciPy 1.13.1. Do not reuse another distribution's environment or build outputs.

See the ROS2 [installation guide](https://github.com/linker-bot/linkerbot-arm-ros2-sdk/blob/main/docs/en/INSTALLATION.md) for complete installation, or the [English developer preview](https://doc.linkerhub.work/sdk-doc/#/linkerbot-arm-ros2/docs/environment_setup.md?lang=en). Install the paired SDK commit selected by ROS2's `requirements/source-versions.txt`. Transport installs from current `main` without a version, tag, or old-commit constraint.

With APT Pinocchio, install the base SDK without `[kinetix]`. APT provides the `pinocchio` module without PyPI `pin` distribution metadata. SDK construction requires Pinocchio even for joint-only control. The SDK's generic `constraints/ros2.txt` does not replace ROS2's distribution-specific profiles.

## Interpreter and SDK Source

Activate the ROS venv, build with its Python, and inspect the generated node's interpreter:

```bash
python /usr/bin/colcon build --packages-select linker_arm_ros2 --symlink-install
head -n 1 install/linker_arm_ros2/lib/linker_arm_ros2/arm_node
python -c "import sys, linkerbot_arm; print(sys.executable, linkerbot_arm.__file__)"
```

The loader first uses importable `linkerbot_arm`, then checks `LINKERBOT_ARM_SRC`, deprecated `LINKERBOT_SDK_SRC`, and nearby directories named `linkerbot-arm`. Install a renamed `linkerbot-arm-python-sdk` checkout or specify:

```bash
export LINKERBOT_ARM_SRC=/absolute/path/to/linkerbot-arm-python-sdk/src
```

The repository root is also accepted, but source variables do not override an importable SDK. Restart after changing the source. The loader does not use the old aggregate `linkerbot` namespace. The node checks `home_cancellable` and `get_feedback` before opening CAN.

`CANTransport` is the default backend. Set `LINKERBOT_ARM_TRANSPORT=dispatcher` before starting a new node to select the low-level dispatcher. See [Communication Backends](../TRANSPORT.md). This affects only new instances and does not automatically restore motion after faults.

## Calls and Responses

- Streaming targets follow `ArmNode → LinkerBotSDKAdapter.set_angles → SDK._set_angles`, preserving PP control and the `None` return value. Success means queue admission, not motor execution.
- Enable, disable, speed, and mode configuration wait for physical send receipts and propagate failure. A receipt means the backend accepted the send, not that the motor executed it.
- ROS2 configures speed in a lifecycle worker, retains the latest valid pending target, and drops stale targets without blocking the single-threaded executor.
- P7 streaming applies SDK velocity/acceleration limits. The first frame holds measured position and repeated input is required. External targets are rejected during SDK host trajectories.
- A7 Lite software stop remains latched until explicit enabling or successful homing; it does not recover automatically after two seconds.

While ordinary lifecycle tasks are busy, other ordinary services fail and streamed targets are not admitted. Stop services can cancel work and clear pending targets; the original request fails. Stop response time still depends on SDK calls and worker exit. During speed configuration, only the latest valid target is retained.

## Cancellable Homing

A task thread calls `home_cancellable(cancel_event: threading.Event) -> None`. The stopping caller sets the event, calls `emergency_stop()` or `disable()`, then waits for the task to exit. The event alone cancels software waits and new target submission; it does not send hardware stop commands or retract frames already admitted to FIFO.

Existing `home(blocking=...)` and `move_j(..., blocking=...)` remain compatible. P7's `blocking=False` still sends the full host trajectory synchronously, skipping only the final wait. Software stop does not replace a hardware emergency stop.

## Feedback and Checks

ROS2 uses `get_feedback()` to validate position, velocity, and torque across seven joints. Missing, non-finite, or stale fields, SDK closure, or a bus fault pause JointState. Publication resumes with complete fresh feedback. The pause itself does not send stop or disable commands.

The SDK retains original host reception times, so repeated caches do not refresh age. ROS2 conservatively maps the oldest published field to its timestamp; this is not synchronized hardware sampling time. `get_angles()` / `get_velocities()` / `get_torques()` remain cached array interfaces without freshness guarantees. See [Feedback API](../FEEDBACK.md).

The ROS2 environment script verifies ROS imports, SDK capabilities, and all six URDF FKs without constructing a device or opening CAN:

```bash
python /path/to/linkerbot-arm-ros2/scripts/check_ros_environment.py
python -m pip check
```

## Integration Scope

The current ROS2 adapter does not support H75 or expose MIT/CSP topics or services. Standalone calibration and lifecycle tools support only A7 / A7 Lite. Humble/Jazzy Docker checks do not replace real CAN, motion, stopping, or calibration validation.
