"""Constants for the LG Soundbars via Bluetooth integration."""

from __future__ import annotations

DOMAIN = "lg_soundbar_bluetooth"

CONF_CHANNEL = "channel"
CONF_FEATURES = "features"
# The extended feature flags the soundbar last reported, as numbers.
CONF_FLAGS = "flags"
# Whether the soundbar's feature list offers turning it off (the LG app
# shows its power button only then).
CONF_POWER_OFF = "power_off"
CONF_MODEL = "model"
# What the soundbar offers, for use while Home Assistant is not connected.
CONF_SOURCES = "sources"
CONF_SOUND_MODES = "sound_modes"

# Option: the input to switch to after Home Assistant wakes the soundbar,
# which starts on Bluetooth. An input name, TURN_ON_LAST for the last input
# the soundbar was seen on, or TURN_ON_DEFAULT to send nothing.
CONF_TURN_ON_INPUT = "turn_on_input"
TURN_ON_DEFAULT = "default"
TURN_ON_LAST = "last"
DEFAULT_TURN_ON_INPUT = TURN_ON_LAST
# The last input the soundbar was seen on: {"input", "since", "how"}.
CONF_LAST_INPUT = "last_input"
# Option: connect when a scan sees the soundbar come on, and at start-up.
CONF_AUTO_CONNECT = "auto_connect"
DEFAULT_AUTO_CONNECT = False
# Option: seconds between scans for the soundbar while not connected.
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 600
# How long to wait for the soundbar to report the input after switching, and
# how many times to ask.
SWITCH_WAIT = 3.0
SWITCH_ATTEMPTS = 2

DEFAULT_NAME = "LG Soundbar"

# Feature keys stored in the config entry so entities can be created while the
# soundbar is off (its Bluetooth link drops when it is).
FEATURE_LEVELS = "levels"
FEATURE_SWITCHES = "switches"
FEATURE_NIGHT_MODE = "night_mode"
# Extras created when the soundbar has the feature or answered for it.
FEATURE_TONE = "tone"
FEATURE_TONE_MIDDLE = "tone_middle"
FEATURE_SLEEP_TIMER = "sleep_timer"
FEATURE_AUDIO_INFO = "audio_info"
FEATURE_WOOFER_STATE = "woofer_state"
FEATURE_REAR_STATE = "rear_state"
