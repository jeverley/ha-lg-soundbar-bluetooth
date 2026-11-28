# LG Soundbars via Bluetooth

A Home Assistant integration for LG soundbars that are controlled over
Bluetooth, such as the LG G1. It speaks the soundbar's Bluetooth serial
protocol, locally and without the cloud.

It is a companion to Home Assistant's built-in
[LG Soundbars](https://www.home-assistant.io/integrations/lg_soundbar)
integration, which controls Wi-Fi models. Entity layout, input names and
sound mode names follow that integration, so automations read the same.

For developers: how it works, and proposals for Bluetooth Classic support in
Home Assistant, are in [docs/architecture.md](docs/architecture.md).

> **Tested on** an LG G1, day to day. Other models should work if LG's app
> controls them over Bluetooth, but have not been tried. Please report how
> it behaves on yours, with diagnostics attached.

## Installation

[![Open your Home Assistant instance and show this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=jeverley&repository=ha-lg-soundbar-bluetooth&category=integration)

1. Select the button above, or in Home Assistant go to **Settings** →
   **Marketplace** and search for **LG Soundbars via Bluetooth**.
2. Install it and restart Home Assistant.

#### Requirements

- Home Assistant 2026.11 or newer, with BlueZ on the host (Container
  installations need access to the host's D-Bus, as for Home Assistant's
  own Bluetooth integration).
- A Bluetooth adapter that supports **Bluetooth Classic** (BR/EDR) on the Home
  Assistant host. Most built-in and USB adapters do. ESPHome Bluetooth proxies
  do not work, because they only carry Bluetooth Low Energy.

## Features

- A **media player** for volume, mute, input, sound mode, and turning the
  soundbar on and off.
- The soundbar's **settings** as switches and numbers, using the ranges it
  reports.
- Its **speaker connections** and the **audio format** it is playing, where
  it reports them.
- A **Connected** switch to connect, or to let go of the soundbar without
  switching it off.
- The soundbar's **model and firmware versions** on its device page.
- While the soundbar plays Dolby Atmos or DTS:X, the sound mode shows that
  format and cannot be changed, as on the soundbar itself. Settings the
  soundbar ignores in that mode are refused with an explanation.

### Entities

Only what your soundbar offers is created, judged by its feature flags as
LG's app does. The last column shows what an LG G1 has.

| Entity | Type | Category | Created when | Notes | G1 |
|---|---|---|---|---|---|
| *(the soundbar's name)* | Media player | | Always | Turning off where the soundbar offers it, as LG's app shows its power button | ✓ |
| Connected | Switch | | Always | On while Home Assistant is connected. Turning it on connects (and turns on a soundbar that is off); turning it off lets go of the soundbar | ✓ |
| Night time | Switch | | The soundbar has night mode | | ✓ |
| Dynamic range control | Switch | Configuration | The soundbar offers it | | ✓ |
| Auto volume | Switch | Configuration | The soundbar offers it | | ✓ |
| Auto power | Switch | Configuration | The soundbar offers it | Needed for Home Assistant to turn the soundbar on | ✓ |
| Auto display | Switch | Configuration | The soundbar offers it | | |
| Neural:X | Switch | Configuration | The soundbar offers it | | |
| Surround sound | Switch | Configuration | The soundbar offers it | | ✓ |
| TV remote control | Switch | Configuration | The soundbar offers it | | ✓ |
| Woofer level | Number (dB) | Configuration | The soundbar offers it | | ✓ |
| Center level | Number (dB) | Configuration | The soundbar offers it | | ✓ |
| Rear level | Number (dB) | Configuration | The soundbar offers it | | ✓ |
| Side level | Number (dB) | Configuration | The soundbar offers it | | |
| Overhead level | Number (dB) | Configuration | The soundbar offers it | | |
| Dialog control | Number | Configuration | The soundbar offers it | Only during DTS:X | ✓ |
| AV sync | Number (ms) | Configuration | The soundbar offers it | | ✓ |
| Bass, Treble | Number (dB) | Configuration | The soundbar has tone control | | ✓ |
| Middle | Number (dB) | Configuration | The soundbar reports three tone bands | Hidden on models with "Q" in their name, as in LG's app | |
| Sleep timer | Number (min) | | The soundbar's feature list offers it | Minutes left; 0 turns it off | |
| Subwoofer | Binary sensor (connectivity) | Diagnostic | The soundbar reports it | | ✓ |
| Rear speakers | Binary sensor (connectivity) | Diagnostic | The soundbar reports it | | |
| Audio format | Sensor | | The soundbar reports it | Such as Dolby Atmos | |

The media player and Connected switch are always available. The others are
available while Home Assistant is connected, and unavailable otherwise, as
their values are only known then.

## How it connects

Connecting has side effects: it wakes the soundbar if it is off, moves it to
Bluetooth for a moment if it is on, and disconnects other connected
devices. So Home Assistant connects as little as it can:

- **While not connected**, a short Bluetooth scan every minute shows whether
  the soundbar is on, without waking it. The volume, input and sound mode
  are left blank, and the settings are unavailable.
- **Using the media player, or turning on Connected, connects.** Home
  Assistant puts the soundbar straight back on the input it was on, or
  wakes it if it was off.
- **Once connected**, everything updates live until the connection drops
  (the soundbar switches off, another device takes it, or you turn Connected
  off).
  Home Assistant then goes back to scanning and does not reconnect by
  itself.

Options, under **Configure**:

- **Input when turned on**: a soundbar woken by Home Assistant starts on
  Bluetooth. **Last input** (the default) switches it back to the input it
  was last seen on; **Default** leaves it on Bluetooth; or choose an input,
  such as Optical/HDMI ARC.
- **Auto-connect** (off by default): connect when the soundbar comes on, and
  at start-up if it is on, for live updates without using the media player
  first. It never reconnects after a drop while the soundbar stays on, so it
  does not fight other devices.
- **Scan interval** (60 seconds): how often to check whether the soundbar is
  on while not connected.

### Limitations

- **Turning on needs Auto power on and BT LOCK off.** Otherwise the soundbar
  does not answer while off, and with BT LOCK on it may also refuse Home
  Assistant on inputs other than BT and LG TV. (Hold Play/Pause on the
  remote while on BT to see or change BT LOCK.)
- **A short sound drop when Home Assistant connects** while the soundbar is
  playing, as it moves to Bluetooth and back. LG's app causes the same.
- **No live updates while not connected.** Changes made with the remote, the
  TV or LG's app show up once Home Assistant next connects.
- **One connection at a time.** Connecting disconnects other devices from
  the soundbar, and the other way round.
- **Scanning shares the Bluetooth adapter** with Home Assistant's other
  Bluetooth use; a shorter scan interval takes more of it.

## Setup

1. Switch the soundbar on. If your phone is connected to it, disconnect the
   phone so the soundbar is free to pair.
2. In Home Assistant, go to **Settings > Devices & services > Add integration**
   and choose **LG Soundbars via Bluetooth**.
3. Home Assistant scans for about 15 seconds and lists the LG soundbars it
   finds. Pick yours, or type its Bluetooth address if it is not listed.
4. If the soundbar is not paired yet, you are asked to put it in Bluetooth
   pairing mode (on most LG soundbars, press **Function** until it shows
   **BT**). Select **Submit** and Home Assistant pairs with it.

Like LG's app, the integration recognises a soundbar by a Bluetooth name
starting with "LG " or "LG-" (an LG G1 shows up as "LG G1(XX)"). Setup pairs
with the soundbar and marks it as trusted on the Home Assistant host; one
paired earlier, for example with `bluetoothctl`, is trusted when you add it.

There is no automatic discovery notification: Home Assistant's Bluetooth
discovery only sees Bluetooth Low Energy, and these soundbars use Bluetooth
Classic, so the scan runs when you add the integration.

## Examples

Paste these into a new automation, with **Edit in YAML**.

Connect when the TV turns on. If the TV switches the soundbar on and off
itself (over HDMI ARC or eARC), this connects before the TV's sound starts,
so the soundbar's moment on Bluetooth goes unnoticed. If the soundbar is
off, connecting turns it on, on the input chosen in **Input when turned
on**.

```yaml
alias: Connect to the soundbar when the TV turns on
triggers:
  - trigger: state
    entity_id: media_player.living_room_tv
    to: "on"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.lg_g1_xx_connected
```

Use the Music sound mode while the TV plays Spotify, and AI Sound Pro
otherwise, only while the TV is on so it never wakes the soundbar. The
TV's media player reports the app it is running as its source; check
yours under **Tools > States**.

```yaml
alias: Soundbar sound mode follows the TV's app
triggers:
  - trigger: state
    entity_id: media_player.living_room_tv
    attribute: source
conditions:
  - condition: state
    entity_id: media_player.living_room_tv
    state: "on"
actions:
  - action: media_player.select_sound_mode
    target:
      entity_id: media_player.lg_g1_xx
    data:
      sound_mode: |
        {% if state_attr('media_player.living_room_tv', 'source') == 'Spotify - Music and Podcasts' %}
          Music
        {% else %}
          AI Sound Pro
        {% endif %}
```

## Troubleshooting

- **The soundbar does not turn on from Home Assistant**: check **Auto
  power** is on and BT LOCK is off (see Limitations).
- **It is not found when adding it**: switch it on, disconnect your phone
  from it, and keep it close to the Home Assistant host. You can also type
  its Bluetooth address.
- **The input changes for a moment when Home Assistant connects**: this is
  the soundbar moving to Bluetooth, which it does for any control
  connection; Home Assistant switches it straight back.

To see every frame sent and received, select **Enable debug logging** on the
integration's page, reproduce the problem, then disable it to download the
log. This includes the Bluetooth libraries' messages.

When reporting a problem, download the diagnostics from the integration's
device page and attach them to the issue. They show what your soundbar
reported, which helps add support for more models; the soundbar's Bluetooth
address is left out.

## Removal

1. Go to **Settings > Devices & services**, select **LG Soundbars via
   Bluetooth**, and delete the soundbar's entry.
2. To remove the integration as well, uninstall it from the **Marketplace**
   and restart Home Assistant.

The soundbar stays paired with the Home Assistant host. To unpair it, run
`bluetoothctl remove <address>` on the host.

## How it works

The soundbar's protocol is in the
[lg-soundbar-bluetooth](https://github.com/jeverley/lg-soundbar-bluetooth) library, which documents it in
[docs/protocol.md](https://github.com/jeverley/lg-soundbar-bluetooth/blob/main/docs/protocol.md). Bluetooth discovery,
pairing and the serial link come from
[bluetooth-classic](https://github.com/jeverley/bluetooth-classic).

How the pieces fit together, what was prototyped, and proposals for
Bluetooth Classic support in Home Assistant are in
[docs/architecture.md](docs/architecture.md).

## Development

Developed with AI assistance (Claude Code). Changes are reviewed and tested
by the maintainer, and behaviour is confirmed on a real LG G1 before
release.

```sh
pip install pytest-homeassistant-custom-component pytest-asyncio \
  bluetooth-classic lg-soundbar-bluetooth
pytest tests
```

## Disclaimer

This project is not affiliated with or endorsed by LG Electronics. The LG
logo in `custom_components/lg_soundbar_bluetooth/brand/` is the one Home
Assistant uses for its built-in LG integrations, from the
[Home Assistant brands repository](https://github.com/home-assistant/brands),
and is used to identify the product only. LG and the LG logo are trademarks
of LG Electronics.
