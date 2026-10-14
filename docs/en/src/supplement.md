# Further Information

After connecting and reading initial feedback, consult the runtime and migration references as needed. These rules are shared across models; use the model reference for control modes and units.

- [Feedback Freshness](../../FEEDBACK.md): snapshot completeness, monotonic receive times, caches, and device sampling time. Reading a cache does not guarantee a new device sample.
- [Transport and Recovery](../../TRANSPORT.md): default CANTransport, optional dispatcher, batch admission, backpressure, initialization failures, and cleanup retries. Queue admission does not mean motion has completed.
- [Migration](../../MIGRATION.md): standalone SDK package names, imports, and dependency installation.
- [ROS2 Integration](../../ROS2.md): Python, Pinocchio, and numerical libraries for Humble and Jazzy. Use separate environments for each distribution.

When changing backends or recovering from a bus fault, stop target production and close the old connection. Then check state, configure modes, and enable according to your application. The SDK does not automatically replay motion from before the fault.

[Back to quick start](quick_start.md)
