"""Exercise real dispatcher workers and motor protocol frames on virtual CAN.

Set ARM_TEST_VCAN to an isolated Linux vcan interface to run the same assertions
through SocketCAN. No physical CAN interface is opened by this test suite.
"""

import os
import struct
import threading
import uuid
from collections import deque

import can
import pytest

from linkerbot_arm import A7lite, ControlMode
from linkerbot_arm._transport.can import ManagedCANDispatcher
from linkerbot_arm.arm.a7.motor import A7Motor
from linkerbot_arm.arm.a7_lite.motor import A7liteMotor
from linkerbot_arm.arm.h75.motor import H75Motor
from linkerbot_arm.arm.p7.motor_v2 import MotorV2
from linkerbot_arm.comm.can import CanInterface, CANMessageDispatcher
from linkerbot_arm.exceptions import TimeoutError


class FakeDispatcher:
    def __init__(self):
        self.sent = deque()
        self.callbacks = []
        self.enabled_by_id = {}

    def subscribe(self, callback):
        self.callbacks.append(callback)

    def send(self, message):
        self.sent.append(message)
        data = bytes(message.data)
        if len(data) == 2 and data[0] == 0x2A:
            self.enabled_by_id[message.arbitration_id] = data[1]
        elif data == b"\x2b":
            self.feedback(
                can.Message(
                    arbitration_id=message.arbitration_id,
                    is_extended_id=False,
                    data=bytes(
                        [0x2B, self.enabled_by_id.get(message.arbitration_id, 0)]
                    ),
                )
            )

    def _send_checked(self, message, *, timeout_s=1.0):
        # This test backend sends synchronously; production backends await a receipt.
        self.send(message)

    def feedback(self, message):
        for callback in self.callbacks:
            callback(message)


@pytest.fixture(params=["fake", "real", "managed"])
def link(request):
    if request.param == "fake":
        dispatcher = FakeDispatcher()
        yield dispatcher, dispatcher.sent.popleft, dispatcher.feedback
        return
    channel = os.environ.get("ARM_TEST_VCAN", "arm-test-" + uuid.uuid4().hex)
    backend = "socketcan" if "ARM_TEST_VCAN" in os.environ else "virtual"
    if backend == "socketcan":
        assert channel.startswith("vcan"), "use an isolated vcan interface"
    with can.Bus(interface=backend, channel=channel) as peer:
        if request.param == "managed":
            model = {
                A7Motor: "a7",
                A7liteMotor: "a7_lite",
                MotorV2: "p7",
                H75Motor: "h75",
            }[request.node.callspec.params["cls"]]
            selected = ManagedCANDispatcher(channel, backend, model, "left")
        else:
            selected = CANMessageDispatcher(channel, backend)
        with selected as dispatcher:
            assert dispatcher.can_interface == CanInterface(channel, backend)
            received = threading.Event()

            def feedback(message):
                # Subscribe after the motor, so its decoder finishes first.
                received.clear()

                def callback(msg):
                    received.set()

                dispatcher.subscribe(callback)
                peer.send(message, timeout=1)
                assert received.wait(1), "dispatcher did not receive feedback"
                dispatcher.unsubscribe(callback)

            yield dispatcher, lambda: peer.recv(1), feedback
        assert not dispatcher._recv_thread.is_alive()
        if request.param == "managed":
            assert not dispatcher._tx.get_health().running
        else:
            assert not dispatcher._send_thread.is_alive()


