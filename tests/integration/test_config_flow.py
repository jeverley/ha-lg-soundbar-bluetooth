"""Tests for the config flow: scan, pick, pair and connect."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, patch

from bluetooth_classic import BluetoothClassicError, ClassicDevice, PairingError
from lg_soundbar_bluetooth import SPP_UUID
from lg_soundbar_bluetooth.testing import ADDRESS, FakeSoundbar
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lg_soundbar_bluetooth.config_flow import (
    async_ensure_paired,
    async_ensure_trusted,
    async_find_soundbars,
)
from custom_components.lg_soundbar_bluetooth.const import (
    CONF_AUTO_CONNECT,
    CONF_SCAN_INTERVAL,
    CONF_SOURCES,
    CONF_TURN_ON_INPUT,
    DOMAIN,
    TURN_ON_DEFAULT,
    TURN_ON_LAST,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import FEATURES

FLOW = "custom_components.lg_soundbar_bluetooth.config_flow"
HANDSHAKE_TIMEOUT = "lg_soundbar_bluetooth.client.HANDSHAKE_TIMEOUT"


def g1(paired: bool) -> ClassicDevice:
    return ClassicDevice(
        address=ADDRESS,
        name="LG G1(XX)",
        path="/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF",
        adapter="hci0",
        paired=paired,
    )


async def choose_options(hass: HomeAssistant, result: dict, **choices: object) -> dict:
    """Answer the options step that ends setup."""
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "options"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TURN_ON_INPUT: TURN_ON_LAST,
            CONF_AUTO_CONNECT: False,
            CONF_SCAN_INTERVAL: 60,
            **choices,
        },
    )


async def finish_progress(hass: HomeAssistant, result: dict, action: str) -> dict:
    """Let a progress step's task finish and move on.

    Mocked tasks finish at once, in which case Home Assistant has usually
    moved past the spinner already.
    """
    if result["type"] is FlowResultType.SHOW_PROGRESS:
        assert result["progress_action"] == action
        await hass.async_block_till_done()
    if result["type"] in (
        FlowResultType.SHOW_PROGRESS,
        FlowResultType.SHOW_PROGRESS_DONE,
    ):
        return await hass.config_entries.flow.async_configure(result["flow_id"])
    return result


async def start(hass: HomeAssistant, found: list[ClassicDevice]) -> dict:
    """Start the flow and let the scan finish."""
    with patch(f"{FLOW}.async_find_soundbars", AsyncMock(return_value=found)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await finish_progress(hass, result, "scanning")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick"
    return result


async def test_scan_pair_and_create_entry(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    result = await start(hass, [g1(paired=False)])
    assert result["description_placeholders"] == {"count": "1"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["step_id"] == "pair"
    assert result["type"] is FlowResultType.FORM

    pair = AsyncMock(return_value=g1(paired=True))
    with patch(f"{FLOW}.async_ensure_paired", pair):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await finish_progress(hass, result, "pairing")
    pair.assert_awaited_once_with(ADDRESS)

    result = await choose_options(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "LG G1(XX)"
    assert result["result"].unique_id == ADDRESS
    # The options chosen at the end of setup are saved.
    assert result["result"].options == {
        CONF_TURN_ON_INPUT: TURN_ON_LAST,
        CONF_AUTO_CONNECT: False,
        CONF_SCAN_INTERVAL: 60,
    }
    flags = result["data"].pop("flags")
    # A G1's feature list offers turning it off.
    assert result["data"].pop("power_off") is True
    # The extended feature flags, kept to switch back without waiting.
    assert 3 * 8 + 6 in flags
    assert result["data"] == {
        CONF_ADDRESS: ADDRESS,
        "channel": 1,
        "features": FEATURES,
        # Stored for use while not connected, and to switch back quickly.
        "sources": ["Bluetooth", "HDMI", "LG TV", "Optical/HDMI ARC", "USB"],
        "sound_modes": ["AI Sound Pro", "Bass Blast", "Movie", "Music", "Standard"],
    }


async def test_already_paired_skips_pairing(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    result = await start(hass, [g1(paired=True)])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    result = await choose_options(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_pairing_failure_can_be_retried(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    result = await start(hass, [g1(paired=False)])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )

    with patch(
        f"{FLOW}.async_ensure_paired", AsyncMock(side_effect=PairingError("no"))
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await finish_progress(hass, result, "pairing")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": "pairing_failed"}

    with patch(f"{FLOW}.async_ensure_paired", AsyncMock(return_value=g1(True))):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await finish_progress(hass, result, "pairing")
    result = await choose_options(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_without_bluez_typed_address_still_connects(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    result = await start(hass, [])
    assert result["description_placeholders"] == {"count": "0"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "aa-bb-cc-dd-ee-ff"}
    )
    assert result["step_id"] == "pair"
    with patch(
        f"{FLOW}.async_ensure_paired",
        AsyncMock(side_effect=BluetoothClassicError("no bus")),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await finish_progress(hass, result, "pairing")
    result = await choose_options(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "LG Soundbar"


async def test_connect_failure_can_be_retried(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    result = await start(hass, [g1(paired=True)])
    mock_client.silent = True
    with patch(HANDSHAKE_TIMEOUT, 0.05):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["step_id"] == "connect"
    assert result["errors"] == {"base": "cannot_connect"}

    mock_client.silent = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await choose_options(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("address", ["nonsense", "AA:BB:CC:DD:EE"])
async def test_invalid_address(
    hass: HomeAssistant, mock_client: FakeSoundbar, address: str
) -> None:
    result = await start(hass, [])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: address}
    )
    assert result["errors"] == {CONF_ADDRESS: "invalid_address"}


async def test_already_configured(
    hass: HomeAssistant, mock_client: FakeSoundbar, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await start(hass, [g1(paired=True)])
    # The configured soundbar is not offered again.
    assert result["description_placeholders"] == {"count": "0"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_scan_shows_progress_until_done(
    hass: HomeAssistant, mock_client: FakeSoundbar
) -> None:
    release = asyncio.Event()

    async def slow_scan() -> list[ClassicDevice]:
        await release.wait()
        return [g1(paired=True)]

    with patch(f"{FLOW}.async_find_soundbars", slow_scan):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        assert result["progress_action"] == "scanning"
        release.set()
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "pick"
    assert result["description_placeholders"] == {"count": "1"}


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        (
            ["Bluetooth", "HDMI", "Optical/HDMI ARC"],
            [TURN_ON_LAST, TURN_ON_DEFAULT, "Bluetooth", "HDMI", "Optical/HDMI ARC"],
        ),
        # Before the first connection the inputs are not known yet.
        (None, [TURN_ON_LAST, TURN_ON_DEFAULT]),
    ],
)
async def test_options(
    hass: HomeAssistant, sources: list[str] | None, expected: list[str]
) -> None:
    data = {CONF_ADDRESS: ADDRESS}
    if sources:
        data[CONF_SOURCES] = sources
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data=data)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    selector = schema[CONF_TURN_ON_INPUT]
    assert [o["value"] for o in selector.config["options"]] == expected
    defaults = {key.schema: key.default() for key in schema}
    # The last input, no auto-connect, and a scan a minute by default.
    assert defaults == {
        CONF_TURN_ON_INPUT: TURN_ON_LAST,
        CONF_AUTO_CONNECT: False,
        CONF_SCAN_INTERVAL: 60,
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TURN_ON_INPUT: TURN_ON_DEFAULT,
            CONF_AUTO_CONNECT: True,
            CONF_SCAN_INTERVAL: 30,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_TURN_ON_INPUT: TURN_ON_DEFAULT,
        CONF_AUTO_CONNECT: True,
        CONF_SCAN_INTERVAL: 30,
    }


class _Unreachable:
    """A BluetoothClassic whose system bus cannot be reached."""

    async def __aenter__(self) -> _Unreachable:
        raise BluetoothClassicError("no bus")

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Bluetooth:
    """Stands in for bluetooth_classic.BluetoothClassic."""

    def __init__(self, known: list[ClassicDevice]) -> None:
        self.known = {d.address: d for d in known}
        self.calls: list[str] = []
        self.on_discover: list[ClassicDevice] = []

    async def __aenter__(self) -> _Bluetooth:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def discover(self) -> list[ClassicDevice]:
        self.calls.append("discover")
        for device in self.on_discover:
            self.known[device.address] = device
        return self.on_discover

    async def devices(self) -> list[ClassicDevice]:
        return list(self.known.values())

    async def device(self, address: str) -> ClassicDevice | None:
        return self.known.get(address)

    async def pair(self, address: str) -> ClassicDevice:
        self.calls.append("pair")
        device = replace(self.known[address], paired=True)
        self.known[address] = device
        return device

    async def trust(self, address: str) -> ClassicDevice:
        self.calls.append("trust")
        device = replace(self.known[address], trusted=True)
        self.known[address] = device
        return device


def _connected(bluetooth: _Bluetooth) -> Any:
    return patch(f"{FLOW}.BluetoothClassic", return_value=bluetooth)


async def test_find_soundbars_lists_lg_soundbars_paired_first() -> None:
    other = ClassicDevice(
        address="11:22:33:44:55:66", name="Phone", path="/p1", adapter="hci0"
    )
    unpaired = replace(g1(False), address="22:33:44:55:66:77", name="LG-SN5Y")
    paired = replace(g1(True), uuids=frozenset({SPP_UUID}))
    bluetooth = _Bluetooth([other, unpaired, paired])
    with _connected(bluetooth):
        found = await async_find_soundbars()
    assert [d.address for d in found] == [ADDRESS, "22:33:44:55:66:77"]
    assert bluetooth.calls == ["discover"]


async def test_find_soundbars_without_bluez() -> None:
    with patch(
        f"{FLOW}.BluetoothClassic",
        return_value=_Unreachable(),
    ):
        assert await async_find_soundbars() == []


async def test_ensure_paired_pairs_then_trusts() -> None:
    bluetooth = _Bluetooth([g1(False)])
    with _connected(bluetooth):
        device = await async_ensure_paired(ADDRESS)
    assert device.paired
    assert device.trusted
    assert bluetooth.calls == ["pair", "trust"]


async def test_ensure_paired_scans_for_an_unknown_soundbar() -> None:
    bluetooth = _Bluetooth([])
    bluetooth.on_discover = [g1(False)]
    with _connected(bluetooth):
        await async_ensure_paired(ADDRESS)
    assert bluetooth.calls == ["discover", "pair", "trust"]


@pytest.mark.parametrize(
    ("known", "trusts"),
    [([g1(True)], 1), ([replace(g1(True), trusted=True)], 0), ([g1(False)], 0)],
)
async def test_ensure_trusted(known: list[ClassicDevice], trusts: int) -> None:
    bluetooth = _Bluetooth(known)
    with _connected(bluetooth):
        await async_ensure_trusted(ADDRESS)
    assert bluetooth.calls.count("trust") == trusts


async def test_ensure_trusted_ignores_bluez_errors() -> None:
    with patch(
        f"{FLOW}.BluetoothClassic",
        return_value=_Unreachable(),
    ):
        await async_ensure_trusted(ADDRESS)
