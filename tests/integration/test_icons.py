"""Tests for the entity icons."""

from __future__ import annotations

import json
from pathlib import Path

COMPONENT = Path(__file__).parents[2] / "custom_components" / "lg_soundbar_bluetooth"


def test_every_icon_is_for_an_entity_and_every_entity_has_one() -> None:
    icons = json.loads((COMPONENT / "icons.json").read_text())["entity"]
    names = json.loads((COMPONENT / "strings.json").read_text())["entity"]
    # The media player takes the device's name, so it has an icon but no
    # name of its own.
    names["media_player"] = {"soundbar": {}}
    assert {p: set(k) for p, k in icons.items()} == {
        p: set(k) for p, k in names.items()
    }
    for platform in icons.values():
        for icon in platform.values():
            assert icon["default"].startswith("mdi:")
