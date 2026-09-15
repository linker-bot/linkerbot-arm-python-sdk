# Changelog

## 0.6.0 — Unreleased

- Move arm implementation to `linkerbot_arm` (phase 2, PR #3). Legacy `linkerbot.*`
  forwarding and the ROS2 loader migration remain separate tasks.
- Depend on `linkerbot-transport[can]>=1.0,<2.0` and delegate classic CAN workers
  to its low-level dispatcher. Keep the arm dispatcher import path, `send() -> None`,
  `queue.Full` / `CANError`, and best-effort shutdown behavior through a thin adapter.
- Re-export `CanInterface` from transport. Keep arm exception names and positional
  arguments while adding transport exception categories, including `DeviceStateError`.
- Retain motor frames, IDs, polling, motion control and constructor behavior. Do not
  introduce `CANTransport`, explicit `open()` or receipt waiting.
- Add motor frame, lifecycle, exception and virtual CAN regressions, a checker for
  the actual ROS2 adapter, and authenticated installation of pinned transport in CI.
- CAN FD cleanup, aggregate-package compatibility and hardware acceptance remain pending.

## 0.5.4 — Independent arm distribution

- Extract A7, A7lite, P7, kinematics and six URDF resources from SDK commit
  `c6167ba`, keeping existing `linkerbot` imports and arm implementations.
- Retain shared CAN/CAN FD, exceptions, relay, queue and motion timer interfaces.
- Remove hand modules and their TOML persistence dependencies.
- Allow NumPy 1.x / SciPy versions used by ROS2; retain a `kinetix` extra for standalone installations.
- Add frozen API compatibility checks, package resource tests and migration documentation.
