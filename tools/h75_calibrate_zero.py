"""H75 标零：将当前机械姿态设为零点并保存 EEPROM，必须显式 --yes。

运行前将机械臂放在正确零位并做好支撑，停止其他控制程序。此操作会改变持久配置。
示例：python tools/h75_calibrate_zero.py --side left --interface can0 --yes
"""

import argparse
import math
import time

from linkerbot_arm import H75, StateError
from linkerbot_arm.arm.h75.motor import InternalSensorType, SensorType


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--interface-type", default="socketcan")
    parser.add_argument(
        "--yes", action="store_true", help="确认当前姿态是机械零位，并允许保存"
    )
    parser.add_argument("--settle", type=float, default=0.3, help="保存后等待秒数")
    args = parser.parse_args(argv)
    if not args.yes:
        parser.error("标零需要 --yes；未连接或修改电机")
    if not math.isfinite(args.settle) or args.settle < 0:
        parser.error("settle 必须为有限非负秒数")
    with H75(args.side, args.interface, interface_type=args.interface_type) as arm:
        print("before (rad):", arm.get_angles())
        arm.stop_polling()
        arm.disable()
        # Confirm disable through new register reads before persisting zeros.
        for motor in arm._motors:
            if motor._read_register(InternalSensorType.ENABLED)[0] != 0:
                raise StateError(f"CAN ID {motor._id} 仍处于使能状态，未标零")
        arm.calibrate_zero()
        time.sleep(args.settle)
        angles = [
            motor._decode_sensor(
                SensorType.POSITION, motor._read_register(SensorType.POSITION)
            )
            for motor in arm._motors
        ]
        print("after, new position reads (rad):", angles)
        if any(not math.isfinite(q) or abs(q) > 0.05 for q in angles):
            raise StateError(
                "标零后查询值未接近零；请检查姿态、固件和通信，已保存值不会自动回滚"
            )
        print("新查询值接近零；尚需断电重启确认 EEPROM 持久化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
