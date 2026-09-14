# Changelog

## 0.5.4 — Independent arm distribution

- Extract A7, A7lite, P7, kinematics and six URDF resources from SDK commit
  `c6167ba`, keeping existing `linkerbot` imports and arm implementations.
- Retain shared CAN/CAN FD, exceptions, relay, queue and motion timer interfaces.
- Remove hand modules and their TOML persistence dependencies.
- Allow NumPy 1.x / SciPy versions used by ROS2; retain a `kinetix` extra for standalone installations.
- Add frozen API compatibility checks, package resource tests and migration documentation.
