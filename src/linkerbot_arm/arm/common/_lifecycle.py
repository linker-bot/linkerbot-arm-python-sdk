"""Best-effort disable across a group after a physical send failure."""

import logging

logger = logging.getLogger(__name__)


def disable_motors(motors):
    errors = []
    for motor in motors:
        try:
            motor.disable()
        except Exception as error:
            errors.append(error)
            logger.error("Motor %d disable failed: %s", motor._id, error)
    if errors:
        raise errors[0]
