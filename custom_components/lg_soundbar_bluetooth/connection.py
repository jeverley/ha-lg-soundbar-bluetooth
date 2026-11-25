"""Tracks whether the soundbar is on, and connects to it when needed.

Connecting has side effects on an LG G1: it wakes the soundbar if it is off,
and switches it to Bluetooth if it is on. The soundbar also keeps only the
newest control connection, so connecting takes it from LG's app. Home
Assistant therefore tells whether the soundbar is on with a short Bluetooth
Classic scan, which has none of these effects, and only connects when asked
to (or, with auto-connect, when the soundbar comes on).
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
import contextlib
import logging
import time
from typing import Any

from bluetooth_classic import BluetoothClassic, BluetoothClassicError, ClassicDevice

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.util import dt as dt_util
from lg_soundbar_bluetooth import (
    LEVEL_COMMANDS,
    SETTING_FEATURES,
    SWITCH_COMMANDS,
    Feature,
    Function,
    LGSoundbar,
    LGSoundbarError,
    SoundbarState,
    current_function_name,
    function_for_name,
    offered_function_names,
    offered_sound_mode_names,
)

from .const import (
    CONF_AUTO_CONNECT,
    CONF_FEATURES,
    CONF_FLAGS,
    CONF_LAST_INPUT,
    CONF_MODEL,
    CONF_POWER_OFF,
    CONF_SCAN_INTERVAL,
    CONF_SOUND_MODES,
    CONF_SOURCES,
    CONF_TURN_ON_INPUT,
    DEFAULT_AUTO_CONNECT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TURN_ON_INPUT,
    DOMAIN,
    FEATURE_AUDIO_INFO,
    FEATURE_LEVELS,
    FEATURE_NIGHT_MODE,
    FEATURE_REAR_STATE,
    FEATURE_SLEEP_TIMER,
    FEATURE_SWITCHES,
    FEATURE_TONE,
    FEATURE_TONE_MIDDLE,
    FEATURE_WOOFER_STATE,
    SWITCH_ATTEMPTS,
    SWITCH_WAIT,
    TURN_ON_DEFAULT,
    TURN_ON_LAST,
)

_LOGGER = logging.getLogger(__name__)

# Recent events kept for diagnostics.
HISTORY_SIZE = 50


def features_from_state(
    state: SoundbarState, stored: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return the settings a soundbar offers, in config entry form.

    When the soundbar has sent its feature flags, they decide, as in the LG
    app; a reply that went missing then cannot drop a setting. Without the
    flags, the settings it answered for are added to those stored before, so
    one connection with a missed reply never shrinks the list. Extras with no
    flag of their own are kept once the soundbar has answered for them.
    """
    stored = stored or {}
    if (features := state.features) is not None:
        result: dict[str, Any] = {
            FEATURE_LEVELS: _flagged(LEVEL_COMMANDS, features),
            FEATURE_SWITCHES: _flagged(SWITCH_COMMANDS, features),
            FEATURE_NIGHT_MODE: Feature.NIGHT_MODE in features,
            FEATURE_TONE: Feature.TONE_CONTROL in features,
        }
    else:
        result = {
            FEATURE_LEVELS: sorted(
                set(stored.get(FEATURE_LEVELS, [])) | {int(c) for c in state.levels}
            ),
            FEATURE_SWITCHES: sorted(
                set(stored.get(FEATURE_SWITCHES, [])) | {int(c) for c in state.switches}
            ),
            FEATURE_NIGHT_MODE: _answered(stored, FEATURE_NIGHT_MODE, state.night_mode),
            FEATURE_TONE: _answered(stored, FEATURE_TONE, state.bass),
        }
    result[FEATURE_AUDIO_INFO] = _answered(
        stored, FEATURE_AUDIO_INFO, state.audio_info
    ) or bool(features and Feature.AUDIO_INFO in features)
    result[FEATURE_TONE_MIDDLE] = _answered(stored, FEATURE_TONE_MIDDLE, state.middle)
    # Offered as the LG app offers it, by the feature list; without one, if
    # the soundbar has answered for it.
    result[FEATURE_SLEEP_TIMER] = (
        state.sleep_timer_supported
        if state.sleep_timer_supported is not None
        else _answered(stored, FEATURE_SLEEP_TIMER, state.sleep_timer)
    )
    result[FEATURE_WOOFER_STATE] = (
        _answered(stored, FEATURE_WOOFER_STATE, state.woofer_connected)
        and state.asks_woofer_state
    )
    result[FEATURE_REAR_STATE] = (
        _answered(stored, FEATURE_REAR_STATE, state.rear_connected)
        and state.asks_rear_state
    )
    return result


