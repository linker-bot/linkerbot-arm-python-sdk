"""Load every installed URDF and execute real FK/IK without a CAN device."""

import importlib.resources
import math

import pytest


@pytest.mark.parametrize("arm_type", ["a7", "a7_lite", "p7"])
@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("world_frame", ["urdf", "maestro"])
def test_builtin_kinematics(arm_type, side, world_frame):
    pytest.importorskip("pinocchio")
    from linkerbot.arm.kinetix import ArmKinetix

    resource = importlib.resources.files("linkerbot.arm.kinetix.urdf")
    assert (resource / f"{arm_type}__{side}.urdf").is_file()
    kx = ArmKinetix.from_builtin(
        arm_type, side, tcp_offset=[0.01, 0.02, 0.03], world_frame=world_frame
    )
    assert kx.side == side
    limits = kx.get_joint_limits()
    assert len(limits) == 7
    angles = [(lower + upper) / 2 for lower, upper in limits]
    pose = kx.forward_kinematics(angles)
    assert all(math.isfinite(v) for v in pose.to_list())
    result = kx.inverse_kinematics_result(pose, angles)
    assert result.is_ok(), result.error
    actual = kx.forward_kinematics(result.joint_angles)
    assert actual.to_list() == pytest.approx(pose.to_list(), abs=1e-5)
