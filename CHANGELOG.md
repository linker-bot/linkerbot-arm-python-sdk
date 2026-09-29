# Changelog

## 0.6.1 — Unreleased

- Port the P7 PTM control fix from linkerbot-python-sdk 6f6da6b: use 16/12-bit
  packed position, velocity, Kp, Kd and torque frames on joints 6/7, with default
  Kp=4, Kd=15 and zero feedforward. V2 velocity-loop gain setters are now no-ops;
  profile velocity remains a host planning value rather than PTM feedforward.
- Ensure V2 Flash Control Mode 0x02 before feedback initialization and heartbeats.
  Skip writes when already PTM; otherwise enter Rest, write/save and verify the
  mode. Failures propagate through existing connection cleanup. Reverting Python
  code alone does not restore the old motor mode; see docs/MIGRATION.md.
- Keep atomic target admission, heartbeat ordering, indexed Flash replies,
  periodic scheduling and cancellation. Replace the private Servo encoder with
  the PTM encoder; public arm call signatures remain compatible.
- Add the five-page Chinese P7 reference based on upstream f616481, adapted to
  linkerbot_arm and its actual motion, state, coordinate and persistence behavior.

- Read A7 profile velocity from 0x1C separately from measured velocity (0x05),
  including P7's first five joints. Validate nonzero-motion timing parameters
  before admitting targets; zero/unknown/non-finite profiles now raise StateError.
  Rejected A7/A7lite profile writes no longer update accepted-value caches.
- Finish and validate all three models' linear plans before temporary parameter
  changes or execution. Share ordered streaming with P7 move_j: wait at least
  10 ms between submissions, stretch time on delays, and never catch up in bursts.
  Keep motion busy through streaming and cleanup, and stop new targets on cancel.
- Attempt both parameter restores on failure, preserve the original exception,
  and serialize cleanup with stop/disable so it cannot interrupt A7lite's zero-speed
  hold. Motion return values still do not prove physical arrival.
- Match A7lite register replies and P7 V2 Flash replies by address/index; reject
  malformed frames before completing a read. Same-address reads remain serialized;
  the wire protocol cannot distinguish a late reply to the same address.
- Share bounded read-only startup probing across all three models: 100 ms first
  attempt, 200 ms retry for missing joints only, 2.5 s total discovery budget.
  Keep public motor timeout defaults and include joint IDs/attempts in failures.
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