def _answered(stored: dict[str, Any], key: str, value: object) -> bool:
    return bool(stored.get(key)) or value is not None


def _flagged(commands: frozenset, features: frozenset[int]) -> list[int]:
    return sorted(int(c) for c in commands if SETTING_FEATURES[c] in features)


async def async_find_soundbar(address: str) -> ClassicDevice | None:
    """Return the soundbar if it answers a short Classic scan, else None.

    A soundbar that is on answers within a few seconds, whatever input it is
    on and whatever is connected to it; one that is off never does, and the
    scan does not wake it.

    Raises BluetoothClassicError if BlueZ cannot be asked.
    """
    async with BluetoothClassic() as bluetooth:
        return await bluetooth.find_device_by_address(address)


def describe_scan(found: ClassicDevice | None, after: float) -> str:
    """Return a short explanation of a scan for logs and diagnostics."""
    if found is None:
        return "not seen"
    rssi = f", RSSI {found.rssi}" if found.rssi is not None else ""
    link = " (BlueZ had a link to it)" if found.connected else ""
    return f"seen after {after:.1f} s{rssi}{link}"


class LGSoundbarConnection:
    """Knows whether the soundbar is on, and connects to it on request.

    While not connected, a short scan every scan interval tells whether the
    soundbar is on. Commands connect first. Once connected, Home Assistant
    stays connected until the connection drops, then goes back to scanning;
    it never reconnects by itself, except with auto-connect when the
    soundbar comes on (or is on when Home Assistant starts).
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: LGSoundbar
    ) -> None:
        """Initialise the connection manager."""
        self.hass = hass
        self.entry = entry
        self.client = client
        # Whether the last scan saw the soundbar; None before the first.
        self._visible: bool | None = None
        # Whether scans are failing, to log that once rather than each time.
        self._scan_failing = False
        # Auto-connect only when the soundbar comes on (or at start-up), not
        # after a connection drops while it stays on, as when LG's app takes
        # it over.
        self._auto_armed = True
        self._power_off_requested = False
        # Set while Home Assistant closes the connection on request.
        self._disconnect_requested = False
        # The input after the connection settled, so later changes the
        # soundbar reports can be told from the ones connecting caused.
        self._settled_input: str | None = None
        self._reload_pending = False
        self._stopping = False
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._scan_task: asyncio.Task[None] | None = None
        self._callbacks: list[Callable[[], None]] = []
        # Recent scans, connections, input switches and drops, with why.
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_SIZE)
        self._remove_client_callback = client.register_callback(self._on_client_update)

    @property
    def is_on(self) -> bool:
        """Return whether the soundbar is on: connected, or seen by a scan."""
        return self.client.connected or bool(self._visible)

    def register_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Call callback when the soundbar's state or the connection changes."""
        self._callbacks.append(callback)

        def remove() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return remove

    @property
    def started(self) -> bool:
        """Return whether scanning has started, after the entities were set up."""
        return self._scan_task is not None

    @callback
    def start(self) -> None:
        """Start scanning for the soundbar."""
        self._scan_task = self.entry.async_create_background_task(
            self.hass, self._scan_loop(), "lg_soundbar_bluetooth scan"
        )

    async def stop(self) -> None:
        """Stop scanning and close the connection."""
        self._stopping = True
        self._remove_client_callback()
        if self._scan_task is not None:
            self._scan_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scan_task
            self._scan_task = None
        await self.client.disconnect()

    def _record(self, event: str, **details: Any) -> None:
        self.history.append(
            {
                "time": dt_util.utcnow().isoformat(timespec="milliseconds"),
                "event": event,
                **details,
            }
        )

    async def async_ensure_connected(
        self, reason: str, *, restore_input: bool = True, turning_on: bool = False
    ) -> None:
        """Connect if not connected, putting the input back as it should be.

        Connecting switches a soundbar that is on to Bluetooth, so it is
        switched back to the input it reported first. A soundbar woken by the
        connection is switched to the input chosen in the options instead.
        Reason says what asked for the connection, for logs and diagnostics.
        """
        async with self._lock:
            if self.client.connected:
                return
            seen_on = self._visible is True
            _LOGGER.debug(
                "Connecting to soundbar %s for %s (last scan: %s)",
                self.client.address,
                reason,
                "on" if seen_on else "off" if self._visible is False else "unknown",
            )
            try:
                await self.client.connect(keep_input=restore_input)
            except LGSoundbarError as err:
                _LOGGER.debug(
                    "Could not connect to soundbar %s for %s: %s (from %r)",
                    self.client.address,
                    reason,
                    err,
                    err.__cause__,
                )
                self._record(
                    "connect failed",
                    reason=reason,
                    error=str(err),
                    timings=self.client.timings,
                )
                raise
            self._visible = True
            self._auto_armed = False
            initial = current_function_name(
                self.client.initial_function, self.client.state.selectable_functions
            )
            now_on = self._current_source()
            _LOGGER.debug(
                "Connected to soundbar %s for %s; it reported %s first, now %s",
                self.client.address,
                reason,
                initial,
                now_on,
            )
            self._record(
                "connected",
                reason=reason,
                seen_on_before=seen_on,
                first_input=initial,
                input=now_on,
                moved_before_answering=self.client.moved_before_answering,
                timings=self.client.timings,
            )
            self.update_stored_details()
            # The input it reported before the connection moved it, unless
            # the connection woke it (it then starts on Bluetooth) or it moved
            # before answering (its Bluetooth is the connection's, not its own).
            if (
                self.client.initial_function is not None
                and not self.client.moved_before_answering
                and (self.client.initial_function != Function.BLUETOOTH or seen_on)
            ):
                self._remember_input(initial, "reported when connecting")
            if restore_input:
                await self._settle_input(seen_on, turning_on)
            self._settled_input = self._current_source()
        if self._reload_pending:
            # After the switch back, so the command that connected completes.
            self._reload_pending = False
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
        self._notify()

    async def async_turn_on(self) -> None:
        """Turn the soundbar on by connecting, which wakes it."""
        await self.async_ensure_connected("turn on", turning_on=True)

    async def async_turn_off(self) -> None:
        """Switch the soundbar off; it closes the connection as it does."""
        if not self.client.connected and self._visible is False:
            return
        # Switch back first: the soundbar remembers the input it was switched
        # off on, and connecting has just moved it to Bluetooth.
        await self.async_ensure_connected("turn off")
        self._power_off_requested = True
        try:
            await self.client.power_off()
        except Exception:
            self._power_off_requested = False
            raise

    async def async_disconnect(self, reason: str) -> None:
        """Close the connection, leaving the soundbar on its current input.

        It stays on: scanning carries on, and auto-connect waits until it has
        been seen off. Reason says what asked, for logs and diagnostics.
        """
        async with self._lock:
            if not self.client.connected:
                return
            _LOGGER.debug(
                "Disconnecting from soundbar %s for %s", self.client.address, reason
            )
            self._record("disconnect requested", reason=reason)
            self._disconnect_requested = True
            try:
                await self.client.disconnect()
            finally:
                self._disconnect_requested = False

    def _option(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    def _current_source(self) -> str | None:
        state = self.client.state
        return current_function_name(state.function, state.selectable_functions)

    async def _settle_input(self, seen_on: bool, turning_on: bool) -> None:
        """Switch away from the Bluetooth input a connection lands on."""
        state = self.client.state
        initial = self.client.initial_function
        restore = self.client.input_restore
        if initial is not None and initial != Function.BLUETOOTH and restore:
            # It was on: the library put back the input the connection moved
            # it from; record how.
            wanted = current_function_name(initial, state.selectable_functions)
            if not restore.moved:
                self._decided("stay", "the connection did not move it")
                return
            if restore.reached and restore.sent is not None and not restore.attempts:
                self._decided("stay", f"switched back to {wanted} while connecting")
                self._record("input switched", input=wanted, attempt=0)
                return
            why = (
                f"switching back while connecting did not take (sent {restore.sent:02x})"
                if restore.sent is not None
                else "it was on this input before the connection moved it"
            )
            self._decided(f"switch to {wanted}", why)
            if restore.reached:
                self._record("input switched", input=wanted, attempt=restore.attempts)
            else:
                _LOGGER.warning(
                    "Soundbar %s did not switch to %s", self.client.address, wanted
                )
                self._record(
                    "input not switched", input=wanted, now=self._current_source()
                )
            return
        if seen_on and self.client.moved_before_answering:
            # The input it was on is not known: it moved before answering.
            self._decided("stay", "it moved to Bluetooth before saying its input")
            return
        if seen_on:
            self._decided("stay", "it was on and already on Bluetooth")
            return
        elif not turning_on:
            # The last scan may be older than the soundbar being switched on
            # on Bluetooth, so only turning on applies the option.
            self._decided("stay", "on Bluetooth, and not turned on from Home Assistant")
            return
        else:
            wanted = self._option(CONF_TURN_ON_INPUT, DEFAULT_TURN_ON_INPUT)
            if wanted == TURN_ON_DEFAULT:
                self._decided("stay", "woken; input when turned on is Default")
                return
            if wanted == TURN_ON_LAST:
                last = self.entry.data.get(CONF_LAST_INPUT)
                if not last:
                    self._decided("stay", "woken; no last input known yet")
                    return
                wanted = last["input"]
                why = f"woken; last input ({last['how']}, since {last['since']})"
            else:
                why = "woken; chosen as the input when turned on"
        if not wanted or wanted == self._current_source():
            self._decided("stay", f"already on {wanted}")
            return
        self._decided(f"switch to {wanted}", why)
        try:
            function = function_for_name(wanted, state.selectable_functions)
        except ValueError:
            _LOGGER.warning("Soundbar %s has no input %s", self.client.address, wanted)
            return
        for attempt in range(1, SWITCH_ATTEMPTS + 1):
            _LOGGER.debug("Switching soundbar %s to %s", self.client.address, wanted)
            await self.client.select_function(function)
            if await self._wait_for_source(wanted):
                self._record("input switched", input=wanted, attempt=attempt)
                return
        _LOGGER.warning("Soundbar %s did not switch to %s", self.client.address, wanted)
        self._record("input not switched", input=wanted, now=self._current_source())

    def _remember_input(self, name: str | None, how: str) -> None:
        """Store the input the soundbar was seen on, for turning it on later."""
        if (
            not name
            or (self.entry.data.get(CONF_LAST_INPUT) or {}).get("input") == name
        ):
            return
        last = {
            "input": name,
            "since": dt_util.utcnow().isoformat(timespec="seconds"),
            "how": how,
        }
        _LOGGER.debug("Soundbar %s last input: %s (%s)", self.client.address, name, how)
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_LAST_INPUT: last}
        )

    def _decided(self, action: str, why: str) -> None:
        _LOGGER.debug("Soundbar %s input: %s (%s)", self.client.address, action, why)
        self._record("input decision", action=action, why=why)

    async def _wait_for_source(self, wanted: str) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SWITCH_WAIT
        while loop.time() < deadline:
            if self._current_source() == wanted:
                return True
            await asyncio.sleep(0.1)
        return self._current_source() == wanted

    async def _scan_loop(self) -> None:
        trigger = "start-up"
        while not self._stopping:
            if not self.client.connected:
                try:
                    await self._scan(trigger)
                except Exception:
                    # Keep scanning whatever went wrong: nothing restarts this.
                    _LOGGER.exception(
                        "Unexpected error scanning for soundbar %s",
                        self.client.address,
                    )
            self._wake.clear()
            trigger = "interval"
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(
                    self._option(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ):
                    await self._wake.wait()
                    trigger = "after disconnect"

    async def _scan(self, trigger: str) -> None:
        async with self._lock:
            if self.client.connected:
                return
            error: str | None = None
            found: ClassicDevice | None = None
            started = time.monotonic()
            try:
                found = await async_find_soundbar(self.client.address)
            except BluetoothClassicError as err:
                error = str(err)
            after = time.monotonic() - started
        description = (
            f"could not scan ({error})"
            if error is not None
            else describe_scan(found, after)
        )
        _LOGGER.debug(
            "Scan for soundbar %s (%s): %s",
            self.client.address,
            trigger,
            description,
        )
        self._record("scan", trigger=trigger, result=description)
        if error is not None and not self._scan_failing:
            self._scan_failing = True
            _LOGGER.warning(
                "Cannot tell whether soundbar %s is on: %s",
                self.client.address,
                error,
            )
        elif error is None and self._scan_failing:
            self._scan_failing = False
            _LOGGER.info(
                "Can tell whether soundbar %s is on again", self.client.address
            )
        if error is not None:
            return
        visible = found is not None
        previous = self._visible
        changed = visible != previous
        self._visible = visible
        if not visible:
            self._auto_armed = True
        elif self._auto_armed and self._option(CONF_AUTO_CONNECT, DEFAULT_AUTO_CONNECT):
            self._auto_armed = False
            reason = (
                "auto-connect: on at start-up"
                if previous is None
                else "auto-connect: came on"
            )
            self.entry.async_create_background_task(
                self.hass,
                self._auto_connect(reason),
                "lg_soundbar_bluetooth auto-connect",
            )
        if changed:
            _LOGGER.debug(
                "Soundbar %s is %s", self.client.address, "on" if visible else "off"
            )
            self._notify()

    async def _auto_connect(self, reason: str) -> None:
        try:
            await self.async_ensure_connected(reason)
        except LGSoundbarError as err:
            _LOGGER.debug(
                "Could not auto-connect to soundbar %s: %s", self.client.address, err
            )

    @callback
    def _update_emergency_issue(self) -> None:
        """Raise a repair while the soundbar is in emergency mode.

        A failed firmware update can leave a soundbar in emergency mode,
        which LG's app recovers with its recovery update; until then it
        offers nothing else. The repair goes once it reports normal mode.
        """
        issue_id = f"emergency_mode_{self.entry.entry_id}"
        emergency = self.client.state.emergency
        if emergency:
            self._record("emergency mode")
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="emergency_mode",
                translation_placeholders={"name": self.entry.title},
            )
        elif emergency is False:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def update_stored_details(self) -> None:
        """Store what the latest connection found and show it on the device."""
        state = self.client.state
        self._update_emergency_issue()
        data = dict(self.entry.data)
        data[CONF_FEATURES] = features_from_state(state, data.get(CONF_FEATURES))
        if state.features is not None:
            # Kept apart from the features, so a change does not reload.
            data[CONF_FLAGS] = sorted(state.features)
        if state.power_off_supported is not None:
            data[CONF_POWER_OFF] = state.power_off_supported
        if state.model:
            data[CONF_MODEL] = state.model
        if sources := offered_function_names(state.selectable_functions):
            data[CONF_SOURCES] = sources
        if sound_modes := offered_sound_mode_names(state.sound_modes):
            data[CONF_SOUND_MODES] = sound_modes
        features_changed = data[CONF_FEATURES] != self.entry.data.get(CONF_FEATURES)
        if data != self.entry.data:
            self.hass.config_entries.async_update_entry(self.entry, data=data)
        if features_changed and self.started:
            # Entities are created from the stored features; reload to add or
            # remove them, as after a firmware update.
            _LOGGER.info(
                "Soundbar %s reports different features; reloading",
                self.client.address,
            )
            self._reload_pending = True
        registry = dr.async_get(self.hass)
        # Looked up through the entry: identifiers are not unique across
        # config entries, and async_get_device by identifier is deprecated.
        identifier = (DOMAIN, self.client.address)
        device = next(
            (
                device
                for device in dr.async_entries_for_config_entry(
                    registry, self.entry.entry_id
                )
                if identifier in device.identifiers
            ),
            None,
        )
        if device is None:
            return
        changes: dict[str, Any] = {}
        if state.model and device.model != state.model:
            changes["model"] = state.model
        if state.firmware_version and device.sw_version != state.firmware_version:
            changes["sw_version"] = state.firmware_version
        if changes:
            registry.async_update_device(device.id, **changes)

    @callback
    def _on_client_update(self) -> None:
        if self.client.connected and self._settled_input is not None:
            # A change after the connection settled was made on the
            # soundbar, its remote or the TV.
            now_on = self._current_source()
            if now_on and now_on != self._settled_input:
                self._settled_input = now_on
                self._remember_input(now_on, "changed while connected")
        if not self.client.connected:
            self._settled_input = None
        if not self.client.connected and not self._stopping:
            # Dropped: the soundbar switched off, something else took it, or
            # the link failed. Scan rather than reconnect.
            self._auto_armed = False
            reason = self.client.close_reason
            details = {
                "how": repr(reason) if reason is not None else "closed cleanly",
                "after": (
                    f"{duration:.0f} s"
                    if (duration := self.client.last_duration) is not None
                    else None
                ),
                "input": self._current_source(),
                "turned_off_by_home_assistant": self._power_off_requested,
                "disconnected_by_home_assistant": self._disconnect_requested,
            }
            if self._power_off_requested:
                self._power_off_requested = False
                self._visible = False
                self._auto_armed = True
            else:
                self._wake.set()
            _LOGGER.debug(
                "Disconnected from soundbar %s after %s: %s (on %s%s)",
                self.client.address,
                details["after"],
                details["how"],
                details["input"],
                ", turned off by Home Assistant"
                if details["turned_off_by_home_assistant"]
                else ", disconnected by Home Assistant"
                if details["disconnected_by_home_assistant"]
                else "",
            )
            self._record("disconnected", **details)
        self._notify()

    @callback
    def _notify(self) -> None:
        for callback_ in list(self._callbacks):
            callback_()
