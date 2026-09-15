# Changelog

## 0.6.0 — Unreleased

- Import the SDK through `linkerbot_arm`. This distribution does not provide the old
  `linkerbot.*` paths; see the [migration guide](docs/MIGRATION.md).
- Require `linkerbot-transport[can]==1.0.0` for CAN communication.
- Share CAN FD I/O and vendor-library ownership with transport, retaining arm's
  existing imports, message models, `Future[None]` receipts and close behavior.
- Keep arm dispatcher calls compatible: `send()` returns `None`, queue overflow raises
  `queue.Full`, and sending after a bus fault raises the arm `CANError`.
- Re-export `CanInterface` from transport. Arm exception names and positional arguments
  remain available and also match the corresponding transport exception categories.

## 0.5.4 — Independent arm distribution

- Provide A7, A7lite, P7, kinematics and six URDF resources as a standalone arm SDK,
  retaining the original `linkerbot` imports in this version.
- Retain shared CAN/CAN FD, exceptions, relay, queue and motion timer interfaces.
- Remove hand modules and their TOML persistence dependencies.
- Support NumPy 1.x / SciPy versions used by ROS2 and a `kinetix` extra for standalone installations.
