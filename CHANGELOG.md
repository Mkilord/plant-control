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
- Journals can be cleared: the watering journal (all records or only failed
  ones), past calibrations of a machine and the new problem history. Delete one
  record, records older than 7, 30 or 90 days, or everything. The calibration in
  effect and open problems are never deleted.
- Problem history on the Problems tab: when each problem opened, how long it
  lasted and on which machine.
- Retention setting for journals: 30, 90 or 365 days or no limit.

### Changed

- Existing machines move to equipment automatically on start; watering does not
  change.
- Machine cards are collapsed by default; rare actions are in the "..." menu and
  Stop only shows while something is running.
- The Water dialog fills in the dose from the plant's schedule.
- One relay can belong to one machine only.

### Fixed

- MQTT: entities of a deleted machine or plant stay in Home Assistant no
  longer, leftovers from earlier versions are removed on connect. Renaming a
  machine or a plant updates the device and entity names in Home Assistant.
- The list of Home Assistant entities did not open in the Home Assistant app on
  Android. The relay field now has its own list with search, entity states and
  relays taken by other machines.
- Hints behind the "i" icon and "..." menus no longer go off screen. On a phone a
  hint opens as a panel at the bottom.
- A pump relay that turns on while its machine is not watering is switched off
  right away. Before, it was taken for a manual start and could run until the
  pump limit or longer. If the relay does not confirm the off command, watering
  of that machine is blocked and a problem is raised. A pump turned on by hand in
  Home Assistant is switched off too.
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
