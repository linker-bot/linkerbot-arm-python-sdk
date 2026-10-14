import functools
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

import numpy as np
from scipy.spatial.transform import Rotation as R

from linkerbot_arm._transport import arm_dispatcher, close_arm, exit_arm
from linkerbot_arm._transport.targets import ArmMotionQueueMixin, submit_targets
from linkerbot_arm.arm.a7.consts import (
    DEFAULT_POLL_INTERVALS,
    MAX_ACCELERATION,
    MAX_VELOCITY,
    MIN_ACCELERATION,
    MIN_VELOCITY,
    MOVE_L_DEFAULT_ACCELERATION,
    MOVE_L_DEFAULT_ANGULAR_ACCELERATION,
    MOVE_L_DEFAULT_MAX_ANGULAR_VELOCITY,
    MOVE_L_DEFAULT_MAX_VELOCITY,
    MOVE_L_MAX_ACCELERATION,
    MOVE_L_MAX_ANGULAR_ACCELERATION,
    MOVE_L_MAX_MAX_ANGULAR_VELOCITY,
    MOVE_L_MAX_MAX_VELOCITY,
    NUM_JOINTS,
)
from linkerbot_arm.arm.common import ControlMode, Pose, State
from linkerbot_arm.arm.common._diagnostics import describe_motor
from linkerbot_arm.arm.common._discovery import check_motors
from linkerbot_arm.arm.common._lifecycle import disable_motors
from linkerbot_arm.arm.common._motion import (
    joint_duration,
    point_duration,
    trapezoidal_duration,
    validate_target,
)
from linkerbot_arm.arm.common._stream import plan_linear, stream_targets
from linkerbot_arm.comm import CanInterface, CANMessageDispatcher
from linkerbot_arm.exceptions import StateError, ValidationError
from linkerbot_arm.feedback import ArmFeedback, read_feedback
from linkerbot_arm.motion_timer import CancellableHomeMixin, MotionTimer

from .motor import A7Motor, SensorType


def _guard_not_moving(method):
    @functools.wraps(method)
    def wrapper(self: "A7", *args, **kwargs):
        if self.is_moving():
            raise StateError("Cannot start new motion while arm is moving.")
        return method(self, *args, **kwargs)

    return wrapper


