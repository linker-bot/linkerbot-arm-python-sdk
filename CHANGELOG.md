# Changelog

## 0.6.1 — Unreleased

- Clean up failed arm initialization on both CAN backends. Keep failed physical
  shutdown retryable; `close()` now reports cleanup failures instead of silently
  succeeding. Successful calls still return None and repeated close is safe.
- Preserve application exceptions if context-manager cleanup also fails.
- Add `home_cancellable(cancel_event)` for lifecycle integrations on all models.
  Stops/disable cancel motion waiting; P7 ceases new home waypoints after
  cancellation. Existing home/move_j signatures and accepted FIFO order remain
  unchanged. The caller must still issue emergency_stop or disable to stop motors.

- Identify the arm side, one-based joint number and CAN ID in startup discovery
  and missing-feedback errors for A7, A7lite and P7.
- Default A7, A7lite and P7 to CANTransport. Keep explicit
  `LINKERBOT_ARM_TRANSPORT=dispatcher` selection and existing constructors,
  control calls and direct `CANMessageDispatcher` imports. Unsetting the variable
  now restores CANTransport for newly constructed arms.
- Use one periodic worker for A7 queries and P7 queries/heartbeats, preserving
  configured intervals and A7lite unsolicited reporting. Register read waiters
  before sending so synchronous or fast responses cannot be lost.
- Atomically admit complete arm target groups and preserve target caches on
  rejection. Add opt-in target age admission/expiration and zero-I/O motion
  queue health; P7 heartbeats never revive expired or failed targets.
- Both arm CAN backends use transport FIFO batches and require the source commit
  in `requirements/transport.txt`. Public calls, FIFO ordering, 2000-frame
  capacity and successful-send pacing remain compatible; no release is implied.

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