@pytest.mark.parametrize(
    "cls,motor_id,angle,arb_id,extended,payload",
    [
        (A7Motor, 61, 0.5, 61, False, bytes.fromhex("0a0000003f")),
        (A7liteMotor, 61, 0.5, 0x1200FD3D, True, bytes.fromhex("167000000000003f")),
        (MotorV2, 66, 0.0, 66, False, bytes.fromhex("80008000424cc800")),
    ],
)
def test_motor_control_frames_and_feedback(
    link, cls, motor_id, angle, arb_id, extended, payload
):
    dispatcher, receive, feedback = link
    motor = cls(motor_id, dispatcher)
    assert motor.set_angle(angle) is None
    frame = receive()
    assert frame is not None
    assert (frame.arbitration_id, frame.is_extended_id, bytes(frame.data)) == (
        arb_id,
        extended,
        payload,
    )
    assert motor.control_angle.angle == angle
    if cls is A7Motor:
        relay = motor._get_relay(0x06)
        feedback(
            can.Message(
                arbitration_id=61,
                data=b"\x06" + struct.pack("<f", 1.25),
                is_extended_id=False,
            )
        )
        assert relay.snapshot() == struct.pack("<f", 1.25)
    elif cls is A7liteMotor:
        feedback(
            can.Message(
                arbitration_id=0x02003DFD,
                data=bytes.fromhex("ffffffffffff012c"),
                is_extended_id=True,
            )
        )
        assert motor.angle.angle == pytest.approx(12.57)
        assert motor.velocity.velocity == 33.0
        assert motor.torque.torque == 14.0
        assert motor.temperature.temperature == 30.0
    else:
        feedback(
            can.Message(
                arbitration_id=66,
                data=bytes.fromhex("01ffffffff00071e"),
                is_extended_id=False,
            )
        )
        assert motor.angle.angle == 12.5
        assert motor.velocity.velocity == 10.0
        assert motor.fault_code == 7
        assert motor.temperature.temperature == 30.0
        # Register an addressed reader before injecting a Flash response.
        with pytest.raises(TimeoutError):
            motor._read_flash_param(0x0B, timeout_s=0)
        feedback(
            can.Message(
                arbitration_id=0x642,
                data=bytes.fromhex("420b0102030400ff"),
                is_extended_id=False,
            )
        )
        assert motor._flash_relays[0x0B].snapshot() == b"\x01\x02\x03\x04"


@pytest.mark.parametrize("cls", [A7Motor, A7liteMotor, MotorV2])
def test_motor_register_timeout_is_still_arm_timeout(link, cls):
    dispatcher, _, _ = link
    motor = cls(61, dispatcher)
    read = motor._read_flash_param if cls is MotorV2 else motor._read_register
    with pytest.raises(TimeoutError):
        read(1, timeout_s=0)


@pytest.mark.parametrize("cls", [A7liteMotor])
def test_mit_csp_and_mode_changes_keep_wire_bytes_and_order(link, cls):
    dispatcher, receive, _ = link
    arm = A7lite.__new__(A7lite)
    arm._motors = [cls(mid, dispatcher) for mid in range(61, 68)]
    arm._control_modes = None
    arm.set_control_modes([ControlMode.MIT, ControlMode.CSP] + [ControlMode.PP] * 5)
    frames = [receive() for _ in range(14)]
    assert [frame.arbitration_id for frame in frames[:7]] == [
        0x0400FD00 | mid for mid in range(61, 68)
    ]
    assert [bytes(frame.data) for frame in frames[:7]] == [bytes(8)] * 7
    assert [frame.arbitration_id for frame in frames[7:]] == [
        0x1200FD00 | mid for mid in range(61, 68)
    ]
    assert [struct.unpack("<HHI", bytes(frame.data)) for frame in frames[7:]] == [
        (0x7005, 0, value) for value in [0, 5, 1, 1, 1, 1, 1]
    ]
    arm._motors[0].set_mit(0.0, 0.0, 20.0, 1.0, 0.0)
    frame = receive()
    assert frame.arbitration_id == 0x017FFF3D
    assert bytes(frame.data) == bytes.fromhex("7fff7fff0a3d3333")
    arm._motors[1].set_limit_spd(0.5)
    frame = receive()
    assert frame.arbitration_id == 0x1200FD3E
    assert bytes(frame.data) == bytes.fromhex("177000000000003f")


def test_subscribe_unsubscribe_and_stop_inside_callback():
    channel = "arm-subscribe-" + uuid.uuid4().hex
    dispatcher = CANMessageDispatcher(channel, "virtual")
    seen = []
    callback_stopped = threading.Event()
    release_callback = threading.Event()

    def removed(message):
        seen.append("removed")

    def stop_in_callback(message):
        seen.append(bytes(message.data))
        dispatcher.stop()
        callback_stopped.set()
        release_callback.wait(2)

    dispatcher.subscribe(removed)
    dispatcher.unsubscribe(removed)
    dispatcher.unsubscribe(removed)
    dispatcher.subscribe(stop_in_callback)
    dispatcher.subscribe(stop_in_callback)
    with can.Bus(interface="virtual", channel=channel) as peer:
        try:
            peer.send(can.Message(arbitration_id=61, data=b"x"))
            assert callback_stopped.wait(1)
            assert seen == [b"x"]
            with pytest.raises(RuntimeError, match="stopped"):
                dispatcher.send(can.Message(arbitration_id=61))
        finally:
            release_callback.set()
            dispatcher.stop()
    assert not dispatcher._recv_thread.is_alive()
    assert not dispatcher._send_thread.is_alive()
