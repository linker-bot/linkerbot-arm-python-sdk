"""Read-only startup discovery shared by all arm models and CAN backends."""

import logging
import time

from linkerbot_arm.arm.common._diagnostics import describe_motor
from linkerbot_arm.exceptions import StateError

logger = logging.getLogger(__name__)

# Startup-only budgets. Motor.check_alive() keeps its public defaults.
_ATTEMPT_TIMEOUTS = (0.1, 0.2)
_TOTAL_TIMEOUT = 2.5


def check_motors(motors) -> None:
    started = time.monotonic()
    deadline = started + _TOTAL_TIMEOUT
    pending = list(motors)
    attempts = {motor._id: 0 for motor in pending}
    for budget in _ATTEMPT_TIMEOUTS:
        for motor in tuple(pending):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            timeout = min(budget, remaining)
            attempt_started = time.monotonic()
            attempts[motor._id] += 1
            # A failed send/bus fault is not a timeout and must propagate. Do not
            # mask it with retries or recovery commands that could move the arm.
            alive = motor.check_alive(timeout_s=timeout)
            logger.debug(
                "%s startup probe attempt=%d budget=%.3fs elapsed=%.3fs replied=%s",
                describe_motor(motor._id),
                attempts[motor._id],
                timeout,
                time.monotonic() - attempt_started,
                alive,
            )
            if alive:
                pending.remove(motor)
                if attempts[motor._id] > 1:
                    logger.info(
                        "%s responded on startup retry", describe_motor(motor._id)
                    )
        if not pending:
            return
    if pending:
        names = ", ".join(describe_motor(motor._id) for motor in pending)
        counts = ", ".join(f"{motor._id}={attempts[motor._id]}" for motor in pending)
        raise StateError(
            f"{names} did not respond during startup discovery. "
            f"Expected {len(motors)} joints, {len(motors) - len(pending)} responded. "
            f"Attempts by CAN ID: {counts}; per-attempt budgets 100/200 ms, "
            f"total budget {_TOTAL_TIMEOUT:.1f}s, elapsed {time.monotonic() - started:.3f}s. "
            "Check CAN communication, wiring, and power."
        )
