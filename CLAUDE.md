# CLAUDE.md

Home Assistant custom integration `lg_soundbar_bluetooth` ("LG Soundbars via
Bluetooth") for LG soundbars controlled over Bluetooth Classic, such as the
LG G1. It speaks the soundbar's Bluetooth serial protocol, through the
`lg-soundbar-bluetooth` library. It complements the built-in Wi-Fi `lg_soundbar`
integration and follows its user-facing conventions (input and sound mode
names). Distributed through Home Assistant's Marketplace (which replaced
HACS in 2026.11; only the latest Home Assistant is supported); may be
proposed for Home Assistant core later, which needs the library on PyPI and core PRs opened by the user.

## Git workflow

- Work on a feature branch off `main` (for example `feature/auto-power`),
  commit there and push it.
- Squash-merge a finished feature into `main` as one commit, with a message
  describing the feature, then delete the branch. Ask before squash-merging
  anything more than trivial.
- Commit straight to `main` only for trivial, self-contained changes.
- Batch related work rather than pushing `main` for each step: every push to
  `main` runs CI.
- Bump the version in `manifest.json` only when asked. The Marketplace only
  offers an update when the version (or a release tag) changes.
- Commit as `jeverley <46714706+jeverley@users.noreply.github.com>`, never the
  user's personal email. Don't rewrite `main`'s history unless asked.
- Don't open pull requests unless asked.

## Repo layout

- `custom_components/lg_soundbar_bluetooth/`: the integration. The
  protocol is the `lg-soundbar-bluetooth` library (its own repo, with its
  own CLAUDE.md); behaviour that is about the soundbar belongs there, not
  here, including putting the input back after connecting.
  - `connection.py`: on/off by scanning for the soundbar (`bluetooth-classic`'s
    `find_device_by_address`), connecting when needed, switching the input back,
    auto-connect, and the event history.
  - `config_flow.py`: finds, pairs and trusts the soundbar with
    `bluetooth-classic`, then connects once to read what it supports.
- The integration calls `bluetooth-classic` and the protocol library
  directly, with no wrapper module, as Home Assistant integrations do.
- The protocol reference is the library's `docs/protocol.md`; findings
  from real soundbars are recorded there. `docs/PROTOCOL.md` here points
  to it.
- The tests use the library's `lg_soundbar_bluetooth.testing.FakeSoundbar`,
  which behaves like a real G1; when the soundbar behaves differently,
  update it in the library. `tests/integration/`: integration tests.

## How the soundbar behaves (LG G1, tested)

Design decisions rest on these; check the library's `docs/protocol.md`
before changing
connection behaviour.

- Any Bluetooth connection wakes it from off (with BT LOCK off and Auto
  power on), even `l2ping`; it then starts on Bluetooth. With Auto power
  off, it does not answer at all while off ("Host is down", or BlueZ's
  `br-connection-page-timeout`).
- Connecting moves it to Bluetooth if it is on another input, 0.2 to 0.7 s
  after the connection opens. It only says which input it was on if asked
  before then; asked late (Home Assistant busy), it moves first and reports
  Bluetooth twice. So the current input is asked for alone, from the
  connector's worker thread, the moment the connection opens.
- Following the LG app's start-up order, its feature flags arrive 0.3 to
  0.6 s after opening, often after the move; the flags of the last
  connection are kept to choose how to switch back (`df` or the input's
  code) without waiting.
- Switched back to HDMI with a TV on eARC, it moves itself to eARC about a
  second later; selecting HDMI once more sticks (cause unconfirmed).
- It keeps the newest control connection and drops the older one, so
  connecting takes it from LG's app and the other way round.
- It resets the connection (`ECONNRESET`) as it switches off.
- A short Classic scan finds it whenever it is on, on any input and whatever
  is connected, never while off, and does not wake it.
- Looking its Serial Port service up (SDP) takes about 1.7 s and does not
  move it to Bluetooth; the RFCOMM connection after it still gets the
  input it was on. Its channel is 10.
- It ignores its eARC code (`00/01 c4`) and takes Optical/HDMI ARC
  (`00/01 df`) on soundbars with the `OPT_HDMI_ARC_SUPPORT` flag.

So Home Assistant connects as little as possible: it scans for on/off,
connects when the media player is used (or with auto-connect when the
soundbar comes on), switches the input back after connecting (once more if
the soundbar leaves it while connecting), and never reconnects by itself
after a drop. Turning off switches back first, as the soundbar remembers
the input it is switched off on. The last input it was seen on (reported
when connecting, or changed while connected; never the Bluetooth a wake or
connection causes) is stored, to return to when Home Assistant turns it
on. Apart from asking for the input first, the start-up follows the LG
app's order, waits and feature-flag gating.

## Behaviour and naming

- Follow LG's app: what it offers, how it gates settings by feature flags,
  how it selects inputs. No model-specific special cases; derive behaviour
  from what the soundbar reports.
- Show nothing that isn't known: blank rather than a stale or guessed value.
- Entity names: plain words, no acronyms (Dynamic range control, not DRC).
  Don't repeat what the device class already says (a connectivity sensor is
  "Subwoofer", not "Subwoofer connected"). US English in `strings.json`.
- Renaming an entity changes only its name; existing installs keep their
  entity IDs. Removing an entity: also remove it from the entity registry
  in setup, so it doesn't linger as unavailable.
- `translations/en.json` must match `strings.json`, with the
  `[%key:common::...%]` references resolved.
- Every connection logs and records what asked for it; every scan its
  trigger and why it counted; every drop how and after how long. The last
  50 events go in the diagnostics download.

## Testing

- Test against the real soundbar through the integration itself (build,
  push, the user installs and sends logs or diagnostics), not separate probe
  scripts.
- Change one thing at a time, so a result points to one cause. Keep test
  builds minimal; no fallbacks or options a test doesn't need.
- Before committing: `ruff check .`, `ruff format --check .`,
  `mypy -p custom_components.lg_soundbar_bluetooth` (strict), and
  `pytest tests` (needs `pytest-homeassistant-custom-component`). Timing
  tests can be flaky: run the suite a few times after connection changes.
- When reporting results, keep "tests pass" distinct from "confirmed on the
  soundbar".

## Writing

- Describe the protocol and what the soundbar does; never how the protocol
  was worked out (no app internals or version numbers).
- No em dashes, and no `--` in their place.
- Comments and docs describe what the soundbar and code do, briefly; mark
  what is unconfirmed.
