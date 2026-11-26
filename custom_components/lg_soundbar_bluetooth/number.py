"""Speaker level settings for LG Soundbars via Bluetooth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import (
    EntityCategory,
    Platform,
    UnitOfSoundPressure,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from lg_soundbar_bluetooth import (
    SLEEP_TIMER_CHOICES,
    Level,
    UtilityCommand,
    model_from_name,
)

from . import LGSoundbarConfigEntry
from .const import (
    CONF_FEATURES,
    CONF_MODEL,
    FEATURE_LEVELS,
    FEATURE_SLEEP_TIMER,
    FEATURE_TONE,
    FEATURE_TONE_MIDDLE,
)
from .entity import LGSoundbarEntity, async_remove_unoffered

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LGSoundbarNumberDescription(NumberEntityDescription):
    """Describes a soundbar level setting."""

    command: UtilityCommand
    # The soundbar counts in steps of this many units (AV sync is in 10 ms).
    scale: int = 1


DECIBEL = UnitOfSoundPressure.DECIBEL

NUMBERS: tuple[LGSoundbarNumberDescription, ...] = (
    LGSoundbarNumberDescription(
        key="woofer_level",
        translation_key="woofer_level",
        native_unit_of_measurement=DECIBEL,
        command=UtilityCommand.WOOFER_LEVEL,
    ),
    LGSoundbarNumberDescription(
        key="rear_level",
        translation_key="rear_level",
        native_unit_of_measurement=DECIBEL,
        command=UtilityCommand.REAR_LEVEL,
    ),
    LGSoundbarNumberDescription(
        key="center_level",
        translation_key="center_level",
        native_unit_of_measurement=DECIBEL,
        command=UtilityCommand.CENTER_LEVEL,
    ),
    LGSoundbarNumberDescription(
        key="side_level",
        translation_key="side_level",
        native_unit_of_measurement=DECIBEL,
        command=UtilityCommand.SIDE_LEVEL,
    ),
    LGSoundbarNumberDescription(
        key="overhead_level",
        translation_key="overhead_level",
        native_unit_of_measurement=DECIBEL,
        command=UtilityCommand.UPWARD_LEVEL,
    ),
    LGSoundbarNumberDescription(
        key="dialogue_level",
        translation_key="dialogue_level",
        command=UtilityCommand.DIALOG_CONTROL,
    ),
    LGSoundbarNumberDescription(
        key="av_sync",
        translation_key="av_sync",
        command=UtilityCommand.AV_SYNC,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        scale=10,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LGSoundbarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the level settings the soundbar reported."""
    features = entry.data.get(CONF_FEATURES, {})
    supported = set(features.get(FEATURE_LEVELS, []))
    entities: list[NumberEntity] = [
        LGSoundbarNumber(entry, description)
        for description in NUMBERS
        if description.command in supported
    ]
    unoffered = [d.key for d in NUMBERS if d.command not in supported]
    tone_bands = []
    if features.get(FEATURE_TONE):
        tone_bands = ["bass", "treble"]
        # As in the LG app: only soundbars that report three bands have a
        # middle band, and it is hidden on models with "q" in their name.
        # The model the soundbar reported, else the one in its Bluetooth
        # name; not the entry's title, which can be renamed.
        model = entry.data.get(CONF_MODEL) or model_from_name(entry.title) or ""
        if features.get(FEATURE_TONE_MIDDLE) and "q" not in model.lower():
            tone_bands.insert(1, "middle")
    entities += [LGSoundbarToneNumber(entry, band) for band in tone_bands]
    unoffered += [b for b in ("bass", "middle", "treble") if b not in tone_bands]
    if features.get(FEATURE_SLEEP_TIMER):
        entities.append(LGSoundbarSleepTimer(entry))
    else:
        unoffered.append("sleep_timer")
    async_remove_unoffered(hass, entry, Platform.NUMBER, unoffered)
    async_add_entities(entities)


