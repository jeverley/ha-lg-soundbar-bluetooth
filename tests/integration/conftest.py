"""Fixtures for the Home Assistant integration tests."""

from __future__ import annotations

from collections.abc import Generator
from functools import partial
from unittest.mock import AsyncMock, patch

from bluetooth_classic import BluetoothClassicError, ClassicDevice
from lg_soundbar_bluetooth import LGSoundbar
from lg_soundbar_bluetooth.testing import ADDRESS, FakeSoundbar
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lg_soundbar_bluetooth.const import (
    CONF_AUTO_CONNECT,
    CONF_CHANNEL,
    CONF_FEATURES,
    DOMAIN,
)
from homeassistant.const import CONF_ADDRESS

# What the fake G1 reports.
FEATURES = {
    "levels": [0x1A, 0x1B, 0x21, 0x26, 0x2B],
    "switches": [0x09, 0x19, 0x1C, 0x1D, 0x22],
    "night_mode": True,
    "tone": True,
    "tone_middle": False,
    "audio_info": False,
    "sleep_timer": False,
    "woofer_state": True,
    "rear_state": False,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in every test."""
    return


@pytest.fixture
def soundbar() -> FakeSoundbar:
    """Return a fake soundbar."""
    return FakeSoundbar()


def _scan(soundbar: FakeSoundbar, address: str) -> ClassicDevice | None:
    if soundbar.visible is None:
        raise BluetoothClassicError("no BlueZ")
    if not soundbar.visible:
        return None
    return ClassicDevice(
        address=address, name="LG G1(XX)", path="/dev", adapter="hci0", rssi=-60
    )


@pytest.fixture
def mock_client(soundbar: FakeSoundbar) -> Generator[FakeSoundbar]:
    """Make the integration talk to the fake soundbar."""

    factory = partial(
        LGSoundbar,
        connector=soundbar.connector,
        send_interval=0,
        settle_quiet=0.05,
        settle_max=0.5,
        ask_timeout=0.2,
        switch_wait=0.2,
    )
    with (
        patch(
            "custom_components.lg_soundbar_bluetooth.config_flow.async_ensure_trusted"
        ),
        patch("custom_components.lg_soundbar_bluetooth.LGSoundbar", factory),
        patch(
            "custom_components.lg_soundbar_bluetooth.config_flow.LGSoundbar", factory
        ),
        # A scan sees the soundbar while it is on, as a real one.
        patch(
            "custom_components.lg_soundbar_bluetooth.connection.async_find_soundbar",
            AsyncMock(side_effect=partial(_scan, soundbar)),
        ),
    ):
        yield soundbar


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for the fake soundbar."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="LG G1(XX)",
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS, CONF_CHANNEL: 2, CONF_FEATURES: FEATURES},
        # Most tests want a connection; auto-connect gives one at start-up.
        options={CONF_AUTO_CONNECT: True},
    )