class A7(ArmMotionQueueMixin, CancellableHomeMixin):
    def __init__(
        self,
        side: Literal["left", "right"],
        interface_name: str,
        interface_type: str = "socketcan",
        tcp_offset: list[float] = [0.0, 0.0, 0.0],
        world_frame: Literal["urdf", "maestro"] = "urdf",
    ) -> None:
        if side not in ("left", "right"):
            raise ValueError(f"side must be 'left' or 'right', got {side!r}")
        if world_frame not in ("urdf", "maestro"):
            raise ValueError(
                f"world_frame must be 'urdf' or 'maestro', got {world_frame!r}"
            )
        with arm_dispatcher(
            self, "a7", side, interface_name, interface_type, CANMessageDispatcher
        ) as self._can_dispatcher:
            self._motors = [
                A7Motor(id, self._can_dispatcher)
                for id in (range(61, 68) if side == "left" else range(51, 58))
            ]
            from linkerbot_arm.arm.kinetix import ArmKinetix

            self._kx: ArmKinetix = ArmKinetix.from_builtin(
                "a7", side, tcp_offset=tcp_offset, world_frame=world_frame
            )
            self._control_mode: ControlMode | None = None
            self._motion_timer = MotionTimer()
            self._closed: bool = False
            self._polling: bool = False
            self._check_motors()
            for motor in self._motors:
                motor.read_initial_state()
            for motor in self._motors:
                if not motor.has_initial_data():
                    raise StateError(
                        f"{describe_motor(motor._id)} did not report initial data."
                    )
            self.start_polling()

    def _check_motors(self) -> None:
        check_motors(self._motors)

    def _on_bus_error(self, error: Exception) -> None:
        self._bus_error = error
        self._closed = True

    @property
    def can_interface(self) -> CanInterface:
        """CAN interface this arm is bound to."""
        return self._can_dispatcher.can_interface

    def start_polling(self, intervals: dict[SensorType, float] | None = None) -> None:
        if self._polling:
            self.stop_polling()
        poll_intervals = intervals if intervals is not None else DEFAULT_POLL_INTERVALS
        for motor in self._motors:
            motor.start_polling(poll_intervals)
        self._polling = True

    def stop_polling(self) -> None:
        for motor in self._motors:
            motor.stop_polling()
        self._polling = False

    def is_moving(self) -> bool:
        return self._motion_timer.is_moving()

    def wait_motion_done(self) -> None:
        self._motion_timer.wait_done()

    def set_control_mode(self, mode: ControlMode) -> None:
        for motor in self._motors:
            motor.set_control_mode(mode)
        self._control_mode = mode

    def enable(self) -> None:
        self.reset_error()
        control_mode = (
            self._control_mode if self._control_mode is not None else ControlMode.PP
        )
        self.set_control_mode(control_mode)
        for motor in self._motors:
            motor.enable()

        time.sleep(0.1)

    def disable(self) -> None:
        with self._motion_timer._lock:
            self._motion_timer.cancel()
            disable_motors(self._motors)

    def reset_error(self) -> None:
        for motor in self._motors:
            motor.reset_error()

    def emergency_stop(self) -> None:
        with self._motion_timer._lock:
            self._motion_timer.cancel()

            def stop_single(motor):
                angle = motor._read_register_float(SensorType.POSITION)
                motor.set_angle(angle)

            with ThreadPoolExecutor(max_workers=len(self._motors)) as pool:
                futures = [pool.submit(stop_single, m) for m in self._motors]
                for f in as_completed(futures):
                    f.result()

    def _set_angles(self, angles: list[float], *, check_limits: bool = True) -> None:
        with self._motion_timer._lock:
            if getattr(self, "_closed", False) or (
                getattr(self, "_closing", False)
                and not self._motion_timer._is_worker_thread()
            ):
                raise StateError("A7 connection is closed or closing")
            validate_target(self, angles, check_limits=check_limits)
            submit_targets(
                motor._prepare_angle(angle)
                for motor, angle in zip(self._motors, angles)
            )

    def set_velocities(self, velocities: list[float]) -> None:
        if len(velocities) != len(self._motors):
            raise ValueError(
                f"Velocities count must be {NUM_JOINTS}, got {len(velocities)}"
            )
        for i, v in enumerate(velocities):
            if not (MIN_VELOCITY <= v <= MAX_VELOCITY):
                raise ValidationError(
                    f"Joint {i} velocity {v} out of range [{MIN_VELOCITY}, {MAX_VELOCITY}]"
                )
        for motor, velocity in zip(self._motors, velocities):
            motor.set_velocity(velocity)

    def set_accelerations(self, accelerations: list[float]) -> None:
        if len(accelerations) != len(self._motors):
            raise ValueError(
                f"Accelerations count must be {NUM_JOINTS}, got {len(accelerations)}"
            )
        for i, a in enumerate(accelerations):
            if not (MIN_ACCELERATION <= a <= MAX_ACCELERATION):
                raise ValidationError(
                    f"Joint {i} acceleration {a} out of range [{MIN_ACCELERATION}, {MAX_ACCELERATION}]"
                )
        for motor, acceleration in zip(self._motors, accelerations):
            motor.set_acceleration(acceleration)
            motor.set_deceleration(acceleration)

    def get_feedback(self) -> ArmFeedback:
        """Read cached measured joints with monotonic reception times, without I/O."""
        return read_feedback(self)

    def get_state(self) -> State:
        return State(
            pose=self.get_pose(),
            joint_angles=[motor.angle for motor in self._motors],
            joint_control_angles=[motor.control_angle for motor in self._motors],
            joint_velocities=[motor.velocity for motor in self._motors],
            joint_control_velocities=[motor.control_velocity for motor in self._motors],
            joint_control_acceleration=[
                motor.control_acceleration for motor in self._motors
            ],
            joint_torques=[motor.torque for motor in self._motors],
            joint_temperatures=[motor.temperature for motor in self._motors],
        )

    def get_angles(self) -> list[float]:
        return [motor.angle.angle for motor in self._motors]

    def get_control_angles(self) -> list[float]:
        return [motor.control_angle.angle for motor in self._motors]

    def get_velocities(self) -> list[float]:
        return [motor.velocity.velocity for motor in self._motors]

    def get_control_velocities(self) -> list[float]:
        return [motor.control_velocity.velocity for motor in self._motors]

    def get_control_acceleration(self) -> list[float]:
        return [motor.control_acceleration.acceleration for motor in self._motors]

    def get_torques(self) -> list[float]:
        return [motor.torque.torque for motor in self._motors]

    def get_temperatures(self) -> list[float]:
        return [motor.temperature.temperature for motor in self._motors]

    def get_pose(self) -> Pose:
        return self._kx.forward_kinematics(self.get_angles())

    def home(self, *, blocking: bool = True) -> None:
        self.move_j([0.0] * NUM_JOINTS, blocking=blocking)

    @_guard_not_moving
    def move_j(
        self,
        target_joints: list[float],
        *,
        blocking: bool = True,
    ) -> None:
        validate_target(self, target_joints)
        self._motion_timer._start_with_target(
            lambda: point_duration(self, target_joints),
            lambda: self._set_angles(target_joints),
        )
        if blocking:
            self.wait_motion_done()

    @_guard_not_moving
    def move_p(
        self,
        target_pose: Pose,
        *,
        current_angles: list[float] | None = None,
        blocking: bool = True,
    ) -> None:
        def plan():
            angles = self.get_angles() if current_angles is None else current_angles
            target = self.inverse_kinematics(target_pose, current_angles=angles)
            validate_target(self, target)
            return target

        self._motion_timer._plan_and_start(
            plan,
            lambda target: point_duration(self, target),
            lambda target: self._set_angles(target, check_limits=False),
        )
        if blocking:
            self.wait_motion_done()

    @_guard_not_moving
    def move_l(
        self,
        target_pose: Pose,
        *,
        max_velocity: float = MOVE_L_DEFAULT_MAX_VELOCITY,
        max_angular_velocity: float = MOVE_L_DEFAULT_MAX_ANGULAR_VELOCITY,
        acceleration: float = MOVE_L_DEFAULT_ACCELERATION,
        angular_acceleration: float = MOVE_L_DEFAULT_ANGULAR_ACCELERATION,
        current_pose: Pose | None = None,
        current_angles: list[float] | None = None,
    ) -> None:
        if not (0 < max_velocity <= MOVE_L_MAX_MAX_VELOCITY):
            raise ValidationError(
                f"max_velocity {max_velocity} out of range (0, {MOVE_L_MAX_MAX_VELOCITY}]"
            )
        if not (0 < max_angular_velocity <= MOVE_L_MAX_MAX_ANGULAR_VELOCITY):
            raise ValidationError(
                f"max_angular_velocity {max_angular_velocity} out of range (0, {MOVE_L_MAX_MAX_ANGULAR_VELOCITY}]"
            )
        if not (0 < acceleration <= MOVE_L_MAX_ACCELERATION):
            raise ValidationError(
                f"acceleration {acceleration} out of range (0, {MOVE_L_MAX_ACCELERATION}]"
            )
        if not (0 < angular_acceleration <= MOVE_L_MAX_ANGULAR_ACCELERATION):
            raise ValidationError(
                f"angular_acceleration {angular_acceleration} out of range (0, {MOVE_L_MAX_ANGULAR_ACCELERATION}]"
            )

        with self._motion_timer._stream_scope() as active:
            if not active:
                return
            if current_angles is not None and current_pose is not None:
                fk_pose = self._kx.forward_kinematics(current_angles)
                if not self._poses_close(fk_pose, current_pose):
                    warnings.warn(
                        "current_pose does not match FK(current_angles). "
                        "Using FK result instead.",
                        stacklevel=2,
                    )
                    current_pose = fk_pose
            elif current_angles is not None:
                current_pose = self._kx.forward_kinematics(current_angles)
            elif current_pose is not None:
                raise ValueError(
                    "current_angles must be provided when current_pose is specified."
                )
            else:
                current_angles = self.get_angles()
                current_pose = self._kx.forward_kinematics(current_angles)

            waypoints = plan_linear(
                self,
                current_pose,
                current_angles,
                target_pose,
                max_velocity=max_velocity,
                acceleration=acceleration,
                max_angular_velocity=max_angular_velocity,
                angular_acceleration=angular_acceleration,
            )
            if waypoints:
                stream_targets(
                    self,
                    waypoints,
                    max_velocity=MAX_VELOCITY,
                    max_acceleration=MAX_ACCELERATION,
                )

    def set_position_kps(self, kps: list[float]) -> None:
        if len(kps) != len(self._motors):
            raise ValueError(f"KPS count must be {NUM_JOINTS}, got {len(kps)}")
        for motor, kp in zip(self._motors, kps):
            motor.set_position_kp(kp)

    def set_velocity_kps(self, kps: list[float]) -> None:
        if len(kps) != len(self._motors):
            raise ValueError(f"KPS count must be {NUM_JOINTS}, got {len(kps)}")
        for motor, kp in zip(self._motors, kps):
            motor.set_velocity_kp(kp)

    def set_velocity_kis(self, kis: list[float]) -> None:
        if len(kis) != len(self._motors):
            raise ValueError(f"KIS count must be {NUM_JOINTS}, got {len(kis)}")
        for motor, ki in zip(self._motors, kis):
            motor.set_velocity_ki(ki)

    def calibrate_zero(self) -> None:
        self.reset_error()
        for motor in self._motors:
            motor.calibrate_zero()

    def forward_kinematics(self, angles: list[float]) -> Pose:
        return self._kx.forward_kinematics(angles)

    def inverse_kinematics(
        self,
        pose: Pose,
        *,
        current_angles: list[float] | None = None,
    ) -> list[float]:
        current_angles = (
            current_angles if current_angles is not None else self.get_angles()
        )
        return self._kx.inverse_kinematics(pose, current_angles=current_angles)

    def set_joint_limits(self, limits: list[tuple[float, float]]) -> None:
        self._kx.set_joint_limits(limits)

    def get_joint_limits(self) -> list[tuple[float, float]]:
        return self._kx.get_joint_limits()

    def close(self) -> None:
        """Release CAN resources; failures are raised and close may be retried."""
        close_arm(self)

    def __enter__(self) -> "A7":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return exit_arm(self, exc_val)

    @staticmethod
    def _poses_close(
        a: Pose, b: Pose, pos_tol: float = 1e-3, rot_tol: float = 1e-2
    ) -> bool:
        pos_diff = np.linalg.norm(np.array([a.x, a.y, a.z]) - np.array([b.x, b.y, b.z]))
        rot_a = R.from_euler("zyx", [a.rz, a.ry, a.rx])
        rot_b = R.from_euler("zyx", [b.rz, b.ry, b.rx])
        rot_diff = (rot_a.inv() * rot_b).magnitude()
        return bool(pos_diff < pos_tol and rot_diff < rot_tol)

    @staticmethod
    def _trapezoidal_duration(
        distance: float, speed: float, acceleration: float
    ) -> float:
        return trapezoidal_duration(distance, speed, acceleration)

    def _move_duration(
        self,
        current_angles: list[float],
        target_angles: list[float],
        control_speeds: list[float],
        control_accelerations: list[float],
    ) -> float:
        return joint_duration(
            current_angles, target_angles, control_speeds, control_accelerations
        )

    def save_params(self) -> None:
        for motor in self._motors:
            motor._save_params()
