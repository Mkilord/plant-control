# PlantControl

[![CI](https://github.com/Mkilord/plant-control/actions/workflows/ci.yaml/badge.svg)](https://github.com/Mkilord/plant-control/actions/workflows/ci.yaml)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
![Architectures](https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational)

**English** · [Русский](README.ru.md)

A Home Assistant add-on for targeted plant watering. You describe your own
watering machines — a tank, a pump, tubes and valves leading to each plant — and
PlantControl calculates how long to run the pump for the dose you want, waters on
a schedule, keeps a queue so machines do not overload the power supply, and stops
watering when something is wrong.

From Home Assistant it only needs switches for the pumps and valves (any relay that
shows up as a `switch` entity).

## Features

- **Watering machines** — tank shape and volume, pump flow model (constant, linear
  or measured table), tubes and a valve collector with one outlet open at a time.
- **Dose-based watering** — you set millilitres, PlantControl works out the run
  time, including water left in the tubes and pump head.
- **Schedules** — on chosen weekdays or every N days, per plant.
- **Queue** — one watering per machine at a time, a limit per power group, manual
  requests go first.
- **Problems** — unavailable pump or valve, unknown pump state, empty tank, lost
  connection to Home Assistant. Blocking problems make watering impossible until
  they are fixed.
- **Push notifications** to phones through the Home Assistant Companion app, with
  quiet hours and urgent alerts.
- **MQTT discovery** — every machine becomes a device in Home Assistant with tank
  level, status, last watering and a "Water" button per plant.
- Interface in English and Russian, light and dark themes, opens inside Home
  Assistant (Ingress).

## Requirements

- Home Assistant OS or Supervised (add-ons need the Supervisor).
- An `amd64` or `aarch64` machine (Raspberry Pi 4/5 in 64-bit, x86 mini PC, etc.).
- Relays for pumps and valves available in Home Assistant as `switch` entities.
- Optional: the Mosquitto broker add-on for MQTT devices, the Companion app for
  push notifications.

## Installation

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FMkilord%2Fplant-control)

Or manually:

1. In Home Assistant open **Settings → Add-ons → Add-on Store**.
2. Menu in the top right corner → **Repositories**, add
   `https://github.com/Mkilord/plant-control` and close the dialog.
3. Find **PlantControl** in the store, press **Install**, then **Start**.
4. Turn on **Show in sidebar** and open PlantControl.

### Release channels

| Channel | Repository URL | For whom |
| --- | --- | --- |
| Stable | `https://github.com/Mkilord/plant-control` | Everyday use |
| Beta | `https://github.com/Mkilord/plant-control#beta` | Trying new features early |

Beta builds may contain bugs. Back up before switching channels. Add only one of
the two repositories.

> PlantControl has not had its first stable release yet. Until then, the stable
> channel carries pre-release versions too.

## Documentation

How to set up machines, schedules, notifications and MQTT:
[DOCS.md](DOCS.md) (also shown on the add-on's **Documentation** tab).

Changes between versions: [CHANGELOG.md](CHANGELOG.md).

## Safety

PlantControl switches pumps and valves on and off. Software, Wi-Fi relays and
Home Assistant itself can fail. Use hardware protection that does not depend on
this add-on — a float switch, a pump with dry-run protection, a timer relay —
especially for unattended watering.

## Contributing

Bug reports and ideas are welcome in
[Issues](https://github.com/Mkilord/plant-control/issues). How to build, test and
release: [CONTRIBUTING.md](CONTRIBUTING.md).

## Author

Created and maintained by [Mkilord](https://github.com/Mkilord).

## License

Copyright (C) 2026 Mkilord

PlantControl is free software: you can redistribute it and/or modify it under the
terms of the [GNU General Public License v3.0](LICENSE) or (at your option) any
later version. Any modified version you distribute must be free under the same
terms.

It is distributed **as is, without any warranty**, including the implied
warranties of merchantability or fitness for a particular purpose. See the
license for details.
