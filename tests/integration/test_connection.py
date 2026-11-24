"""Tests for the connection manager and the settings it stores."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from bluetooth_classic import ClassicDevice
from lg_soundbar_bluetooth import (
    Feature,
    Level,
    SoundbarState,
    UtilityCommand,
)
from lg_soundbar_bluetooth.testing import FakeSoundbar
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lg_soundbar_bluetooth.connection import features_from_state
from custom_components.lg_soundbar_bluetooth.const import (
    CONF_AUTO_CONNECT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant

STORED = {"levels": [0x1B, 0x21], "switches": [0x09], "night_mode": True}


def test_flags_decide_even_when_a_reply_is_missing() -> None:
    # The woofer reply went missing, but the flag says the woofer exists.
    state = SoundbarState(
        levels={UtilityCommand.REAR_LEVEL: Level(0, -6, 6)},
        features=frozenset(
            {Feature.WOOFER_LEVEL, Feature.REAR_LEVEL, Feature.NIGHT_MODE}
        ),
    )
    result = features_from_state(state, STORED)
    assert (result["levels"], result["switches"], result["night_mode"]) == (
        [0x1B, 0x21],
        [],
        True,
    )


def test_without_flags_a_missing_reply_keeps_the_stored_setting() -> None:
    state = SoundbarState(
        levels={UtilityCommand.REAR_LEVEL: Level(0, -6, 6)},
        switches={UtilityCommand.AUTO_POWER: True},
    )
    result = features_from_state(state, STORED)
    assert (result["levels"], result["switches"], result["night_mode"]) == (
        [0x1B, 0x21],
        [0x09, 0x1D],
        True,
    )


async def test_scanning_survives_unexpected_errors(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    attempts = []

    async def flaky_scan(address: str) -> ClassicDevice | None:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("adapter vanished")
        return ClassicDevice(address=address, name=None, path="/dev", adapter="hci0")

    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_AUTO_CONNECT: True, CONF_SCAN_INTERVAL: 0.05}
    )
    with patch(
        "custom_components.lg_soundbar_bluetooth.connection.async_find_soundbar",
        flaky_scan,
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        client = config_entry.runtime_data.client
        for _ in range(100):
            await asyncio.sleep(0.02)
            if client.connected:
                break

    assert len(attempts) >= 2
    assert hass.states.get("media_player.lg_g1_xx").state == STATE_ON
    await hass.config_entries.async_unload(config_entry.entry_id)
