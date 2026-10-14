# Installation and First Feedback

The arm SDK provides seven-joint control, state reading, and kinematics for A7, A7 Lite, P7, and H75. Install the environment and connect CAN before choosing the model. Use that model's constructor and joint limits.

## 1. Install the SDK

Follow [Installation and Environment Setup](../../INSTALLATION.md) to install the arm SDK, transport, and Pinocchio, and run the offline import checks. ROS2 users should use the matching [Humble / Jazzy environment](../../ROS2.md).

## 2. Connect the Device

All four arms use classic CAN at 1 Mbit/s. Follow [CAN Interfaces](../../zh/src/reference/can.md) to configure the adapter and check the interface and arm side. For example, read feedback from an A7 left arm:

```python
from linkerbot_arm import A7

with A7(side="left", interface_name="can0") as arm:
    feedback = arm.get_feedback()
    print(feedback.connected, feedback.oldest_received_at)
    if feedback.is_fresh(max_age_s=0.5):
        print([joint.angle for joint in feedback.joints])
```

This example does not explicitly enable or home the arm. Connecting still starts queries and model initialization; P7 may also configure PTM mode and start heartbeats. Check the physical pose before enabling motion.

## 3. Choose Device Features

<a id="models"></a>

Each model contains motion, configuration, state, and kinematics chapters. Use its own examples and limits. The detailed SDK model references below are currently in Chinese.

| Model | Main Differences |
| --- | --- |
| [A7](../../zh/src/reference/a7/README.md) | Seven V1 motors with drive-side PP position control |
| [A7 Lite](../../zh/src/reference/a7lite/README.md) | PP, MIT, CSP, and mixed control; select the API for the mode |
| [P7](../../zh/src/reference/p7/README.md) | Mixed V1 / V2 joints with host-side streamed velocity and acceleration limits |
| [H75](../../zh/src/reference/h75/README.md) | IQ24 protocol, brakes, and independent current conversion |

## 4. Further Information

- [Feedback Freshness](../../FEEDBACK.md): valid snapshots, host receive time, and timeouts.
- [Transport and Recovery](../../TRANSPORT.md): backend selection, queue backpressure, and resource cleanup.
- [Migration](../../MIGRATION.md): installation and imports when moving from the old SDK.

For ROS2 topics and services, see [ROS2 Integration](../../ROS2.md). ROS2 does not yet expose H75 or every SDK control mode.
