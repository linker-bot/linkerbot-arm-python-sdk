import functools
import logging
import threading
import time
import warnings
from dataclasses import asdict
from typing import Literal

import numpy as np
from scipy.spatial.transform import Rotation as R

from linkerbot_arm._transport import (
    _finish_cancelled_worker,
    arm_dispatcher,
    close_arm,
    exit_arm,
)
from linkerbot_arm._transport.targets import ArmMotionQueueMixin, submit_targets
from linkerbot_arm.arm.common import ControlMode, Pose, State
from linkerbot_arm.arm.common._diagnostics import describe_motor
from linkerbot_arm.arm.common._discovery import check_motors
from linkerbot_arm.arm.common._motion import (
    joint_duration,
    point_duration,
    trapezoidal_duration,
    validate_target,
)
from linkerbot_arm.arm.common._stream import plan_linear, stream_targets
from linkerbot_arm.arm.h75.consts import (
    BRAKE_JOINT_INDICES,
    DEFAULT_POLL_INTERVALS,
    MIN_ACCELERATION,
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
from linkerbot_arm.comm import CanInterface, CANMessageDispatcher
from linkerbot_arm.exceptions import StateError, ValidationError
from linkerbot_arm.motion_timer import CancellableHomeMixin, MotionTimer

from .model import CurrentState, H75MotorConfig
from .motor import H75Motor, SensorType

logger = logging.getLogger(__name__)


def _guard_not_moving(method):
    @functools.wraps(method)
    def wrapper(self: "H75", *args, **kwargs):
        if self.is_moving():
            raise StateError("Cannot start new motion while arm is moving.")
        return method(self, *args, **kwargs)

    return wrapper


class H75(ArmMotionQueueMixin, CancellableHomeMixin):
    """Seven-joint Weiyi arm, adapted from upstream 9041b05.

    PP uses the drive's S-curve position mode (0x06); CSP uses ordinary
    position mode (0x03). Only joints 1/2 have brakes. Torque is unavailable;
    use get_currents() for amperes. Motion completion is an estimate, not
    feedback-confirmed arrival.
    """

    def __init__(
        self,
        side: Literal["left", "right"],
        interface_name: str,
        interface_type: str = "socketcan",
        tcp_offset: list[float] = [0.0, 0.0, 0.0],
        world_frame: Literal["urdf", "maestro"] = "urdf",
        *,
        motor_configs: list[H75MotorConfig] | None = None,
    ) -> None:
        if side not in ("left", "right"):
            raise ValueError(f"side must be 'left' or 'right', got {side!r}")
        if world_frame not in ("urdf", "maestro"):
            raise ValueError(
                f"world_frame must be 'urdf' or 'maestro', got {world_frame!r}"
            )
        configs = (
            list(motor_configs)
            if motor_configs is not None
            else [H75MotorConfig()] * NUM_JOINTS
        )
        if len(configs) != NUM_JOINTS or any(
            not isinstance(c, H75MotorConfig) for c in configs
        ):
            raise ValidationError(
                "motor_configs must contain seven H75MotorConfig values"
            )
        self._closing = False
        self._close_lock = threading.Lock()
        with arm_dispatcher(
            self, "h75", side, interface_name, interface_type, CANMessageDispatcher
        ) as self._can_dispatcher:
            self._motors = [
                H75Motor(mid, self._can_dispatcher, **asdict(config))
                for mid, config in zip(
                    range(61, 68) if side == "left" else range(51, 58), configs
                )
            ]
            from linkerbot_arm.arm.kinetix import ArmKinetix

            self._kx: ArmKinetix = ArmKinetix.from_builtin(
                "h75", side, tcp_offset=tcp_offset, world_frame=world_frame
            )
            self._control_mode: ControlMode | None = None
            self._motion_timer = MotionTimer()
            # Standalone motors use their own lock. Within an arm, share the
            # admission lock so low-level writes and whole-arm snapshots agree.
            for motor in self._motors:
                motor._parameter_lock = self._motion_timer._lock
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

    def _require_connection(self, *, allow_closing=False) -> None:
        if self._closed:
            raise StateError(
                "H75 connection is closed; close it and construct a new arm"
            )
        if (
            getattr(self, "_closing", False)
            and not allow_closing
            and not self._motion_timer._is_worker_thread()
        ):
            raise StateError("H75 connection is closing; new commands are unavailable")

    def _require_pp(self) -> None:
        self._require_connection()
        if self._control_mode != ControlMode.PP:
            raise StateError(
                "H75 home/move_j/move_p require PP; disable, select PP and enable first"
            )

    def set_control_mode(self, mode: ControlMode) -> None:
        with self._motion_timer._lock:
            self._require_connection()
            if mode not in (ControlMode.PP, ControlMode.CSP):
                raise ValidationError("H75 supports PP and CSP only")
            if self.is_moving() or any(m.enabled for m in self._motors):
                raise StateError("Disable H75 before changing control mode")
            self._control_mode = None  # a partial write must never look complete
            for motor in self._motors:
                motor.set_control_mode(mode)
            self._control_mode = mode

    def enable(self) -> None:
        with self._motion_timer._lock:
            self._require_connection()
            if self.is_moving():
                raise StateError("Cannot enable H75 during motion")
            mode = self._control_mode or ControlMode.PP
            try:
                if any(m.enabled for m in self._motors):
                    self.disable()
                self.reset_error()
                self.set_control_mode(mode)
                for motor in self._motors:
                    motor.enable()
                for i in BRAKE_JOINT_INDICES:
                    self._motors[i].release_brake()
                time.sleep(0.1)
                self._require_connection()
            except BaseException:
                self._control_mode = None
                try:
                    self.disable()
                except BaseException:
                    logger.exception(
                        "H75 enable cleanup failed; check brakes and motor state"
                    )
                raise

    def disable(self) -> None:
        with self._motion_timer._lock:
            self._motion_timer.cancel()
            errors = []
            failed_brakes = set()
            for i in BRAKE_JOINT_INDICES:
                try:
                    self._motors[i].lock_brake()
                except BaseException as error:
                    failed_brakes.add(i)
                    errors.append(error)
                    logger.error(
                        "H75 joint %d brake failed; skipping its disable: %s",
                        i + 1,
                        error,
                    )
            for i, motor in enumerate(self._motors):
                if i in failed_brakes:
                    continue
                try:
                    motor.disable()
                except BaseException as error:
                    errors.append(error)
                    logger.error("H75 joint %d disable failed: %s", i + 1, error)
            if errors:
                raise errors[0]

    def reset_error(self) -> None:
        self._require_connection()
        for motor in self._motors:
            motor.reset_error()

    def emergency_stop(self) -> None:
        with self._motion_timer._lock:
            self._motion_timer.cancel()
            self._submit_angles(
                self.get_angles(),
                check_limits=False,
                enforce_age=False,
                allow_closing=True,
            )

    def _set_angles(self, angles: list[float], *, check_limits: bool = True) -> None:
        with self._motion_timer._lock:
            self._submit_angles(angles, check_limits=check_limits)

    def _submit_angles(
        self, angles, *, check_limits=True, enforce_age=True, allow_closing=False
    ):
        """Submit while holding the motion lock; stops bypass only target age."""
        self._require_connection(allow_closing=allow_closing)
        if self._control_mode is None:
            raise StateError(
                "H75 control mode is unknown; select a mode before sending targets"
            )
        validate_target(self, angles, check_limits=check_limits)
        submit_targets(
            (m._prepare_angle(a) for m, a in zip(self._motors, angles)),
            enforce_age=enforce_age,
        )

    def _require_parameter_write(self):
        self._require_connection()
        if self.is_moving() and not self._motion_timer._is_worker_thread():
            raise StateError(
                "Cannot change H75 parameters during active motion; stop it first"
            )

    def _validate_profiles(self, values: list[float], *, velocity: bool) -> None:
        self._require_parameter_write()
        if len(values) != NUM_JOINTS:
            raise ValueError(f"Expected {NUM_JOINTS} profile values, got {len(values)}")
        for motor, value in zip(self._motors, values):
            motor._encode_profile(value, velocity=velocity)

    def set_velocities(self, velocities: list[float]) -> None:
        with self._motion_timer._lock:
            self._validate_profiles(velocities, velocity=True)
            for motor, value in zip(self._motors, velocities):
                motor.set_velocity(value)

    def set_accelerations(self, accelerations: list[float]) -> None:
        with self._motion_timer._lock:
            self._validate_profiles(accelerations, velocity=False)
            for motor, value in zip(self._motors, accelerations):
                motor.set_acceleration(value)
                motor.set_deceleration(value)

    def set_decelerations(self, decelerations: list[float]) -> None:
        with self._motion_timer._lock:
            self._validate_profiles(decelerations, velocity=False)
            for motor, value in zip(self._motors, decelerations):
                motor.set_deceleration(value)

    def get_control_decelerations(self) -> list[float]:
        with self._motion_timer._lock:
            return [motor.control_deceleration.acceleration for motor in self._motors]

    def get_currents(self) -> list[float]:
        return [motor.current.current for motor in self._motors]

    def get_current_states(self) -> list[CurrentState]:
        return [motor.current for motor in self._motors]

    def get_state(self) -> State:
        return State(
            pose=self.get_pose(),
            joint_angles=[motor.angle for motor in self._motors],
            joint_control_angles=[motor.control_angle for motor in self._motors],
            joint_velocities=[motor.velocity for motor in self._motors],
            joint_control_velocities=(
                [motor.control_velocity for motor in self._motors]
                if all(m._control_velocity is not None for m in self._motors)
                else []
            ),
            joint_control_acceleration=[
                motor.control_acceleration for motor in self._motors
            ],
            joint_torques=None,
            joint_temperatures=[motor.temperature for motor in self._motors],
        )

    def get_angles(self) -> list[float]:
        return [motor.angle.angle for motor in self._motors]

    def get_control_angles(self) -> list[float]:
        return [motor.control_angle.angle for motor in self._motors]

    def get_velocities(self) -> list[float]:
        return [motor.velocity.velocity for motor in self._motors]

    def get_control_velocities(self) -> list[float]:
        with self._motion_timer._lock:
            return [motor.control_velocity.velocity for motor in self._motors]

    def get_control_acceleration(self) -> list[float]:
        with self._motion_timer._lock:
            return [motor.control_acceleration.acceleration for motor in self._motors]

    def get_torques(self) -> list[float]:
        raise StateError(
            "H75 torque conversion is unavailable; use get_currents() for amperes"
        )

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
        self._require_pp()
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
        self._require_pp()

        def plan():
            angles = self.get_angles() if current_angles is None else current_angles
            target = self.inverse_kinematics(target_pose, current_angles=angles)
            validate_target(self, target)
            return target

        self._motion_timer._plan_and_start(
            plan,
            lambda target: point_duration(self, target),
            lambda target: self._set_angles(target, check_limits=False),
            guard=self._require_pp,
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

        self._require_connection()
        if self._control_mode is None:
            raise StateError("Select an H75 control mode before motion")
        with self._motion_timer._stream_scope(guard=self._require_connection) as active:
            if not active:
                return
            self._require_connection()
            if self._control_mode is None:
                raise StateError("Select an H75 control mode before motion")
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
                    max_velocity=[m.config.max_velocity for m in self._motors],
                    max_acceleration=[m.config.max_acceleration for m in self._motors],
                    min_acceleration=MIN_ACCELERATION,
                    independent_deceleration=True,
                )

    def _validate_gains(self, values: list[float]) -> None:
        self._require_parameter_write()
        if len(values) != NUM_JOINTS:
            raise ValueError(f"Expected {NUM_JOINTS} gain values, got {len(values)}")
        for motor, value in zip(self._motors, values):
            motor._encode_gain(value)

    def set_position_kps(self, kps: list[float]) -> None:
        with self._motion_timer._lock:
            self._validate_gains(kps)
            for motor, value in zip(self._motors, kps):
                motor.set_position_kp(value)

    def set_velocity_kps(self, kps: list[float]) -> None:
        with self._motion_timer._lock:
            self._validate_gains(kps)
            for motor, value in zip(self._motors, kps):
                motor.set_velocity_kp(value)

    def set_velocity_kis(self, kis: list[float]) -> None:
        with self._motion_timer._lock:
            self._validate_gains(kis)
            for motor, value in zip(self._motors, kis):
                motor.set_velocity_ki(value)

    def calibrate_zero(self) -> None:
        with self._motion_timer._lock:
            self._require_connection()
            if self.is_moving() or any(m.enabled for m in self._motors):
                raise StateError(
                    "Disable H75 and place it at mechanical zero before calibration"
                )
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
        with self._motion_timer._lock:
            self._require_parameter_write()
            self._kx.set_joint_limits(limits)

    def get_joint_limits(self) -> list[tuple[float, float]]:
        return self._kx.get_joint_limits()

    def close(self) -> None:
        """Finish owned work/restoration before marking the connection closed."""
        timer = self._motion_timer
        if timer._is_worker_thread():
            raise StateError(
                "Cannot close H75 from its active motion worker; stop first and close after it returns"
            )
        with self._close_lock:
            if getattr(self, "_resources_closed", False):
                return
            with timer._lock:
                self._closing = True
                active_worker = not timer._worker_done.is_set()
                was_closed = self._closed
            primary = None
            try:
                timer._wait_worker_done(report_error=active_worker)
                if not was_closed:
                    self.wait_motion_done()
            except BaseException as error:
                primary = error
                # Cancellation wakes timer waits before streaming cleanup ends.
                # Keep the bus open until that cleanup has actually run.
                _finish_cancelled_worker(timer)
            finally:
                self._closed = True
                try:
                    close_arm(self)
                except BaseException:
                    if primary is None:
                        raise
                    logger.exception(
                        "H75 connection cleanup also failed; close may be retried"
                    )
                finally:
                    timer._worker_error = None
            if primary is not None:
                raise primary

    def __enter__(self) -> "H75":
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
        # Recheck under _start_with_target's lock: mode may have changed while
        # move_p was solving IK, before motion ownership was acquired.
        self._require_pp()
        decelerations = self.get_control_decelerations()
        # A conservative trapezoidal estimate using the smaller ramp limit.
        # The drive uses an S-curve; this is not feedback-confirmed arrival.
        joint_duration(current_angles, target_angles, control_speeds, decelerations)
        if len(control_accelerations) != NUM_JOINTS:
            raise StateError("Missing H75 acceleration profile")
        joint_duration(
            current_angles, target_angles, control_speeds, control_accelerations
        )
        return joint_duration(
            current_angles,
            target_angles,
            control_speeds,
            [min(a, d) for a, d in zip(control_accelerations, decelerations)],
        )

    def save_params(self) -> None:
        with self._motion_timer._lock:
            self._require_connection()
            if self.is_moving():
                raise StateError("Cannot save H75 parameters during motion")
            for motor in self._motors:
                motor._save_params()
