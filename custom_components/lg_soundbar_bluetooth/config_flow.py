"""Config flow for LG Soundbars via Bluetooth.

The flow scans for soundbars with Bluetooth Classic, pairs with the chosen one
if it is not paired yet, then checks that it answers before creating the entry.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import contextlib
import logging
from typing import Any, override

from bluetooth_classic import (
    BluetoothClassic,
    BluetoothClassicError,
    ClassicDevice,
    DeviceNotFoundError,
    PairingError,
)
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from lg_soundbar_bluetooth import (
    BluetoothUnsupported,
    CannotConnect,
    LGSoundbar,
    is_lg_soundbar,
    normalize_address,
    offered_function_names,
    offered_sound_mode_names,
)

from .connection import features_from_state
from .const import (
    CONF_AUTO_CONNECT,
    CONF_CHANNEL,
    CONF_FEATURES,
    CONF_FLAGS,
    CONF_POWER_OFF,
    CONF_SCAN_INTERVAL,
    CONF_SOUND_MODES,
    CONF_SOURCES,
    CONF_TURN_ON_INPUT,
    DEFAULT_AUTO_CONNECT,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TURN_ON_INPUT,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    TURN_ON_DEFAULT,
    TURN_ON_LAST,
)

_LOGGER = logging.getLogger(__name__)


async def async_find_soundbars() -> list[ClassicDevice]:
    """Return LG soundbars known to BlueZ, after a scan.

    Paired soundbars come first. Returns an empty list if BlueZ is unavailable,
    so the user can still type an address.
    """
    try:
        async with BluetoothClassic() as bluetooth:
            try:
                await bluetooth.discover()
            except BluetoothClassicError as err:
                _LOGGER.warning("Bluetooth scan failed: %s", err)
            devices = await bluetooth.devices()
    except BluetoothClassicError as err:
        _LOGGER.warning("Could not list Bluetooth devices from BlueZ: %s", err)
        return []
    _LOGGER.debug("BlueZ knows %s devices", len(devices))
    soundbars = []
    for device in devices:
        soundbar = is_lg_soundbar(device.name, device.uuids, paired=device.paired)
        _LOGGER.debug(
            "Device %s name=%r paired=%s soundbar=%s services=%s",
            device.address,
            device.name,
            device.paired,
            soundbar,
            sorted(device.uuids),
        )
        if soundbar:
            soundbars.append(device)
    return sorted(soundbars, key=lambda d: (not d.paired, (d.name or "").lower()))


async def async_ensure_paired(address: str) -> ClassicDevice:
    """Pair with the soundbar and trust it, unless that is already done.

    Raises DeviceNotFoundError if BlueZ does not find it, PairingError if
    pairing fails, and BluetoothClassicError if BlueZ cannot be reached.
    """
    async with BluetoothClassic() as bluetooth:
        if await bluetooth.device(address) is None:
            # Not seen yet; look for it before pairing.
            with contextlib.suppress(BluetoothClassicError):
                await bluetooth.discover()
        device = await bluetooth.pair(address)
        return await bluetooth.trust(device.address)


async def async_ensure_trusted(address: str) -> None:
    """Trust an already paired soundbar, if BlueZ can be reached.

    Soundbars paired outside Home Assistant may not be trusted, and then
    drop the control connection. Failures are only logged: the connection
    attempt that follows shows whether it mattered.
    """
    try:
        async with BluetoothClassic() as bluetooth:
            device = await bluetooth.device(address)
            if device is not None and device.paired and not device.trusted:
                _LOGGER.debug("Trusting %s", address)
                await bluetooth.trust(address)
    except BluetoothClassicError as err:
        _LOGGER.debug("Could not check whether %s is trusted: %s", address, err)


class LGSoundbarBluetoothConfigFlow(ConfigFlow, domain=DOMAIN):
    """Find, pair and set up an LG soundbar."""

    VERSION = 1
    # 2: the unused last_source and powered_off keys are removed.
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return LGSoundbarBluetoothOptionsFlow()

    def __init__(self) -> None:
        """Initialise the flow."""
        self._found: list[ClassicDevice] = []
        self._address: str | None = None
        self._name: str | None = None
        self._scan_task: asyncio.Task[list[ClassicDevice]] | None = None
        self._pair_task: asyncio.Task[ClassicDevice] | None = None
        self._pair_error: str | None = None
        self._channel: int | None = None
        # What the connection found, kept for the options step.
        self._data: dict[str, Any] | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to make the soundbar discoverable before scanning."""
        if user_input is None:
            return self.async_show_form(step_id="user")
        return await self.async_step_scan()

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Scan for soundbars."""
        if self._scan_task is None:
            self._scan_task = self.hass.async_create_task(async_find_soundbars())
        if not self._scan_task.done():
            return self.async_show_progress(
                step_id="scan",
                progress_action="scanning",
                progress_task=self._scan_task,
            )
        self._found = self._scan_task.result()
        self._scan_task = None
        return self.async_show_progress_done(next_step_id="pick")

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose a soundbar, or type its address."""
        errors: dict[str, str] = {}
        # When the scan finishes at once (for example, BlueZ is unreachable),
        # Home Assistant hands this step the previous form's empty input.
        if user_input and CONF_ADDRESS in user_input:
            try:
                address = normalize_address(user_input[CONF_ADDRESS])
            except ValueError:
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                self._address = address
                found = next((d for d in self._found if d.address == address), None)
                self._name = found.name if found else None
                if found is not None and found.paired:
                    return await self.async_step_connect()
                return await self.async_step_pair()

        configured = self._async_current_ids(include_ignore=False)
        choices = [d for d in self._found if d.address not in configured]
        if choices:
            selector: SelectSelector | TextSelector = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(
                            value=d.address,
                            label=f"{d.name or 'Unknown'} ({d.address})",
                        )
                        for d in choices
                    ],
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            selector = TextSelector()
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): selector}),
            errors=errors,
            description_placeholders={"count": str(len(choices))},
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair with the soundbar, after the user puts it in pairing mode."""
        assert self._address is not None
        if self._pair_task is not None and self._pair_task.done():
            task, self._pair_task = self._pair_task, None
            try:
                device = task.result()
            except (DeviceNotFoundError, PairingError) as err:
                _LOGGER.debug("Pairing with %s failed: %s", self._address, err)
                self._pair_error = "pairing_failed"
            except BluetoothClassicError as err:
                # Without BlueZ the soundbar can't be paired from here, but it
                # may already be paired outside Home Assistant; try anyway.
                _LOGGER.debug("BlueZ unavailable, skipping pairing: %s", err)
                self._pair_error = None
                return self.async_show_progress_done(next_step_id="connect")
            else:
                self._name = device.name or self._name
                self._pair_error = None
                return self.async_show_progress_done(next_step_id="connect")
            return self.async_show_progress_done(next_step_id="pair")

        if self._pair_task is None and user_input is None:
            errors = {"base": self._pair_error} if self._pair_error else {}
            return self.async_show_form(
                step_id="pair",
                errors=errors,
                description_placeholders={"name": self._display_name},
            )

        if self._pair_task is None:
            self._pair_task = self.hass.async_create_task(
                async_ensure_paired(self._address)
            )
        return self.async_show_progress(
            step_id="pair",
            progress_action="pairing",
            progress_task=self._pair_task,
            description_placeholders={"name": self._display_name},
        )

    async def async_step_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect to the soundbar and read what it supports."""
        assert self._address is not None
        await async_ensure_trusted(self._address)
        client = LGSoundbar(self._address, self._channel)
        try:
            await client.connect()
        except BluetoothUnsupported:
            return self.async_abort(reason="bluetooth_unsupported")
        except CannotConnect as err:
            _LOGGER.debug("Could not connect to %s: %s", self._address, err)
            # Reuse a channel the lookup found, as it does not always answer.
            self._channel = client.channel
            return self.async_show_form(
                step_id="connect",
                errors={"base": "cannot_connect"},
                description_placeholders={"name": self._display_name},
            )
        except Exception:
            _LOGGER.exception("Unexpected error connecting to %s", self._address)
            return self.async_show_form(
                step_id="connect",
                errors={"base": "unknown"},
                description_placeholders={"name": self._display_name},
            )
        data = {
            CONF_ADDRESS: self._address,
            CONF_CHANNEL: client.channel,
            CONF_FEATURES: features_from_state(client.state),
        }
        if (flags := client.state.features) is not None:
            data[CONF_FLAGS] = sorted(flags)
        if (power_off := client.state.power_off_supported) is not None:
            data[CONF_POWER_OFF] = power_off
        if sources := offered_function_names(client.state.selectable_functions):
            data[CONF_SOURCES] = sources
        if sound_modes := offered_sound_mode_names(client.state.sound_modes):
            data[CONF_SOUND_MODES] = sound_modes
        await client.disconnect()
        self._data = data
        return await self.async_step_options()

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the options before the soundbar is added."""
        assert self._data is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._name or DEFAULT_NAME, data=self._data, options=user_input
            )
        return self.async_show_form(
            step_id="options",
            data_schema=options_schema(self._data.get(CONF_SOURCES) or [], {}),
            description_placeholders={"name": self._display_name},
        )

    @property
    def _display_name(self) -> str:
        return self._name or self._address or DEFAULT_NAME


def options_schema(sources: list[str], current: Mapping[str, Any]) -> vol.Schema:
    """Return the options form, with the current choices as defaults."""
    # The inputs are stored on each connection, so they are known while the
    # soundbar is off.
    choices = [
        SelectOptionDict(value=TURN_ON_LAST, label=TURN_ON_LAST),
        SelectOptionDict(value=TURN_ON_DEFAULT, label=TURN_ON_DEFAULT),
        *(SelectOptionDict(value=source, label=source) for source in sources),
    ]
    turn_on_input = current.get(CONF_TURN_ON_INPUT, DEFAULT_TURN_ON_INPUT)
    if turn_on_input not in (TURN_ON_LAST, TURN_ON_DEFAULT, *sources):
        turn_on_input = DEFAULT_TURN_ON_INPUT
    return vol.Schema(
        {
            vol.Required(CONF_TURN_ON_INPUT, default=turn_on_input): SelectSelector(
                SelectSelectorConfig(
                    options=choices,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_TURN_ON_INPUT,
                )
            ),
            vol.Required(
                CONF_AUTO_CONNECT,
                default=current.get(CONF_AUTO_CONNECT, DEFAULT_AUTO_CONNECT),
            ): BooleanSelector(),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(
                NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Coerce(int),
            ),
        }
    )


class LGSoundbarBluetoothOptionsFlow(OptionsFlow):
    """Choose how Home Assistant connects and which input to wake on."""

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=options_schema(
                self.config_entry.data.get(CONF_SOURCES) or [],
                self.config_entry.options,
            ),
        )