class LGSoundbarNumber(LGSoundbarEntity, NumberEntity):
    """A level setting with the range the soundbar reports."""

    entity_description: LGSoundbarNumberDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self, entry: LGSoundbarConfigEntry, description: LGSoundbarNumberDescription
    ) -> None:
        """Initialise the setting."""
        super().__init__(entry, description.key)
        self.entity_description = description
        self._scale = description.scale
        self._attr_native_step = description.scale

    @property
    @override
    def available(self) -> bool:
        """Return whether the soundbar is connected and reported this level."""
        return super().available and self._level is not None

    @property
    def _level(self) -> Level | None:
        return self.client.state.levels.get(self.entity_description.command)

    @property
    @override
    def native_value(self) -> float | None:
        """Return the current level."""
        return None if (level := self._level) is None else level.value * self._scale

    @property
    @override
    def native_min_value(self) -> float:
        """Return the lowest level the soundbar allows."""
        return -6 if (level := self._level) is None else level.minimum * self._scale

    @property
    @override
    def native_max_value(self) -> float:
        """Return the highest level the soundbar allows."""
        return 6 if (level := self._level) is None else level.maximum * self._scale

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the level."""
        self._refuse_if_locked(
            self.client.state.locked_by(self.entity_description.command)
        )
        await self._command(
            self.client.set_level(
                self.entity_description.command, round(value / self._scale)
            )
        )


class LGSoundbarToneNumber(LGSoundbarEntity, NumberEntity):
    """A tone band; the bands are set together, as the soundbar takes them."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1
    _attr_native_unit_of_measurement = DECIBEL

    def __init__(self, entry: LGSoundbarConfigEntry, band: str) -> None:
        """Initialise the setting for "bass", "middle" or "treble"."""
        super().__init__(entry, band)
        self._band = band
        self._attr_translation_key = band

    @property
    def _tone(self) -> Level | None:
        return getattr(self.client.state, self._band)

    @property
    @override
    def available(self) -> bool:
        """Return whether the soundbar is connected and reported its tone."""
        return super().available and self._tone is not None

    @property
    @override
    def native_value(self) -> float | None:
        """Return the current value."""
        return None if (tone := self._tone) is None else tone.value

    @property
    @override
    def native_min_value(self) -> float:
        """Return the lowest value the soundbar allows."""
        return -5 if (tone := self._tone) is None else tone.minimum

    @property
    @override
    def native_max_value(self) -> float:
        """Return the highest value the soundbar allows."""
        return 5 if (tone := self._tone) is None else tone.maximum

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set this band, keeping the other as it is."""
        state = self.client.state
        bands = {
            band: 0 if (level := getattr(state, band)) is None else level.value
            for band in ("bass", "middle", "treble")
        }
        bands[self._band] = int(value)
        await self._command(self.client.set_tone(**bands))


class LGSoundbarSleepTimer(LGSoundbarEntity, NumberEntity):
    """Minutes until the soundbar turns itself off; 0 turns the timer off."""

    _attr_translation_key = "sleep_timer"
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    # The LG app offers 10 to 180 minutes; the soundbar counts down by the minute.
    _attr_native_max_value = max(SLEEP_TIMER_CHOICES)
    _attr_native_step = 1

    def __init__(self, entry: LGSoundbarConfigEntry) -> None:
        """Initialise the sleep timer."""
        super().__init__(entry, "sleep_timer")

    @property
    @override
    def available(self) -> bool:
        """Return whether connected, and the soundbar has a timer or reported one.

        As in the LG app, a soundbar whose feature list offers the timer has
        it; its value stays unknown until the soundbar reports it.
        """
        state = self.client.state
        return super().available and (
            state.sleep_timer is not None or bool(state.sleep_timer_supported)
        )

    @property
    @override
    def native_value(self) -> float | None:
        """Return the minutes left, or 0 when the timer is off."""
        return self.client.state.sleep_timer

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Start the timer, or turn it off with 0."""
        await self._command(self.client.set_sleep_timer(int(value)))
