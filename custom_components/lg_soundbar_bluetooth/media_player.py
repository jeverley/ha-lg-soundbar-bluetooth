"""Media player for LG Soundbars via Bluetooth."""

from __future__ import annotations

from typing import override

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
)
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from lg_soundbar_bluetooth import (
    SPECIAL_EQ_NAMES,
    current_function_name,
    function_for_name,
    offered_function_names,
    offered_sound_mode_names,
    sound_mode_for_name,
    sound_mode_name,
)

from . import LGSoundbarConfigEntry
from .const import CONF_POWER_OFF, CONF_SOUND_MODES, CONF_SOURCES, DOMAIN
from .entity import LGSoundbarEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LGSoundbarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the soundbar's media player."""
    async_add_entities([LGSoundbarMediaPlayer(entry)])


class LGSoundbarMediaPlayer(LGSoundbarEntity, MediaPlayerEntity):
    """The soundbar as a media player.

    On or off comes from the connection, or while not connected from a scan.
    While not connected, the volume, input and sound mode are not known and
    are left blank; using any control connects first, and turning on
    connects, which wakes the soundbar. The Connected switch shows
    whether Home Assistant is connected.
    """

    _attr_name = None
    # For its icon (icons.json); it takes the device's name.
    _attr_translation_key = "soundbar"
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.SELECT_SOUND_MODE
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.TURN_ON
    )

    def __init__(self, entry: LGSoundbarConfigEntry) -> None:
        """Initialise the media player."""
        super().__init__(entry, None)
        self._entry = entry

    @property
    @override
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return the controls; turning off only where the soundbar offers it.

        The LG app shows its power button only when the soundbar's feature
        list offers it; as last stored while not connected.
        """
        power_off = self.client.state.power_off_supported
        if power_off is None:
            power_off = self._entry.data.get(CONF_POWER_OFF, True)
        if power_off:
            return self._features
        return self._features & ~MediaPlayerEntityFeature.TURN_OFF

    @property
    @override
    def available(self) -> bool:
        """Stay available: commands connect when needed."""
        return True

    @property
    @override
    def state(self) -> MediaPlayerState:
        """Return whether the soundbar is on."""
        return MediaPlayerState.ON if self.connection.is_on else MediaPlayerState.OFF

    @property
    @override
    def volume_level(self) -> float | None:
        """Return the volume from 0 to 1."""
        state = self.client.state
        if not self.client.connected or state.volume is None or not state.volume_max:
            return None
        return state.volume / state.volume_max

    @property
    @override
    def is_volume_muted(self) -> bool | None:
        """Return whether the soundbar is muted."""
        return self.client.state.muted if self.client.connected else None

    @property
    @override
    def source(self) -> str | None:
        """Return the current input."""
        if not self.client.connected:
            return None
        state = self.client.state
        return current_function_name(state.function, state.selectable_functions)

    @property
    @override
    def source_list(self) -> list[str] | None:
        """Return the inputs the soundbar offers, as last stored if not connected."""
        if self.client.connected and (
            names := offered_function_names(self.client.state.selectable_functions)
        ):
            return names
        return self._entry.data.get(CONF_SOURCES) or None

    @property
    @override
    def sound_mode(self) -> str | None:
        """Return the sound mode, or the special mode overriding it.

        As in the LG app, Dolby Atmos, DTS:X or "Synced with TV" is shown
        while the soundbar has switched to it.
        """
        if not self.client.connected:
            return None
        state = self.client.state
        if (special := state.special_mode) is not None:
            return SPECIAL_EQ_NAMES[special]
        if state.sound_mode is None:
            return None
        return sound_mode_name(state.sound_mode)

    @property
    @override
    def sound_mode_list(self) -> list[str] | None:
        """Return the sound modes the soundbar offers, as last stored if not connected."""
        if self.client.connected and (
            names := offered_sound_mode_names(self.client.state.sound_modes)
        ):
            return names
        return self._entry.data.get(CONF_SOUND_MODES) or None

    async def _connect(self, reason: str) -> None:
        """Connect first if not connected; every command needs a connection."""
        await self._command(self.connection.async_ensure_connected(reason))

    @override
    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume from 0 to 1."""
        await self._connect("set volume")
        if (maximum := self.client.state.volume_max) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="volume_unknown"
            )
        await self._command(self.client.set_volume(round(volume * maximum)))

    @override
    async def async_volume_up(self) -> None:
        """Raise the volume by one step."""
        await self._step_volume(1)

    @override
    async def async_volume_down(self) -> None:
        """Lower the volume by one step."""
        await self._step_volume(-1)

    async def _step_volume(self, step: int) -> None:
        await self._connect("volume up" if step > 0 else "volume down")
        if (volume := self.client.state.volume) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="volume_unknown"
            )
        await self._command(self.client.set_volume(volume + step))

    @override
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        await self._connect("mute" if mute else "unmute")
        await self._command(self.client.set_mute(mute))

    @override
    async def async_select_source(self, source: str) -> None:
        """Select an input."""
        await self._connect(f"select source {source}")
        try:
            function = function_for_name(source, self.client.state.selectable_functions)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_source",
                translation_placeholders={"source": source},
            ) from err
        await self._command(self.client.select_function(function))

    @override
    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Select a sound mode, unless a special mode overrides it."""
        await self._connect(f"select sound mode {sound_mode}")
        self._refuse_if_locked(self.client.state.special_mode)
        try:
            mode = sound_mode_for_name(sound_mode, self.client.state.sound_modes)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_sound_mode",
                translation_placeholders={"sound_mode": sound_mode},
            ) from err
        await self._command(self.client.set_sound_mode(mode))

    @override
    async def async_turn_on(self) -> None:
        """Turn the soundbar on by connecting to it."""
        await self._command(self.connection.async_turn_on())

    @override
    async def async_turn_off(self) -> None:
        """Turn the soundbar off."""
        await self._command(self.connection.async_turn_off())
