"""Tests for diagnostics."""

from __future__ import annotations

import asyncio
import json

from lg_soundbar_bluetooth.testing import ADDRESS, FakeSoundbar
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lg_soundbar_bluetooth.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import JSONEncoder


async def test_diagnostics_are_serialisable(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    for _ in range(100):
        if config_entry.runtime_data.client.connected:
            break
        await asyncio.sleep(0.02)

    result = await async_get_config_entry_diagnostics(hass, config_entry)

    json.dumps(result, cls=JSONEncoder)
    state = result["state"]
    assert "OPT_HDMI_ARC_SUPPORT" in state["features"]
    assert "NEURAL_X" not in state["features"]
    assert state["extended_flags_available"] is True
    assert state["firmware_info_available"] is True
    assert state["sleep_timer_supported"] is False
    assert state["power_off_supported"] is True
    # A G1 has no second extended feature flags.
    assert state["features_2"] is None
    assert state["levels"]["WOOFER_LEVEL"] == {"value": 0, "minimum": -15, "maximum": 6}
    assert result["connected"] is True
    connected = next(e for e in result["history"] if e["event"] == "connected")
    assert {"connecting", "first input", "ready"} <= set(connected["timings"])
    assert result["entry_data"]["address"] == "**REDACTED**"


async def test_diagnostics_leave_out_the_address(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    # Error messages name the address, in either case.
    config_entry.runtime_data.connection._record(
        "connect failed", error=f"Could not connect to {ADDRESS.lower()}: refused"
    )

    result = await async_get_config_entry_diagnostics(hass, config_entry)

    text = json.dumps(result, cls=JSONEncoder)
    assert ADDRESS.lower() not in text.lower()
    assert result["history"][-1]["error"] == (
        "Could not connect to **REDACTED**: refused"
    )
