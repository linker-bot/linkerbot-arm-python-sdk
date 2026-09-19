"""Human-readable joint names for the built-in arm CAN ID assignments."""


def describe_motor(motor_id: int) -> str:
    """Keep the CAN ID visible alongside the side and one-based joint number."""
    if 51 <= motor_id <= 57:
        return f"Right arm joint {motor_id - 50} (CAN ID {motor_id})"
    if 61 <= motor_id <= 67:
        return f"Left arm joint {motor_id - 60} (CAN ID {motor_id})"
    return f"Motor (CAN ID {motor_id})"
