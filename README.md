# PlantControl

[![CI](https://github.com/Mkilord/plant-control/actions/workflows/ci.yaml/badge.svg)](https://github.com/Mkilord/plant-control/actions/workflows/ci.yaml)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
![Architectures](https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational)

**English** | [Русский](README.ru.md)

A Home Assistant add-on for targeted plant watering. You describe your own
watering machines: a tank, a pump, tubes and valves leading to each plant.
PlantControl calculates how long to run the pump for the dose you want, waters on
a schedule, keeps a queue so machines do not overload the power supply, and stops
watering when something is wrong.

From Home Assistant it only needs switches for the pumps and valves: any relay
that shows up as a `switch` or `input_boolean` entity.

## Features

- **Watering machines.** Tank, pump, tubes and a valve collector. A new machine
  is set up with a step-by-step wizard.
- **Equipment.** Tanks, pumps, collectors and power groups are described once and
  fit many machines. Identical machines are made by copying.
- **On-site calibration.** The pump fills a measuring container, and the flow,
  delay and afterflow are worked out for you. A calibration becomes stale when
  the hardware changes.
- **Dose-based watering.** You set millilitres, PlantControl works out the run time.
- **Schedules.** On chosen weekdays or every N days, per plant or shared by many
  plants.
- **Queue and power groups.** Machines on one power supply do not start at once.
- **Problems.** Unavailable pump or valve, empty tank, lost connection to Home
  Assistant. Blocking problems make watering impossible until they are fixed.
- **Push notifications** through the Home Assistant Companion app, with quiet
  hours and urgent alerts.
- **MQTT discovery.** Every machine becomes a device in Home Assistant.
- **Export and import** of machines to a file.
- Interface in English and Russian, light and dark themes, opens inside Home
  Assistant (Ingress).

## Requirements

- Home Assistant OS or Supervised (add-ons need the Supervisor).
- An `amd64` or `aarch64` machine (Raspberry Pi 4 or 5 in 64-bit, an x86 mini PC
  and so on).
- Relays for pumps and valves in Home Assistant.
- Optional: the Mosquitto broker add-on for MQTT devices, the Companion app for
  push notifications.

## Installation

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FMkilord%2Fplant-control)

Or manually:

1. In Home Assistant open **Settings**, **Add-ons**, **Add-on Store**.
2. In the menu in the top right corner choose **Repositories**, add
   `https://github.com/Mkilord/plant-control` and close the dialog.
3. Find **PlantControl** in the store, press **Install**, then **Start**.
4. Turn on **Show in sidebar** and open PlantControl.

### Release channels

| Channel | Repository URL | For whom |
| --- | --- | --- |
| Stable | `https://github.com/Mkilord/plant-control` | Everyday use |
| Beta | `https://github.com/Mkilord/plant-control#beta` | Trying new features early |
| Dev | `https://github.com/Mkilord/plant-control#dev-channel` | Testing every change as soon as it lands |

Beta builds may contain bugs, dev builds even more so. Each channel installs as
a separate add-on with its own data. Use export and import to move machines
between channels.

## Documentation

[How to use PlantControl](DOCS.md): machines, equipment, calibration, schedules,
notifications and MQTT. The same text is shown on the add-on's **Documentation**
tab.

The [changelog](CHANGELOG.md) lists changes by version.

## Safety

PlantControl switches pumps and valves on and off. Software, Wi-Fi relays and
Home Assistant itself can fail. Use hardware protection that does not depend on
this add-on: a float switch, a pump with dry-run protection, a timer relay.
Especially for unattended watering.

## Contributing

Bug reports and ideas are welcome in
[Issues](https://github.com/Mkilord/plant-control/issues).
[How to build, test and release](CONTRIBUTING.md).

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
