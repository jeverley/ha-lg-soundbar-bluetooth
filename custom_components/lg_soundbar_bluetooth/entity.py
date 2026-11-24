"""Base entity for LG Soundbars via Bluetooth."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import override

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity
from lg_soundbar_bluetooth import (
    SPECIAL_EQ_NAMES,
    LGSoundbarError,
    SpecialEq,
    model_from_name,
)

from . import LGSoundbarConfigEntry
from .const import CONF_MODEL, DOMAIN


class LGSoundbarEntity(Entity):
    """An entity backed by the soundbar's push updates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: LGSoundbarConfigEntry, key: str | None) -> None:
        """Initialise the entity."""
        self.client = entry.runtime_data.client
        self.connection = entry.runtime_data.connection
        address = self.client.address
        self._attr_unique_id = address if key is None else f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            manufacturer="LG Electronics",
            model=entry.data.get(CONF_MODEL) or model_from_name(entry.title),
            name=entry.title,
            sw_version=self.client.state.firmware_version,
        )

    @property
    @override
    def available(self) -> bool:
        """Return whether the soundbar is connected."""
        return self.client.connected

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to soundbar updates."""
        self.async_on_remove(self.connection.register_callback(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @staticmethod
    def _refuse_if_locked(locked_by: SpecialEq | None) -> None:
        """Refuse a change the soundbar ignores in a special sound mode."""
        if locked_by is None:
            return
        if locked_by == SpecialEq.OFF:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="needs_dts_x"
            )
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="locked_by_special_mode",
            translation_placeholders={"mode": SPECIAL_EQ_NAMES[locked_by]},
        )

    async def _command(self, command: Awaitable[None]) -> None:
        """Run a soundbar command, turning library errors into HA errors."""
        try:
            await command
        except LGSoundbarError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err


def async_remove_unoffered(
    hass: HomeAssistant,
    entry: LGSoundbarConfigEntry,
    platform: str,
    keys: list[str],
) -> None:
    """Remove entities for settings the soundbar turned out not to offer.

    Earlier versions created an entity for every setting the soundbar
    answered, including ones it does not have.
    """
    registry = er.async_get(hass)
    address = entry.runtime_data.client.address
    for key in keys:
        if entity_id := registry.async_get_entity_id(
            platform, DOMAIN, f"{address}_{key}"
        ):
            registry.async_remove(entity_id)
