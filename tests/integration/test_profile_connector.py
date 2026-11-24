"""Tests for the test build's profile connector."""

from __future__ import annotations

import asyncio
import os

from custom_components.lg_soundbar_bluetooth.profile_connector import (
    _SerialPortProfile,
)

DEVICE = "/org/bluez/hci0/dev_00_11_22_33_44_55"


async def test_the_request_is_written_as_bluez_hands_over_the_socket() -> None:
    profile = _SerialPortProfile()
    future = asyncio.get_running_loop().create_future()
    profile.waiting[DEVICE] = (b"hello", future)
    ours, device = os.pipe()
    # BlueZ's call, with the end we would write to.
    profile.NewConnection.__wrapped__(profile, DEVICE, device, {})
    assert os.read(ours, 5) == b"hello"
    fd, _ = future.result()
    assert fd == device
    os.close(ours)
    os.close(device)


async def test_an_unexpected_connection_is_closed() -> None:
    profile = _SerialPortProfile()
    ours, device = os.pipe()
    profile.NewConnection.__wrapped__(profile, DEVICE, device, {})
    # Our end now reads end of file: the other end was closed.
    assert os.read(ours, 1) == b""
    os.close(ours)
