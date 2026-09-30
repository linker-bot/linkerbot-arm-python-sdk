"""H75 状态读取和小幅运动；来源为上游 9041b05 的实机工具。

默认 read 只查询状态。enable/jog/home 是显式操作阶段，结束后失能并关闭连接。
示例：python tools/h75_smoke.py --side left --interface can0 --stage read
"""

import argparse
import logging
import math
import time

from linkerbot_arm import H75, ValidationError

logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--interface", required=True, help="CAN 接口名，如 can0")
    parser.add_argument("--interface-type", default="socketcan")
    parser.add_argument(
        "--stage", choices=("read", "enable", "jog", "home"), default="read"
    )
    parser.add_argument("--joint", type=int, choices=range(1, 8), default=4)
    parser.add_argument(
        "--delta",
        type=float,
        default=0.05,
        help="jog 的有符号角度增量，rad，绝对值不超过 0.1",
    )
    parser.add_argument("--velocity", type=float, default=0.1, help="关节速度 rad/s")
    parser.add_argument(
        "--acceleration", type=float, default=0.15, help="关节加减速度 rad/s²"
    )
    parser.add_argument("--hold", type=float, default=1.0, help="enable 阶段保持秒数")
    args = parser.parse_args(argv)
    if not math.isfinite(args.delta) or not 0 < abs(args.delta) <= 0.1:
        parser.error("delta 必须有限，且绝对值在 (0, 0.1] rad")
    if not math.isfinite(args.hold) or args.hold < 0:
        parser.error("hold 必须为有限非负秒数")
    for value in (args.velocity, args.acceleration):
        if not math.isfinite(value) or value <= 0:
            parser.error("速度和加速度必须为有限正数")

    with H75(args.side, args.interface, interface_type=args.interface_type) as arm:
        print("angles (rad):", arm.get_angles())
        print("velocities (rad/s):", arm.get_velocities())
        print("currents (A):", arm.get_currents())
        print("temperatures (°C):", arm.get_temperatures())
        if args.stage == "read":
            return 0
        target = arm.get_angles()
        if args.stage == "jog":
            target[args.joint - 1] += args.delta
            if any(
                not lo <= q <= hi for q, (lo, hi) in zip(target, arm.get_joint_limits())
            ):
                raise ValidationError("jog 目标超出关节限位，未使能电机")
        # Validate profile encoding before enable; defaults are examples, not
        # load-independent operating ratings. H75.enable selects PP by default.
        arm.set_velocities([args.velocity] * 7)
        arm.set_accelerations([args.acceleration] * 7)
        try:
            arm.enable()
            if args.stage == "jog":
                arm.move_j(target)
            elif args.stage == "home":
                arm.home()
            else:
                time.sleep(args.hold)
        except BaseException:
            try:
                arm.disable()
            except BaseException:
                logger.exception("H75 清理失能失败，请检查抱闸和电机状态")
            raise
        else:
            arm.disable()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
