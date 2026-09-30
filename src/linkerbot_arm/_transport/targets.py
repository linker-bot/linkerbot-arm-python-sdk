"""Atomic motion admission shared by all arm models and CAN backends."""

import math
import queue
import threading
import time
from concurrent.futures import TimeoutError as ReceiptTimeoutError
from dataclasses import dataclass

from linkerbot_transport import SendOutcome, TransmitArbiter, TransmitHealth
from linkerbot_transport.errors import QueueFullError, TransportError
from linkerbot_transport.errors import TimeoutError as TransportTimeoutError

from linkerbot_arm.exceptions import CANError, StateError, TimeoutError, ValidationError


@dataclass(frozen=True, slots=True)
class PreparedTarget:
    motor: object
    message: object
    updates: dict

    def commit(self):
        self.motor.__dict__.update(self.updates)


@dataclass(frozen=True, slots=True)
class MotionQueueHealth:
    """Cached queue state; accepted targets are not proof of physical delivery."""

    queue: TransmitHealth
    max_target_age_s: float | None
    last_outcome: SendOutcome | None
    last_sent_frames: int
    last_frame_count: int
    last_error: str | None


class TargetQueueMixin:
    def _init_target_queue(self):
        if not hasattr(TransmitArbiter, "submit_fifo_batch"):
            raise StateError(
                "This arm source requires transport FIFO-batch support; "
                "install requirements/transport.txt before opening the arm"
            )
        self._target_lock = threading.RLock()
        self._max_target_age_s = None
        self._last_target_receipt = None
        self._checked_condition = threading.Condition()
        self._checked_error = None

    def _fail_checked_sends(self, error):
        # An in-flight receipt may finish only after a fault callback returns.
        # Wake its caller before callbacks try to acquire the caller's locks.
        with self._checked_condition:
            if self._checked_error is None:
                self._checked_error = error
            self._checked_condition.notify_all()

    def _send_checked(self, message, *, timeout_s=1.0):
        """Wait for one lifecycle frame to reach the physical backend.

        Retain FIFO order and capacity, but do not apply target-age admission.
        A queued command which has not started by the deadline must expire;
        an already in-flight frame cannot be retracted.
        """
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(timeout_s)
            or timeout_s <= 0
        ):
            raise ValidationError("checked-send timeout must be finite and positive")
        deadline = time.monotonic() + timeout_s
        try:
            receipt = self._submit_target_frames((message,), deadline_at_s=deadline)

            def completed(_):
                with self._checked_condition:
                    self._checked_condition.notify_all()

            receipt.add_done_callback(completed)
            with self._checked_condition:
                ready = self._checked_condition.wait_for(
                    lambda: receipt.done() or self._checked_error is not None,
                    timeout=max(0.0, deadline - time.monotonic()),
                )
                if self._checked_error is not None:
                    raise self._checked_error
                if not ready:
                    raise ReceiptTimeoutError("physical backend did not complete")
            result = receipt.result(timeout=0)
            if result.outcome is not SendOutcome.DISPATCHED:
                raise CANError(f"Lifecycle frame was not dispatched: {result.outcome}")
        except QueueFullError as error:
            raise queue.Full() from error
        except (ReceiptTimeoutError, TransportTimeoutError) as error:
            raise TimeoutError(f"Lifecycle CAN send timed out: {error}") from error
        except TransportError as error:
            raise CANError(str(error)) from error
        except Exception as error:
            raise CANError(f"Lifecycle CAN send failed: {error}") from error

    def set_motion_queue_policy(self, *, max_target_age_s=None):
        """Opt in to rejecting stale queues and expiring unstarted targets.

        None preserves capacity-only admission. Control/configuration messages
        are never discarded by this policy; close always remains available.
        """
        if max_target_age_s is not None and (
            isinstance(max_target_age_s, bool)
            or not isinstance(max_target_age_s, (int, float))
            or not math.isfinite(max_target_age_s)
            or max_target_age_s <= 0
        ):
            raise ValidationError(
                "max_target_age_s must be finite and positive or None"
            )
        with self._target_lock:
            self._max_target_age_s = max_target_age_s

    def send_targets(self, targets, *, enforce_age=True):
        targets = tuple(targets)
        with self._target_lock:
            budget = self._max_target_age_s if enforce_age else None
            try:
                receipt = self._submit_target_frames(
                    (target.message for target in targets),
                    deadline_at_s=None if budget is None else time.monotonic() + budget,
                    max_pending_age_s=budget,
                )
            except QueueFullError as error:
                raise queue.Full() from error
            except TransportTimeoutError as error:
                raise TimeoutError(str(error)) from error
            except TransportError as error:
                raise CANError(*error.args) from error
            # Every parameter/model was constructed before admission. Neither
            # rejected batches nor failed encodings modify accepted-target state.
            for target in targets:
                target.commit()
                target.motor._target_receipt = receipt
            self._last_target_receipt = receipt

    def send_heartbeat(self, motor, build_message):
        # Serialize heartbeat admission with group admission: a heartbeat cannot
        # revive an expired/failed target or overtake a newer accepted target.
        with self._target_lock:
            previous = getattr(motor, "_target_receipt", None)
            if previous is not None and previous.outcome is not SendOutcome.DISPATCHED:
                return
            budget = self._max_target_age_s
            try:
                self._submit_target_frames(
                    (build_message(),),
                    deadline_at_s=None if budget is None else time.monotonic() + budget,
                    max_pending_age_s=budget,
                )
            except (QueueFullError, TransportTimeoutError):
                # The next scheduled heartbeat retries; never build a backlog
                # of stale holds while a target is still waiting to dispatch.
                return

    def get_motion_health(self):
        with self._target_lock:
            budget = self._max_target_age_s
            receipt = self._last_target_receipt
        error = receipt.exception() if receipt is not None and receipt.done() else None
        # Receipt state is read without holding the admission lock.
        return MotionQueueHealth(
            queue=self._tx.get_health(),
            max_target_age_s=budget,
            last_outcome=None if receipt is None else receipt.outcome,
            last_sent_frames=0 if receipt is None else receipt.sent_frames,
            last_frame_count=0 if receipt is None else receipt.frame_count,
            last_error=None if error is None else str(error),
        )


def submit_targets(targets, *, enforce_age=True):
    """Dispatch prevalidated targets, using native batching when available."""
    targets = tuple(targets)
    if not targets:
        return
    dispatcher = targets[0].motor._dispatcher
    if any(t.motor._dispatcher is not dispatcher for t in targets):
        raise ValidationError("a target batch must belong to one arm connection")
    if isinstance(dispatcher, TargetQueueMixin):
        dispatcher.send_targets(targets, enforce_age=enforce_age)
    else:
        # Compatibility with user-supplied test/custom dispatchers. Built-in
        # legacy and managed dispatchers both take the atomic path above.
        for target in targets:
            dispatcher.send(target.message)
            target.commit()


class ArmMotionQueueMixin:
    def set_motion_queue_policy(self, *, max_target_age_s=None):
        self._can_dispatcher.set_motion_queue_policy(max_target_age_s=max_target_age_s)

    def get_motion_health(self) -> MotionQueueHealth:
        return self._can_dispatcher.get_motion_health()
