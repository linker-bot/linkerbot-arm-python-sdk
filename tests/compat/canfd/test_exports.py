"""Deep CAN FD exports remain callable through the original arm namespace."""

import importlib

import pytest

from linkerbot_arm.comm import canfd
from linkerbot_arm.exceptions import CANError, StateError, ValidationError


@pytest.mark.parametrize("name", ["ctypes_backend", "socketcan_backend", "dispatcher"])
def test_deep_module_exports_keep_arm_identity(name):
    module = importlib.import_module("linkerbot_arm.comm.canfd." + name)
    namespace = {}
    exec("from " + module.__name__ + " import *", namespace)
    assert namespace["CANError"] is CANError
    assert namespace["ValidationError"] is ValidationError
    assert namespace["CANFDMessage"] is canfd.CANFDMessage
    if name == "ctypes_backend":
        assert namespace["CANFDConfigOptions"] is canfd.CANFDConfigOptions
        assert namespace["CANFDInterface"] is canfd.CANFDInterface
        assert namespace["CANFD_TRANSMIT_MAX_BATCH"] == 100
        assert namespace["dlc_to_length"] is canfd.dlc_to_length
    elif name == "socketcan_backend":
        assert namespace["SocketCANFDBackend"] is canfd.SocketCANFDBackend
        assert namespace["dlc_to_length"] is canfd.dlc_to_length
        assert namespace["length_to_dlc"] is canfd.length_to_dlc
    else:
        assert namespace["StateError"] is StateError
        assert namespace["CANFDSendReceipt"] is canfd.CANFDSendReceipt
        assert namespace["CANFDMessageDispatcher"] is canfd.CANFDMessageDispatcher
        assert namespace["RECEIVE_BATCH_SIZE"] == 64
