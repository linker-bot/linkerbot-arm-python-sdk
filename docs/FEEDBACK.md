# Feedback freshness

A7, A7lite and P7 expose `get_feedback()` for high frequency state publication.
It reads local caches without CAN traffic, kinematics, health queries or waiting
for a new sample. Both CANTransport and dispatcher use the same feedback path.

```python
feedback = arm.get_feedback()
if feedback.is_fresh(max_age_s=0.5):
    angles = [joint.angle for joint in feedback.joints]
    velocities = [joint.velocity for joint in feedback.joints]
    torques = [joint.torque for joint in feedback.joints]
else:
    # Do not label the cached values as a new valid observation.
    pass
```

`ArmFeedback` and `JointFeedback` can be imported from `linkerbot_arm` or
`linkerbot_arm.feedback`. Both are immutable dataclasses.

| Field / method | Meaning |
| --- | --- |
| `feedback.joints` | Seven immutable joint samples, ordered by ascending motor ID: left 61–67, right 51–57 |
| `feedback.connected` | At this read, the SDK has neither closed nor reported a CAN error; does not alone prove freshness |
| `joint.angle`, `.velocity`, `.torque` | Measured rad, rad/s and Nm; NaN until received |
| `joint.angle_received_at`, `.velocity_received_at`, `.torque_received_at` | Host `time.monotonic()` seconds at motor decoder reception; `None` until received |
| `feedback.oldest_received_at` | Minimum reception time across all fields/joints; `None` if any time is missing/nonfinite |
| `feedback.is_fresh(max_age_s, *, now=None)` | Checks connection, completeness, finite values and every field's age in `[0, max_age_s]`; `max_age_s` must be finite and positive |

By default `is_fresh` reads `time.monotonic()` when called. An explicit `now`
must use that same clock and should be read **after** obtaining the snapshot.
Obtain a new snapshot on each iteration to observe subsequent close/CAN faults;
an already returned object does not change. Failed connection cleanup still
invalidates new feedback reads immediately. Silent loss of feedback is detected
by age, without requiring the CAN backend to raise an error.

A7 and P7's first five motors receive position, velocity and torque independently.
Each field retains its own reception time. A7lite and P7's last two motors replace
all three fields atomically from one feedback frame. Across motors the snapshot
is not a simultaneous measurement. Target/configuration writes, repeat reads,
and delayed consumption by A7's polling scheduler do not refresh these times.
Even invalid numeric feedback replaces its field, so a nonfinite reply cannot
leave an earlier valid field masquerading as the latest observation.

These are **host decoder reception times**, not device sampling timestamps or
adapter hardware timestamps. CAN/driver queues, host scheduling and firmware
latency before decoder invocation cannot be inferred from them. Protocols without
transaction IDs may still deliver an indistinguishable late same-register reply.
Choose the age threshold above the slowest configured feedback period and
expected scheduling delay; 0.5 seconds is the ROS2 default, not a hardware latency
guarantee. A7's default torque period is 50 ms; P7 V2's heartbeat period is 200 ms.

`get_angles()`, `get_velocities()`, `get_torques()` and `get_state()` retain their
existing signatures and cache semantics. They do not enforce freshness and may
return old values after close. Their historical Unix `timestamp` fields are
unchanged; do not mix them with the new monotonic times. `get_state()` also
computes forward kinematics and is unnecessary for frequent joint publication.

The [ROS2 adapter](https://gitea.linkerhub.work/linker-bot/linkerbot-arm-ros2)
uses this interface, suppresses incomplete/stale state, and maps reception times
conservatively into the node's ROS clock. See its
[feedback documentation](https://gitea.linkerhub.work/linker-bot/linkerbot-arm-ros2/src/branch/main/docs/feedback.md)
for `JointState.header.stamp` semantics.
