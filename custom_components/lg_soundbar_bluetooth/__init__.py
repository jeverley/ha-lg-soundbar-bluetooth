"""The LG Soundbars via Bluetooth integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from lg_soundbar_bluetooth import BluetoothUnsupported, CannotConnect, LGSoundbar

from .connection import LGSoundbarConnection
from .const import CONF_CHANNEL, CONF_FEATURES, CONF_FLAGS, DOMAIN
from .profile_connector import CONNECTOR

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class LGSoundbarData:
    """Runtime data for a config entry."""

    client: LGSoundbar
    connection: LGSoundbarConnection


type LGSoundbarConfigEntry = ConfigEntry[LGSoundbarData]


async def async_setup_entry(hass: HomeAssistant, entry: LGSoundbarConfigEntry) -> bool:
    """Set up a soundbar from a config entry.

    Home Assistant does not connect here: connecting would wake a soundbar
    that is off, or move one that is on to Bluetooth. A scan tells whether it
    is on, and commands connect when needed. Only an entry without stored
    features (set up by an older version) connects once to read them.
    """
    client = LGSoundbar(
        entry.data[CONF_ADDRESS],
        entry.data.get(CONF_CHANNEL),
        # Test build: open the link through BlueZ's profile API.
        connector=CONNECTOR.connect,
        known_features=entry.data.get(CONF_FLAGS),
    )
    connection = LGSoundbarConnection(hass, entry, client)
    if not entry.data.get(CONF_FEATURES):
        await _async_read_features(client, connection)

    entry.runtime_data = LGSoundbarData(client, connection)
    # The Disconnect button of earlier versions is not needed: LG's app takes
    # the soundbar over by itself, and Home Assistant does not reconnect.
    registry = er.async_get(hass)
    if old := registry.async_get_entity_id(
        Platform.BUTTON, DOMAIN, f"{client.address}_disconnect"
    ):
        registry.async_remove(old)
    entry.async_on_unload(connection.stop)

    async def _async_stop(event: Event) -> None:
        # Home Assistant does not unload entries when it stops, so close the
        # connection here rather than leave it to the process exiting.
        await connection.stop()

    entry.async_on_unload(hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, _async_stop))
    connection.start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_read_features(
    client: LGSoundbar, connection: LGSoundbarConnection
) -> None:
    """Connect once to learn what the soundbar offers."""
    try:
        await connection.async_ensure_connected("reading features at set-up")
    except BluetoothUnsupported as err:
        await connection.stop()
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="bluetooth_unsupported"
        ) from err
    except CannotConnect as err:
        await connection.stop()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"address": client.address},
        ) from err


# Stored by earlier versions and no longer used.
OBSOLETE_KEYS = ("last_source", "powered_off")


async def async_migrate_entry(
    hass: HomeAssistant, entry: LGSoundbarConfigEntry
) -> bool:
    """Bring a config entry stored by an earlier version up to date."""
    if entry.version > 1:
        # Stored by a newer version, which this one cannot read.
        return False
    if entry.minor_version < 2:
        data = {
            key: value for key, value in entry.data.items() if key not in OBSOLETE_KEYS
        }
        hass.config_entries.async_update_entry(entry, data=data, minor_version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LGSoundbarConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
