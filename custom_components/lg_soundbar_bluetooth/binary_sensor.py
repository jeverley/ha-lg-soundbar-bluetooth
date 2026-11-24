"""Connection states for LG Soundbars via Bluetooth."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from lg_soundbar_bluetooth import SoundbarState

from . import LGSoundbarConfigEntry
from .const import (
    CONF_FEATURES,
    FEATURE_REAR_STATE,
    FEATURE_WOOFER_STATE,
)
from .entity import LGSoundbarEntity, async_remove_unoffered

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LGSoundbarBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a connection the soundbar reports."""

    feature: str
    value_fn: Callable[[SoundbarState], bool | None]


BINARY_SENSORS: tuple[LGSoundbarBinarySensorDescription, ...] = (
    LGSoundbarBinarySensorDescription(
        key="woofer_connected",
        translation_key="woofer_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        feature=FEATURE_WOOFER_STATE,
        value_fn=lambda state: state.woofer_connected,
    ),
    LGSoundbarBinarySensorDescription(
        key="rear_connected",
        translation_key="rear_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        feature=FEATURE_REAR_STATE,
        value_fn=lambda state: state.rear_connected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LGSoundbarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the connection states the soundbar reports."""
    features = entry.data.get(CONF_FEATURES, {})
    entities: list[BinarySensorEntity] = [LGSoundbarLink(entry)]
    entities += [
        LGSoundbarBinarySensor(entry, description)
        for description in BINARY_SENSORS
        if features.get(description.feature)
    ]
    async_remove_unoffered(
        hass,
        entry,
        Platform.BINARY_SENSOR,
        [d.key for d in BINARY_SENSORS if not features.get(d.feature)]
        # Earlier versions had an input connection sensor. LG's app does not
        # show one, and a G1 cannot report eARC, the usual TV connection.
        + ["input_connected"],
    )
    async_add_entities(entities)


class LGSoundbarBinarySensor(LGSoundbarEntity, BinarySensorEntity):
    """A connection the soundbar reports, such as its subwoofer's."""

    entity_description: LGSoundbarBinarySensorDescription

    def __init__(
        self,
        entry: LGSoundbarConfigEntry,
        description: LGSoundbarBinarySensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether it is connected."""
        return self.entity_description.value_fn(self.client.state)


class LGSoundbarLink(LGSoundbarEntity, BinarySensorEntity):
    """Whether Home Assistant is connected to the soundbar over Bluetooth.

    The link drops whenever the soundbar is switched off, so this shows
    whether the soundbar is off or out of reach while the others go
    unavailable.
    """

    _attr_translation_key = "bluetooth_connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: LGSoundbarConfigEntry) -> None:
        """Initialise the sensor."""
        super().__init__(entry, "bluetooth_connection")

    @property
    @override
    def available(self) -> bool:
        """Stay available, as this reports the connection itself."""
        return True

    @property
    @override
    def is_on(self) -> bool:
        """Return whether the soundbar is connected."""
        return self.client.connected
