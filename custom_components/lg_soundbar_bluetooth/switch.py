"""On/off settings for LG Soundbars via Bluetooth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from lg_soundbar_bluetooth import UtilityCommand

from . import LGSoundbarConfigEntry
from .const import CONF_FEATURES, FEATURE_NIGHT_MODE, FEATURE_SWITCHES
from .entity import LGSoundbarEntity, async_remove_unoffered

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LGSoundbarSwitchDescription(SwitchEntityDescription):
    """Describes a soundbar on/off setting."""

    command: UtilityCommand


SWITCHES: tuple[LGSoundbarSwitchDescription, ...] = (
    LGSoundbarSwitchDescription(
        key="drc", translation_key="drc", command=UtilityCommand.DRC_CONTROL
    ),
    LGSoundbarSwitchDescription(
        key="auto_volume",
        translation_key="auto_volume",
        command=UtilityCommand.AUTO_VOLUME,
    ),
    LGSoundbarSwitchDescription(
        key="auto_power",
        translation_key="auto_power",
        command=UtilityCommand.AUTO_POWER,
    ),
    LGSoundbarSwitchDescription(
        key="auto_display",
        translation_key="auto_display",
        command=UtilityCommand.AUTO_DISPLAY,
    ),
    LGSoundbarSwitchDescription(
        key="neural_x", translation_key="neural_x", command=UtilityCommand.NEURAL_X
    ),
    LGSoundbarSwitchDescription(
        key="surround",
        translation_key="surround",
        command=UtilityCommand.SURROUND_SETTING,
    ),
    LGSoundbarSwitchDescription(
        key="tv_remote",
        translation_key="tv_remote",
        command=UtilityCommand.TV_REMOTE_CONTROL_USE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LGSoundbarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the on/off settings the soundbar reported."""
    features = entry.data.get(CONF_FEATURES, {})
    supported = set(features.get(FEATURE_SWITCHES, []))
    entities: list[SwitchEntity] = [
        LGSoundbarSettingSwitch(entry, description)
        for description in SWITCHES
        if description.command in supported
    ]
    if features.get(FEATURE_NIGHT_MODE):
        entities.append(LGSoundbarNightModeSwitch(entry))
    entities.append(LGSoundbarConnectedSwitch(entry))
    async_remove_unoffered(
        hass,
        entry,
        Platform.SWITCH,
        [d.key for d in SWITCHES if d.command not in supported]
        + ([] if features.get(FEATURE_NIGHT_MODE) else ["night_mode"]),
    )
    async_add_entities(entities)


class LGSoundbarSettingSwitch(LGSoundbarEntity, SwitchEntity):
    """An on/off setting from the soundbar's settings menu."""

    entity_description: LGSoundbarSwitchDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, entry: LGSoundbarConfigEntry, description: LGSoundbarSwitchDescription
    ) -> None:
        """Initialise the setting."""
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    @override
    def available(self) -> bool:
        """Return whether the soundbar is connected and reported this setting."""
        return (
            super().available
            and self.entity_description.command in self.client.state.switches
        )

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the setting is on."""
        return self.client.state.switches.get(self.entity_description.command)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        self._refuse_if_locked(
            self.client.state.locked_by(self.entity_description.command)
        )
        await self._command(
            self.client.set_switch(self.entity_description.command, True)
        )

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        self._refuse_if_locked(
            self.client.state.locked_by(self.entity_description.command)
        )
        await self._command(
            self.client.set_switch(self.entity_description.command, False)
        )


class LGSoundbarNightModeSwitch(LGSoundbarEntity, SwitchEntity):
    """Night mode, which compresses loud passages for late listening."""

    _attr_translation_key = "night_mode"

    def __init__(self, entry: LGSoundbarConfigEntry) -> None:
        """Initialise the switch."""
        super().__init__(entry, "night_mode")

    @property
    @override
    def available(self) -> bool:
        """Return whether the soundbar is connected and reported night mode."""
        return super().available and self.client.state.night_mode is not None

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether night mode is on."""
        return self.client.state.night_mode

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn night mode on."""
        self._refuse_if_locked(self.client.state.night_mode_locked_by)
        await self._command(self.client.set_night_mode(True))

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn night mode off."""
        self._refuse_if_locked(self.client.state.night_mode_locked_by)
        await self._command(self.client.set_night_mode(False))


class LGSoundbarConnectedSwitch(LGSoundbarEntity, SwitchEntity):
    """Whether Home Assistant is connected to the soundbar, to connect or let go.

    The soundbar keeps only its newest control connection, so turning this
    off hands it back to LG's app. Connecting wakes a soundbar that is off,
    so turning this on then turns it on, as the media player's turn on does
    (with the input chosen for turning on). It turns off by itself when the
    link drops, as when the soundbar is switched off.
    """

    _attr_translation_key = "connected"

    def __init__(self, entry: LGSoundbarConfigEntry) -> None:
        """Initialise the switch."""
        super().__init__(entry, "connected")

    @property
    @override
    def available(self) -> bool:
        """Stay available: turning it on connects, waking a soundbar that is off."""
        return True

    @property
    @override
    def is_on(self) -> bool:
        """Return whether Home Assistant is connected to the soundbar."""
        return self.client.connected

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Connect: put the input back, or turn on a soundbar that is off."""
        await self._command(
            self.connection.async_ensure_connected(
                # Only when a scan saw it off: an unknown or older scan may
                # miss it being switched on on Bluetooth, as by its remote.
                "connected switch",
                turning_on=self.connection.seen_off,
            )
        )

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Close the connection."""
        await self._command(self.connection.async_disconnect("connected switch"))
