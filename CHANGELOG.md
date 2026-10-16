# Changelog

All notable changes to PlantControl are listed here. Versions follow
[Semantic Versioning](https://semver.org/). Beta versions carry a `-beta.N`
suffix, dev channel builds a `-dev.N` suffix. Changes that are in `dev` but not
released yet are listed under Unreleased.

## Unreleased

Target: 0.2.0. Available in the dev channel.

### Added

- Equipment: tank types, pump models, collector types and power groups are
  described once and shared by machines. Editing an item changes every machine
  that uses it; "Save as new" keeps one machine different.
- Step-by-step wizard for new machines, with a measuring wizard for tanks and a
  one-second relay test for pumps and valves.
- On-site calibration of the whole machine by marks or by time. Plants of a
  collector inherit the flow of a calibrated plant. Optional second tank level,
  flow tuning from measured tank volume and a recalibration reminder.
- A calibration becomes stale when the pump model, tank, collector or tubes
  change. Watering of that plant is blocked until it is recalibrated or the
  calibration is kept explicitly.
- The calibration wizard shows the parameters in effect for each plant and the
  history of past calibrations.
- Copying a machine together with its calibration, several copies at once.
- Export of all or single machines to a file and import with duplicate-free
  equipment and a check for relays already in use.
- Shared schedules on the Waterings tab, attachable to plants of any machine.
  A dose set in a shared schedule takes priority over the plant dose.
- Power groups: limit on how long a request waits for a slot.
- The pump run limit defaults to 300 s and can be turned off.
- Dev channel: every push to `dev` becomes a new version for Home Assistant.

### Changed

- Existing machines move to equipment automatically on start; watering does not
  change.
- Machine cards are collapsed by default; rare actions are in the "..." menu and
  Stop only shows while something is running.
- The Water dialog fills in the dose from the plant's schedule.
- One relay can belong to one machine only.

### Fixed

- A schedule assigned after its time no longer records a "too late" skip, and
  moving a schedule's time no longer starts a watering right away.
- After an update the browser loads the new interface instead of a cached one.
- Problem notifications no longer delay the start of a watering or a calibration
  run.

## 0.1.0

First stable release.

- Watering machines: tank, pump with constant, linear or table flow model, tubes,
  valve collector.
- Dose-based watering with tube volume and pump head taken into account.
- Schedules by weekday or every N days, watering queue with power groups.
- Problems board; blocking problems stop watering.
- Push notifications through the Home Assistant Companion app, quiet hours,
  urgent alerts.
- MQTT discovery: machines appear in Home Assistant as devices.
- Interface in English and Russian, light and dark themes.
- Prebuilt images for amd64 and aarch64.
