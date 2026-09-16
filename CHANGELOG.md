# Changelog

## 0.6.1 — Unreleased

- Add A7lite RS00 private-protocol MIT and CSP modes, per-joint mode selection,
  mixed-mode target streaming and CSP speed limits from the full SDK's #177.
- Stop each joint using its configured mode: PP/CSP zero their respective speed
  limits temporarily; MIT commands a hold at the measured position. Mode changes
  stop every motor before writing the new mode; call `enable()` afterwards.
- Validate complete angle batches before sending, including non-finite and float32-overflow targets with soft-limit checks disabled.
- Preserve existing PP signatures, `ControlMode.PP` value, ROS2 `_set_angles`
  integration, lazy kinematics loading and transport 1.0.0 compatibility.

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
