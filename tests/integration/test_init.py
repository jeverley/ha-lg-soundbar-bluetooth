"""Tests for setting up the integration and its entities."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from lg_soundbar_bluetooth import (
    Feature,
    SoundbarState,
)
from lg_soundbar_bluetooth.testing import ADDRESS, FakeSoundbar, Frame
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lg_soundbar_bluetooth.connection import features_from_state
from custom_components.lg_soundbar_bluetooth.const import (
    CONF_AUTO_CONNECT,
    CONF_FLAGS,
    CONF_LAST_INPUT,
    CONF_MODEL,
    CONF_POWER_OFF,
    CONF_SCAN_INTERVAL,
    CONF_SOUND_MODES,
    CONF_SOURCES,
    CONF_TURN_ON_INPUT,
    DOMAIN,
    TURN_ON_DEFAULT,
)
from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    ATTR_SOUND_MODE,
    DOMAIN as MP_DOMAIN,
    SERVICE_SELECT_SOUND_MODE,
    SERVICE_SELECT_SOURCE,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ADDRESS,
    EVENT_HOMEASSISTANT_STOP,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)

from .conftest import FEATURES

MEDIA_PLAYER = "media_player.lg_g1_xx"
WOOFER = "number.lg_g1_xx_woofer_level"
AV_SYNC = "number.lg_g1_xx_av_sync"
DRC = "switch.lg_g1_xx_dynamic_range_control"
AUTO_POWER = "switch.lg_g1_xx_auto_power"
NIGHT = "switch.lg_g1_xx_night_time"
LINK = "binary_sensor.lg_g1_xx_bluetooth"


async def setup(
    hass: HomeAssistant, entry: MockConfigEntry, *, connected: bool = True
) -> None:
    """Set up, and with auto-connect wait for the connection it makes."""
    if entry.entry_id not in (e.entry_id for e in hass.config_entries.async_entries()):
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if connected:
        await wait_for(lambda: entry.runtime_data.client.connected)


def update(hass: HomeAssistant, entry: MockConfigEntry, **changes) -> None:
    """Change the entry, adding it to Home Assistant first if needed."""
    if entry.entry_id not in (e.entry_id for e in hass.config_entries.async_entries()):
        entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, **changes)


async def wait_for(condition, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "timed out"
        await asyncio.sleep(0.02)
    await asyncio.sleep(0)


async def test_entities_reflect_soundbar(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    state = hass.states.get(MEDIA_PLAYER)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_MEDIA_VOLUME_LEVEL] == 15 / 40
    # The G1 reports HDMI eARC, shown as the input it offers for it.
    assert state.attributes[ATTR_INPUT_SOURCE] == "Optical/HDMI ARC"
    assert state.attributes["source_list"] == [
        "Bluetooth",
        "HDMI",
        "LG TV",
        "Optical/HDMI ARC",
        "USB",
    ]
    assert state.attributes[ATTR_SOUND_MODE] == "AI Sound Pro"
    assert state.attributes["sound_mode_list"] == [
        "AI Sound Pro",
        "Bass Blast",
        "Movie",
        "Music",
        "Standard",
    ]

    woofer = hass.states.get(WOOFER)
    assert woofer.state == "0"
    assert (woofer.attributes["min"], woofer.attributes["max"]) == (-15, 6)
    assert woofer.attributes["unit_of_measurement"] == "dB"
    assert hass.states.get("number.lg_g1_xx_rear_level").state == "-3"
    av_sync = hass.states.get(AV_SYNC)
    assert (av_sync.attributes["max"], av_sync.attributes["step"]) == (300, 10)
    assert av_sync.attributes["unit_of_measurement"] == "ms"

    assert hass.states.get(DRC).state == STATE_OFF
    assert hass.states.get(AUTO_POWER).state == STATE_ON
    assert hass.states.get("switch.lg_g1_xx_surround_sound").state == STATE_ON
    assert hass.states.get(NIGHT).state == STATE_OFF

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, ADDRESS)})
    assert (device.manufacturer, device.model) == ("LG Electronics", "G1")


async def test_services_send_commands(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    mock_client.sent.clear()

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: MEDIA_PLAYER, ATTR_MEDIA_VOLUME_LEVEL: 0.5},
        blocking=True,
    )
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_VOLUME_MUTE,
        {ATTR_ENTITY_ID: MEDIA_PLAYER, ATTR_MEDIA_VOLUME_MUTED: True},
        blocking=True,
    )
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_SELECT_SOUND_MODE,
        {ATTR_ENTITY_ID: MEDIA_PLAYER, ATTR_SOUND_MODE: "Movie"},
        blocking=True,
    )
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: WOOFER, "value": -3}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: AV_SYNC, "value": 120}, blocking=True
    )
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {ATTR_ENTITY_ID: MEDIA_PLAYER, ATTR_INPUT_SOURCE: "Bluetooth"},
        blocking=True,
    )
    # Let the soundbar's report of the new input arrive.
    await asyncio.sleep(0.01)
    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: NIGHT}, blocking=True
    )
    await hass.async_block_till_done()

    assert mock_client.sent[:6] == [
        Frame(0xC4, 0x02, bytes([40, 20])),
        Frame(0xC4, 0x1D, b"\x01"),
        Frame(0xC4, 0x1F, b"\x00\x89"),
        Frame(0x0D, 0x1B, b"\xfd"),
        Frame(0x0D, 0x1A, b"\x0c"),
        Frame(0x00, 0x01, b"\x07"),
    ]
    # After the input change, commands go to the newly reported input.
    assert Frame(0x07, 0x4A, b"\x01") in mock_client.sent
    state = hass.states.get(MEDIA_PLAYER)
    assert state.attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.5
    assert state.attributes[ATTR_SOUND_MODE] == "Movie"
    assert state.attributes[ATTR_INPUT_SOURCE] == "Bluetooth"
    assert hass.states.get(AV_SYNC).state == "120"
    assert hass.states.get(NIGHT).state == STATE_ON


async def test_a_dropped_connection_is_not_reconnected(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    update(
        hass, config_entry, options={CONF_AUTO_CONNECT: True, CONF_SCAN_INTERVAL: 0.05}
    )
    await setup(hass, config_entry)
    mock_client.transport.close()
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    # Still on, by the scans, but Home Assistant waits to be asked.
    assert mock_client.connections == 1
    player = hass.states.get(MEDIA_PLAYER)
    assert player.state == STATE_ON
    assert ATTR_MEDIA_VOLUME_LEVEL not in player.attributes
    assert hass.states.get(WOOFER).state == STATE_UNAVAILABLE

    # Using it connects.
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: MEDIA_PLAYER, ATTR_MEDIA_VOLUME_LEVEL: 0.3},
        blocking=True,
    )
    assert mock_client.connections == 2
    # 30% of the fake's maximum of 40.
    assert mock_client.volume == 12
    assert hass.states.get(WOOFER).state == "0"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_setup_while_off_uses_stored_features(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.off = True
    await setup(hass, config_entry, connected=False)
    assert config_entry.state is ConfigEntryState.LOADED
    # Not woken: a scan finds it off, so even auto-connect leaves it.
    assert mock_client.connections == 0
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    assert hass.states.get(DRC).state == STATE_UNAVAILABLE
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_keys_of_earlier_versions_are_removed(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="LG G1(XX)",
        unique_id=ADDRESS,
        version=1,
        minor_version=1,
        data={
            CONF_ADDRESS: ADDRESS,
            "channel": 2,
            "features": dict(FEATURES),
            "last_source": "Optical/HDMI ARC",
            "powered_off": False,
        },
    )
    await setup(hass, entry, connected=False)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 2
    assert "last_source" not in entry.data
    assert "powered_off" not in entry.data
    assert entry.data["channel"] == 2
    await hass.config_entries.async_unload(entry.entry_id)


async def test_an_entry_from_a_newer_version_is_not_loaded(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, version=2, data={CONF_ADDRESS: ADDRESS}
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_emergency_mode_raises_a_repair_until_recovered(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    issue_id = f"emergency_mode_{config_entry.entry_id}"
    mock_client.emergency = True
    await setup(hass, config_entry)
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "emergency_mode"
    await hass.config_entries.async_unload(config_entry.entry_id)

    # Recovered with LG's app: the repair goes on the next connection.
    mock_client.emergency = False
    await setup(hass, config_entry)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_feature_flags_are_remembered_for_the_next_start(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    flags = config_entry.data[CONF_FLAGS]
    # Optical/HDMI ARC combined, byte 3 bit 6.
    assert 3 * 8 + 6 in flags
    await hass.config_entries.async_unload(config_entry.entry_id)

    mock_client.off = True
    await setup(hass, config_entry, connected=False)
    assert config_entry.runtime_data.client.known_features == frozenset(flags)
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_turn_off_only_when_the_feature_list_offers_it(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    features = hass.states.get(MEDIA_PLAYER).attributes["supported_features"]
    assert features & MediaPlayerEntityFeature.TURN_OFF
    await hass.config_entries.async_unload(config_entry.entry_id)

    mock_client.feature_list = (
        mock_client.feature_list[:2] + b"\x00" + mock_client.feature_list[3:]
    )
    await setup(hass, config_entry)
    assert config_entry.data[CONF_POWER_OFF] is False
    features = hass.states.get(MEDIA_PLAYER).attributes["supported_features"]
    assert not features & MediaPlayerEntityFeature.TURN_OFF
    await hass.config_entries.async_unload(config_entry.entry_id)


def test_speaker_state_sensors_follow_the_flags() -> None:
    # Answered before, but the flags now say the state is not asked for.
    state = SoundbarState(features=frozenset({Feature.REAR_LEVEL}))
    stored = {"woofer_state": True, "rear_state": True}
    features = features_from_state(state, stored)
    assert features["woofer_state"] is False
    assert features["rear_state"] is True


async def test_device_model_comes_from_the_firmware(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_client.model = "G1X"
    await setup(hass, config_entry)
    device = device_registry.async_get_device(identifiers={(DOMAIN, ADDRESS)})
    assert device.model == "G1X"
    assert config_entry.data[CONF_MODEL] == "G1X"
    await hass.config_entries.async_unload(config_entry.entry_id)

    # Remembered for when the soundbar is off at start-up.
    device_registry.async_update_device(device.id, model=None)
    mock_client.off = True
    await setup(hass, config_entry, connected=False)
    device = device_registry.async_get_device(identifiers={(DOMAIN, ADDRESS)})
    assert device.model == "G1X"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_device_model_falls_back_to_the_bluetooth_name(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_client.off = True
    await setup(hass, config_entry, connected=False)
    device = device_registry.async_get_device(identifiers={(DOMAIN, ADDRESS)})
    assert device.model == "G1"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_setup_retries_without_stored_features(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"address": "AA:BB:CC:DD:EE:FF", "channel": 2}
    )
    mock_client.silent = True
    entry.add_to_hass(hass)
    with patch(
        "lg_soundbar_bluetooth.client.HANDSHAKE_TIMEOUT",
        0.05,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_optical_hdmi_arc_is_selected_as_one_input(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.function = 0x07
    await setup(hass, config_entry)
    assert hass.states.get(MEDIA_PLAYER).attributes[ATTR_INPUT_SOURCE] == "Bluetooth"
    mock_client.sent.clear()

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {ATTR_ENTITY_ID: MEDIA_PLAYER, ATTR_INPUT_SOURCE: "Optical/HDMI ARC"},
        blocking=True,
    )
    await asyncio.sleep(0.01)
    await hass.async_block_till_done()

    # The LG app selects it with 0xdf; the G1 then reports HDMI eARC (0xc4).
    assert mock_client.sent[0] == Frame(0x00, 0x01, b"\xdf")
    state = hass.states.get(MEDIA_PLAYER)
    assert state.attributes[ATTR_INPUT_SOURCE] == "Optical/HDMI ARC"
    assert "Optical" not in state.attributes["source_list"]


async def test_settings_the_soundbar_does_not_offer_are_removed(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    # Earlier versions created these for every setting the soundbar answered.
    for platform, key in (
        ("switch", "auto_display"),
        ("switch", "neural_x"),
        ("number", "overhead_level"),
    ):
        entity_registry.async_get_or_create(
            platform,
            DOMAIN,
            f"{ADDRESS}_{key}",
            config_entry=config_entry,
            suggested_object_id=f"lg_g1_xx_{key}",
        )

    await setup(hass, config_entry)

    for entity_id in (
        "switch.lg_g1_xx_auto_display",
        "switch.lg_g1_xx_neural_x",
        "number.lg_g1_xx_overhead_level",
    ):
        assert entity_registry.async_get(entity_id) is None
        assert hass.states.get(entity_id) is None
    assert hass.states.get(DRC) is not None
    assert hass.states.get(WOOFER) is not None


async def test_volume_commands_need_a_known_volume(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    state = config_entry.runtime_data.client.state
    state.volume = None
    state.volume_max = None
    mock_client.sent.clear()

    for service, data in (
        (SERVICE_VOLUME_SET, {ATTR_MEDIA_VOLUME_LEVEL: 0.7}),
        ("volume_up", {}),
    ):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                MP_DOMAIN,
                service,
                {ATTR_ENTITY_ID: MEDIA_PLAYER, **data},
                blocking=True,
            )
    assert mock_client.sent == []


@pytest.mark.parametrize(
    ("service", "data"),
    [
        (SERVICE_SELECT_SOURCE, {ATTR_INPUT_SOURCE: "HDMI 9"}),
        (SERVICE_SELECT_SOURCE, {ATTR_INPUT_SOURCE: "Unknown (300)"}),
        (SERVICE_SELECT_SOUND_MODE, {ATTR_SOUND_MODE: "Disco"}),
    ],
)
async def test_unknown_names_raise_a_validation_error(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    service: str,
    data: dict,
) -> None:
    await setup(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            MP_DOMAIN, service, {ATTR_ENTITY_ID: MEDIA_PLAYER, **data}, blocking=True
        )


async def test_extras_from_a_g1(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup(hass, config_entry)

    assert hass.states.get("number.lg_g1_xx_bass").state == "0"
    assert hass.states.get("number.lg_g1_xx_treble").attributes["max"] == 5
    assert hass.states.get("binary_sensor.lg_g1_xx_bluetooth").state == STATE_ON
    assert hass.states.get("binary_sensor.lg_g1_xx_input_connected") is None
    assert hass.states.get("binary_sensor.lg_g1_xx_subwoofer").state == STATE_ON
    # A G1 answers none of these, so they are not created.
    assert hass.states.get("number.lg_g1_xx_sleep_timer") is None
    assert hass.states.get("binary_sensor.lg_g1_xx_rear_speakers") is None
    assert hass.states.get("sensor.lg_g1_xx_audio_format") is None
    device = device_registry.async_get_device(identifiers={(DOMAIN, ADDRESS)})
    assert device.sw_version == "MICOM M2103110, MAIN B210414A"

    mock_client.sent.clear()
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.lg_g1_xx_bass", "value": 3},
        blocking=True,
    )
    await asyncio.sleep(0.01)
    assert mock_client.sent[:1] == [Frame(0xC4, 0x1F, bytes([0x03, 0x03, 0x00]))]
    assert hass.states.get("number.lg_g1_xx_bass").state == "3"


async def test_sleep_timer_when_the_soundbar_has_one(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    # Offered by the feature list (byte 1), as the LG app offers it. The
    # timer is not asked for, so it is unknown until the soundbar reports it.
    mock_client.sleep_timer = 0
    mock_client.feature_list = (
        mock_client.feature_list[:1] + b"\x01" + mock_client.feature_list[2:]
    )
    await setup(hass, config_entry)
    # Learned on connecting, after the entities were set up: a reload adds it.
    await wait_for(lambda: hass.states.get("number.lg_g1_xx_sleep_timer"))
    await wait_for(lambda: config_entry.runtime_data.client.connected)
    await wait_for(
        lambda: hass.states.get("number.lg_g1_xx_sleep_timer").state == "unknown"
    )
    assert not [f for f in mock_client.sent if (f.major, f.minor) == (0x0D, 0x14)]

    mock_client.sent.clear()
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.lg_g1_xx_sleep_timer", "value": 60},
        blocking=True,
    )
    await asyncio.sleep(0.01)
    assert mock_client.sent[:1] == [Frame(0x0D, 0x14, bytes([0x01, 60]))]
    assert hass.states.get("number.lg_g1_xx_sleep_timer").state == "60"


async def test_audio_format_when_the_soundbar_reports_it(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.audio_info = "Dolby Atmos"
    # Asked for only with its flag (byte 9 bit 2), which a G1 does not set.
    flags = bytearray(mock_client.feature_flags)
    flags[9] |= 0x04
    mock_client.feature_flags = bytes(flags)
    update(
        hass,
        config_entry,
        data={
            **config_entry.data,
            "features": {**config_entry.data["features"], "audio_info": True},
        },
    )
    await setup(hass, config_entry)
    assert hass.states.get("sensor.lg_g1_xx_audio_format").state == "Dolby Atmos"


async def test_bluetooth_connection_shows_a_dropped_link(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    mock_client.transport.close()
    await asyncio.sleep(0.01)
    await hass.async_block_till_done()
    link = hass.states.get("binary_sensor.lg_g1_xx_bluetooth")
    assert link.state == STATE_OFF
    assert hass.states.get("binary_sensor.lg_g1_xx_subwoofer").state == (
        STATE_UNAVAILABLE
    )
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_middle_band_on_a_three_band_soundbar(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.three_band = True
    update(
        hass,
        config_entry,
        data={
            **config_entry.data,
            "features": {**config_entry.data["features"], "tone_middle": True},
        },
    )
    await setup(hass, config_entry)

    assert hass.states.get("number.lg_g1_xx_middle").state == "0"
    mock_client.sent.clear()
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.lg_g1_xx_middle", "value": -2},
        blocking=True,
    )
    # A three-band soundbar takes all three bands.
    assert mock_client.sent[0] == Frame(0xC4, 0x1F, bytes([0x01, 0x00, 0xFE, 0x00]))


async def test_middle_band_is_hidden_on_q_models(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="LG QP5",
        unique_id=ADDRESS,
        data={
            "address": ADDRESS,
            "channel": 2,
            "features": {
                "levels": [],
                "switches": [],
                "tone": True,
                "tone_middle": True,
            },
        },
    )
    mock_client.three_band = True
    await setup(hass, entry, connected=False)
    assert hass.states.get("number.lg_qp5_bass") is not None
    assert hass.states.get("number.lg_qp5_middle") is None


async def test_a_dropped_connection_is_logged_once(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await setup(hass, config_entry)
    mock_client.transport.close()
    await asyncio.sleep(0.01)
    await hass.async_block_till_done()
    assert caplog.text.count("Disconnected from soundbar") == 1
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_dolby_atmos_overrides_sound_mode_and_locks_settings(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.special_eq = 1
    await setup(hass, config_entry)

    state = hass.states.get(MEDIA_PLAYER)
    assert state.attributes[ATTR_SOUND_MODE] == "Dolby Atmos"
    mock_client.sent.clear()
    for domain, service, data in (
        (
            MP_DOMAIN,
            SERVICE_SELECT_SOUND_MODE,
            {ATTR_ENTITY_ID: MEDIA_PLAYER, ATTR_SOUND_MODE: "Music"},
        ),
        ("switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: "switch.lg_g1_xx_auto_volume"}),
        ("switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: NIGHT}),
        (
            "number",
            "set_value",
            {ATTR_ENTITY_ID: "number.lg_g1_xx_dialog_control", "value": 3},
        ),
    ):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(domain, service, data, blocking=True)
    assert mock_client.sent == []
    # Settings Dolby Atmos does not lock still work.
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: WOOFER, "value": -3}, blocking=True
    )
    assert mock_client.sent == [Frame(0x0D, 0x1B, b"\xfd")]


async def test_synced_with_tv_locks_speaker_levels(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.special_eq = 3
    await setup(hass, config_entry)
    assert hass.states.get(MEDIA_PLAYER).attributes[ATTR_SOUND_MODE] == "Synced with TV"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: "number.lg_g1_xx_rear_level", "value": 0},
            blocking=True,
        )


async def test_the_disconnect_button_of_earlier_versions_is_removed(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "button", DOMAIN, f"{ADDRESS}_disconnect", config_entry=config_entry
    )
    await setup(hass, config_entry)
    assert (
        entity_registry.async_get_entity_id("button", DOMAIN, f"{ADDRESS}_disconnect")
        is None
    )
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_stopping_home_assistant_closes_the_connection(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    transport = mock_client.transport
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert transport.closed
    assert mock_client.connections == 1
    await hass.config_entries.async_unload(config_entry.entry_id)


async def turn_on(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        MP_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
    )
    await hass.async_block_till_done()


async def setup_switched_off(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    turn_on_input: str | None = None,
) -> None:
    options = {CONF_AUTO_CONNECT: True, CONF_SCAN_INTERVAL: 0.05}
    if turn_on_input:
        options[CONF_TURN_ON_INPUT] = turn_on_input
    update(hass, config_entry, options=options)
    await setup(hass, config_entry)
    mock_client.switch_off()
    await wait_for(lambda: hass.states.get(MEDIA_PLAYER).state == STATE_OFF)
    mock_client.sent.clear()


async def test_switched_off_soundbar_is_left_off_until_turned_on(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup_switched_off(hass, mock_client, config_entry, TURN_ON_DEFAULT)
    await asyncio.sleep(0.2)
    # Not reconnected: that would wake it.
    assert mock_client.connections == 1
    assert hass.states.get(WOOFER).state == STATE_UNAVAILABLE

    # Still left alone after a restart.
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.sleep(0.1)
    assert mock_client.connections == 1
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF

    # Turning on wakes it on Bluetooth, and with Default leaves it there.
    await turn_on(hass)
    assert mock_client.connections == 2
    assert not [f for f in mock_client.sent if (f.major, f.minor) == (0x00, 0x01)]
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    assert hass.states.get(MEDIA_PLAYER).attributes[ATTR_INPUT_SOURCE] == "Bluetooth"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_turn_on_returns_to_the_last_input(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    # Seen on HDMI eARC when it connected, then switched off.
    await setup_switched_off(hass, mock_client, config_entry)
    last = config_entry.data[CONF_LAST_INPUT]
    assert last["input"] == "Optical/HDMI ARC"
    assert last["how"] == "reported when connecting"
    await turn_on(hass)
    assert Frame(0x00, 0x01, b"\xdf") in mock_client.sent
    assert hass.states.get(MEDIA_PLAYER).attributes[ATTR_INPUT_SOURCE] == (
        "Optical/HDMI ARC"
    )
    # Waking it on Bluetooth is not taken as a new last input.
    assert config_entry.data[CONF_LAST_INPUT] == last
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_an_input_change_while_connected_is_remembered(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup(hass, config_entry)
    # Switched to USB with the remote.
    mock_client._jump(0x40)
    await hass.async_block_till_done()
    last = config_entry.data[CONF_LAST_INPUT]
    assert last["input"] == "USB"
    assert last["how"] == "changed while connected"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_turn_on_without_a_last_input_stays_on_bluetooth(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    # Off from the start, so no input has been seen.
    mock_client.off = True
    await setup(hass, config_entry, connected=False)
    await turn_on(hass)
    assert not [f for f in mock_client.sent if (f.major, f.minor) == (0x00, 0x01)]
    assert CONF_LAST_INPUT not in config_entry.data
    assert hass.states.get(MEDIA_PLAYER).attributes[ATTR_INPUT_SOURCE] == "Bluetooth"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_turn_on_switches_to_the_chosen_input(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    await setup_switched_off(hass, mock_client, config_entry, "Optical/HDMI ARC")
    await turn_on(hass)
    assert Frame(0x00, 0x01, b"\xdf") in mock_client.sent
    assert mock_client.function == 0xC4
    assert hass.states.get(MEDIA_PLAYER).attributes[ATTR_INPUT_SOURCE] == (
        "Optical/HDMI ARC"
    )
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_turn_on_gives_up_if_the_input_does_not_switch(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await setup_switched_off(hass, mock_client, config_entry, "USB")
    mock_client.extra[(0x00, 0x01)] = []
    with patch("custom_components.lg_soundbar_bluetooth.connection.SWITCH_WAIT", 0.2):
        await turn_on(hass)
    assert mock_client.sent.count(Frame(0x00, 0x01, b"\x40")) == 2
    assert "did not switch to USB" in caplog.text
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_turn_off_leaves_the_soundbar_off(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    update(
        hass, config_entry, options={CONF_AUTO_CONNECT: True, CONF_SCAN_INTERVAL: 0.05}
    )
    await setup(hass, config_entry)
    await hass.services.async_call(
        MP_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
    )
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert mock_client.off
    assert mock_client.connections == 1
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    dropped = next(
        e
        for e in config_entry.runtime_data.connection.history
        if e["event"] == "disconnected"
    )
    assert dropped["turned_off_by_home_assistant"] is True
    assert "ConnectionResetError" in dropped["how"]
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_turn_off_switches_back_before_switching_off(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    # On, on HDMI eARC, and not connected; connecting moves it to Bluetooth.
    mock_client.switch_to_bt_on_connect = True
    update(hass, config_entry, options={CONF_AUTO_CONNECT: False})
    await setup(hass, config_entry, connected=False)
    assert not config_entry.runtime_data.client.connected
    await hass.services.async_call(
        MP_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
    )
    await hass.async_block_till_done()
    assert mock_client.off
    # Switched off on the input it was on, not on Bluetooth.
    assert mock_client.switched_off_on == 0xC4
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_connecting_switches_back_from_bluetooth(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    # On E-ARC; connecting moves it to Bluetooth, as a G1 does.
    mock_client.switch_to_bt_on_connect = True
    await setup(hass, config_entry)
    await wait_for(lambda: mock_client.function == 0xC4)
    # Switched back during the handshake, once, as Optical/HDMI ARC as the
    # LG app selects it, with nothing more needed afterwards.
    switch = mock_client.sent.index(Frame(0x00, 0x01, b"\xdf"))
    assert switch < mock_client.sent.index(Frame(0x0C, 0x00))
    assert mock_client.sent.count(Frame(0x00, 0x01, b"\xdf")) == 1
    assert Frame(0x00, 0x01, b"\xc4") not in mock_client.sent
    # The new input's details were read again after the switch.
    assert Frame(0xC4, 0x03) in mock_client.sent[switch:]
    assert hass.states.get(MEDIA_PLAYER).attributes[ATTR_INPUT_SOURCE] == (
        "Optical/HDMI ARC"
    )
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_connecting_leaves_bluetooth_if_it_was_already_on_it(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.function = 0x07
    update(
        hass,
        config_entry,
        options={CONF_AUTO_CONNECT: True, CONF_TURN_ON_INPUT: "Optical/HDMI ARC"},
    )
    await setup(hass, config_entry)
    # Seen on before connecting, so not woken: the option does not apply.
    assert not [f for f in mock_client.sent if (f.major, f.minor) == (0x00, 0x01)]
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_without_auto_connect_commands_connect(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    update(
        hass,
        config_entry,
        data={
            **config_entry.data,
            CONF_SOURCES: ["Bluetooth", "Optical/HDMI ARC", "USB"],
            CONF_SOUND_MODES: ["Music", "Standard"],
        },
        options={},
    )
    await setup(hass, config_entry, connected=False)
    await wait_for(lambda: hass.states.get(MEDIA_PLAYER).state == STATE_ON)
    assert mock_client.connections == 0
    player = hass.states.get(MEDIA_PLAYER)
    # On, by the scan, with nothing shown that is not known.
    assert ATTR_INPUT_SOURCE not in player.attributes
    assert ATTR_SOUND_MODE not in player.attributes
    assert player.attributes["source_list"] == ["Bluetooth", "Optical/HDMI ARC", "USB"]
    assert player.attributes["sound_mode_list"] == ["Music", "Standard"]

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {ATTR_ENTITY_ID: MEDIA_PLAYER, ATTR_INPUT_SOURCE: "USB"},
        blocking=True,
    )
    assert mock_client.connections == 1
    assert mock_client.function == 0x40
    # The history says what scanned and what asked for the connection.
    history = list(config_entry.runtime_data.connection.history)
    assert history[0]["event"] == "scan"
    assert history[0]["trigger"] == "start-up"
    assert history[0]["result"].startswith("seen after ")
    assert history[0]["result"].endswith(" s, RSSI -60")
    connected = next(e for e in history if e["event"] == "connected")
    assert connected["reason"] == "select source USB"
    assert connected["seen_on_before"] is True
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_auto_connect_when_the_soundbar_comes_on(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.off = True
    update(
        hass, config_entry, options={CONF_AUTO_CONNECT: True, CONF_SCAN_INTERVAL: 0.05}
    )
    await setup(hass, config_entry, connected=False)
    assert mock_client.connections == 0
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF

    # Switched on by the TV or remote.
    mock_client.off = False
    await wait_for(lambda: config_entry.runtime_data.client.connected)
    assert mock_client.connections == 1
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_off_when_bluez_cannot_scan(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.bluez_unavailable = True
    await setup(hass, config_entry, connected=False)
    assert mock_client.connections == 0
    # Turning on still works: it connects.
    assert hass.states.get(MEDIA_PLAYER).state == STATE_OFF
    await turn_on(hass)
    assert hass.states.get(MEDIA_PLAYER).state == STATE_ON
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_failing_scans_are_logged_once(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_client.bluez_unavailable = True
    await setup(hass, config_entry, connected=False)
    connection = config_entry.runtime_data.connection
    await connection._scan("test")  # noqa: SLF001
    await connection._scan("test")  # noqa: SLF001
    assert caplog.text.count("Cannot tell whether soundbar") == 1
    mock_client.bluez_unavailable = False
    mock_client.off = True
    await connection._scan("test")  # noqa: SLF001
    assert caplog.text.count("Can tell whether soundbar") == 1
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_the_input_connection_sensor_of_earlier_versions_is_removed(
    hass: HomeAssistant,
    mock_client: FakeSoundbar,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "binary_sensor", DOMAIN, f"{ADDRESS}_input_connected", config_entry=config_entry
    )
    await setup(hass, config_entry)
    assert (
        entity_registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{ADDRESS}_input_connected"
        )
        is None
    )
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_switching_back_again_if_the_early_switch_did_not_take(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    # On HDMI; the soundbar ignores the first request to go back to it.
    mock_client.function = 0xC0
    mock_client.switch_to_bt_on_connect = True
    mock_client.ignored_once = {0xC0}
    await setup(hass, config_entry)
    history = config_entry.runtime_data.connection.history
    await wait_for(lambda: any(e["event"] == "input switched" for e in history))
    assert mock_client.function == 0xC0
    assert mock_client.sent.count(Frame(0x00, 0x01, b"\xc0")) == 2
    decision = next(
        e
        for e in config_entry.runtime_data.connection.history
        if e["event"] == "input decision"
    )
    assert decision["why"] == "switching back while connecting did not take (sent c0)"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_command_does_not_apply_the_turn_on_input(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    # The last scan said off, but the soundbar has since been switched on
    # with its remote, on Bluetooth.
    mock_client.off = True
    update(
        hass,
        config_entry,
        options={CONF_TURN_ON_INPUT: "Optical/HDMI ARC"},
    )
    await setup(hass, config_entry, connected=False)
    mock_client.off = False
    mock_client.function = 0x07
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: MEDIA_PLAYER, ATTR_MEDIA_VOLUME_LEVEL: 0.3},
        blocking=True,
    )
    assert not [f for f in mock_client.sent if (f.major, f.minor) == (0x00, 0x01)]
    assert mock_client.function == 0x07
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_turn_off_without_a_scan_result_connects(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    mock_client.bluez_unavailable = True
    update(hass, config_entry, options={})
    await setup(hass, config_entry, connected=False)
    await hass.services.async_call(
        MP_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
    )
    await asyncio.sleep(0.05)
    assert mock_client.connections == 1
    assert mock_client.off
    await hass.config_entries.async_unload(config_entry.entry_id)
