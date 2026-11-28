"""Diagnostics for LG Soundbars via Bluetooth."""

from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any, cast

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from lg_soundbar_bluetooth import Feature, Feature2

from . import LGSoundbarConfigEntry

# The Bluetooth address identifies the device; diagnostics are often posted
# publicly when reporting a model.
TO_REDACT = {CONF_ADDRESS}
REDACTED = "**REDACTED**"


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
    result = {
        "entry_data": async_redact_data(entry.data, TO_REDACT),
        "connected": client.connected,
        "on": entry.runtime_data.connection.is_on,
        # Most recent last: scans, connections and drops, with why.
        "history": list(entry.runtime_data.connection.history),
        "state": state,
    }
    # Error messages in the history name the address too.
    address = re.compile(re.escape(client.address), re.I)
    return cast(dict[str, Any], _redact_address(result, address))


def _redact_address(value: Any, address: re.Pattern[str]) -> Any:
    """Return value with the address replaced wherever it appears in text."""
    if isinstance(value, str):
        return address.sub(REDACTED, value)
    if isinstance(value, dict):
        return {key: _redact_address(item, address) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_address(item, address) for item in value]
    return value
