"""Sensors for LG Soundbars via Bluetooth."""

from __future__ import annotations

from typing import override

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LGSoundbarConfigEntry
from .const import CONF_FEATURES, FEATURE_AUDIO_INFO
from .entity import LGSoundbarEntity, async_remove_unoffered

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LGSoundbarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the audio format sensor if the soundbar reports it."""
    if entry.data.get(CONF_FEATURES, {}).get(FEATURE_AUDIO_INFO):
        async_add_entities([LGSoundbarAudioFormat(entry)])
    else:
        async_remove_unoffered(hass, entry, Platform.SENSOR, ["audio_format"])


class LGSoundbarAudioFormat(LGSoundbarEntity, SensorEntity):
    """The audio format the soundbar is playing, such as Dolby Atmos."""

    _attr_translation_key = "audio_format"

    def __init__(self, entry: LGSoundbarConfigEntry) -> None:
        """Initialise the sensor."""
        super().__init__(entry, "audio_format")

    @property
    @override
    def native_value(self) -> str | None:
        """Return the audio format."""
        return self.client.state.audio_info
