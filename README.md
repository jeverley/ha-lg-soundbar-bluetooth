# LG Soundbars via Bluetooth

A Home Assistant integration for LG soundbars that are controlled over
Bluetooth, such as the LG G1. It speaks the soundbar's Bluetooth serial
protocol, locally and without the cloud.

It is a companion to Home Assistant's built-in
[LG Soundbars](https://www.home-assistant.io/integrations/lg_soundbar)
integration, which controls Wi-Fi models. Entity layout, input names and
sound mode names follow that integration, so automations read the same.

> **Status: early.** It is tested day to day on an LG G1. Other models should work if LG's app controls them
> over Bluetooth, but have not been tried. Please report how it behaves on
> yours, with diagnostics attached.

## What you get

- **Media player**: volume, mute, input, sound mode, turn on, and turn off
  where the soundbar offers it (as LG's app shows its power button).
- **Numbers**: woofer, center, rear, side and overhead speaker levels (dB),
  dialog control and AV sync (ms), using the ranges your soundbar reports.
- **Switches**: night time, dynamic range control (DRC), auto volume, auto
  power, auto display, Neural:X, surround sound and TV remote control.
- **Bass and treble** (and middle on soundbars with three tone bands).
- A **sleep timer** (minutes left, 0 for off) on soundbars whose feature
  list offers one, as LG's app does.
- **Connections**: whether Home Assistant is connected to the soundbar
  (**Bluetooth**), and the **Subwoofer** and **Rear speakers** where the
  soundbar reports them. Some soundbars report only one of these; the
  speaker levels and surround setting work either way.
- **Audio format**, such as Dolby Atmos, where the soundbar reports it.
- The soundbar's **model and firmware versions** on its device page, as the
  soundbar reports them.
- While the soundbar plays Dolby Atmos or DTS:X, the sound mode shows that
  format and cannot be changed, as on the soundbar itself. Settings the
  soundbar ignores in that mode are refused with an explanation.

Only what your soundbar offers is created, judged by its feature flags as the
LG app does.

## How it connects

Connecting to the soundbar has side effects: it wakes the soundbar if it is
off, switches it to Bluetooth if it is on (cutting your TV sound for a
moment), and takes it from LG's app, as the soundbar keeps only the newest
connection. So Home Assistant connects as little as it can:

- **While not connected**, Home Assistant checks whether the soundbar is on
  with a short Bluetooth scan every minute. The scan does not wake it or
  change its input. The media player shows on or off, with the volume, input
  and sound mode left blank, and the settings are unavailable.
- **Using the media player connects**: turning on, or changing the volume,
  input or sound mode. If the soundbar was on, Home Assistant switches it
  straight back to the input it was on. If it was off, connecting wakes it
  (see **Input when turned on** below).
- **Once connected**, everything updates live, including changes made with
  the remote, until the connection drops: the soundbar switches off, LG's app
  takes it, or the link fails. Home Assistant then goes back to scanning; it
  does not reconnect by itself.

Options, under **Configure**:

- **Input when turned on**: a soundbar woken by Home Assistant starts on
  Bluetooth. **Default** leaves it there; choose an input, such as
  Optical/HDMI ARC, to switch to straight afterwards.
- **Auto-connect** (off by default): connect when the soundbar comes on, and
  when Home Assistant starts if it is on, for live updates without using the
  media player first. Each time, the soundbar moves to Bluetooth for a moment
  before Home Assistant switches it back. It never reconnects after the
  connection drops while the soundbar stays on, so it does not fight LG's app.
- **Scan interval** (60 seconds): how often to check whether the soundbar is
  on while not connected.

### Limitations

- **Turning on needs BT LOCK off.** With BT LOCK on (hold Play/Pause on the
  remote while on BT to see or change it), the soundbar does not answer while
  off, and may refuse Home Assistant while on inputs other than BT and LG TV.
- **A short sound drop when Home Assistant connects** while the soundbar is
  playing, as it moves to Bluetooth and back. The soundbar does this for any
  control connection, LG's app included.
- **No live updates while not connected.** Changes made with the remote, the
  TV or LG's app show up once Home Assistant next connects; on or off is
  always shown, from the scans.
- **One controller at a time.** Connecting takes the soundbar from LG's app,
  and the other way round. Opening the app is enough to take it from Home
  Assistant, which then leaves the soundbar alone until you use it again.
- **Scanning shares the Bluetooth adapter** with Home Assistant's other
  Bluetooth use. A 5-second scan a minute is little, but a shorter scan
  interval takes more.

## Requirements

- Home Assistant OS, Supervised or Container on Linux. Home Assistant's own
  Python is built with Bluetooth socket support, so nothing extra needs
  installing.
- A Bluetooth adapter that supports **Bluetooth Classic** (BR/EDR) on the Home
  Assistant host. Most built-in and USB adapters do. ESPHome Bluetooth proxies
  do not work, because they only carry Bluetooth Low Energy.

## Installation

### HACS

1. In HACS, open the menu, choose **Custom repositories**, and add
   `https://github.com/jeverley/ha-lg-soundbar-bluetooth` as an
   **Integration**.
2. Install **LG Soundbars via Bluetooth** and restart Home Assistant.

### Manual

Copy `custom_components/lg_soundbar_bluetooth` into your Home Assistant
`config/custom_components` folder and restart Home Assistant.

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
starting with "LG " or "LG-" (an LG G1 shows up as "LG G1(XX)", where XX
varies).

Pairing uses a temporary agent that only accepts the chosen soundbar. The
soundbar is then marked as trusted on the Home Assistant host, as phones do
with what they pair with: some soundbars drop the control connection a
moment after it opens otherwise. Soundbars paired earlier (for example with
`bluetoothctl`) are marked as trusted when you set them up.

The integration finds the soundbar's serial port channel itself and remembers
it, along with which settings the soundbar supports, so it can be set up
again after a restart even while the soundbar is off. With **Auto-connect**
on, it connects whenever the soundbar comes on.

### Why there is no automatic discovery notification

Home Assistant's automatic Bluetooth discovery only listens to Bluetooth Low
Energy advertisements. Soundbars controlled this way use Bluetooth Classic,
which is only found by an active scan, so the scan runs when you add the
integration rather than in the background. Running Classic scans continuously
would interfere with Home Assistant's own Bluetooth scanning.

## Troubleshooting

Turn on debug logging to see every frame sent and received:

```yaml
logger:
  logs:
    custom_components.lg_soundbar_bluetooth: debug
```

When reporting a problem, download the diagnostics from the integration's
device page and attach them to the issue. They show what your soundbar
reported, which helps add support for more models.

## How it works

The soundbar's protocol is in the
[lg-soundbar-bluetooth](https://github.com/jeverley/lg-soundbar-bluetooth) library, which documents it in
[docs/protocol.md](https://github.com/jeverley/lg-soundbar-bluetooth/blob/main/docs/protocol.md). Bluetooth discovery,
pairing and the serial link come from
[bluetooth-classic](https://github.com/jeverley/bluetooth-classic).

## Development

```sh
pip install pytest-homeassistant-custom-component lg-soundbar-bluetooth
pytest tests
```

## Disclaimer

This project is not affiliated with or endorsed by LG Electronics. The LG
logo in `custom_components/lg_soundbar_bluetooth/brand/` is the one Home
Assistant uses for its built-in LG integrations, from the
[Home Assistant brands repository](https://github.com/home-assistant/brands),
and is used to identify the product only. LG and the LG logo are trademarks
of LG Electronics.
