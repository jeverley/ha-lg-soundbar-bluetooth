"""Diagnostics for LG Soundbars via Bluetooth."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from lg_soundbar_bluetooth import Feature, Feature2

from . import LGSoundbarConfigEntry

# The Bluetooth address identifies the device; diagnostics are often posted
# publicly when reporting a model.
TO_REDACT = {CONF_ADDRESS}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LGSoundbarConfigEntry
) -> dict[str, Any]:
    """Return what the soundbar reported, to help add support for more models."""
    client = entry.runtime_data.client
    state = asdict(client.state)
    state["levels"] = {
        command.name: level for command, level in state["levels"].items()
    }
    state["switches"] = {
        command.name: value for command, value in state["switches"].items()
    }
    for key, flags in (("features", Feature), ("features_2", Feature2)):
        if (features := state[key]) is not None:
            names = {flag.value: flag.name for flag in flags}
            state[key] = sorted(names.get(flag, f"flag_{flag}") for flag in features)
    return {
        "entry_data": async_redact_data(entry.data, TO_REDACT),
        "connected": client.connected,
        "on": entry.runtime_data.connection.is_on,
        "channel": client.channel,
        # Most recent last: scans, connections and drops, with why.
        "history": list(entry.runtime_data.connection.history),
        "state": state,
    }
