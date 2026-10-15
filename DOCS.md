# PlantControl documentation

**English** · [Русский](DOCS.ru.md)

Targeted plant watering in Home Assistant: your own watering machines, schedules,
a watering queue and problems. Home Assistant only has to provide relays for pumps
and valves. The interface opens inside Home Assistant (Ingress), no extra port is
needed.

## First steps

1. Install and start the add-on (see [README.md](README.md)).
2. Open PlantControl from the sidebar.
3. On the **Machines** tab create a machine: tank, pump, plants and their outlets.
   The pump and valves are picked from Home Assistant `switch` entities.
4. Calibrate the pump: the **Calibrate** button on the machine card.
5. Check the watering plan and water once by hand with a small dose.
6. Add schedules to the plants.

## Pump calibration

The pump flow is measured, not typed in. The calibration wizard opens from the
**Calibrate** button on the machine card and works on a phone and on a PC.
Put the container under the tube outlet at the plant, not under the pump: then
the real lift height and tube length are part of the measurement.

Two ways:

- **By marks.** Needs a container with markings. Set a calibration volume and
  marks, for example 500, 1000 and 1500 ml. After Start press the button each
  time the water reaches a mark. The pump stops by itself at the last mark. Then
  enter how much water is in the container once it stops dripping.
- **By time.** The pump runs for a set time, the water is weighed (1 g = 1 ml) or
  measured. Two runs of different length, for example 10 and 30 s. More precise
  than marks and suits powerful pumps.

The calibration volume does not depend on the tank size: one and a half litres
is enough even for a tank of a ton. A run should take at least 20 seconds,
otherwise the wizard warns that the press error is noticeable.

The measurement gives the flow, the delay before the first water and how much
drips after the stop. Watering time: the delay plus (dose minus afterflow)
divided by the flow.

Safety: the pump never runs longer than its limit, stops if the last mark does
not come within 1.5 of the expected time, and stops if the wizard page is closed
or the connection is lost. The machine does not water while being calibrated.

With a collector it is enough to calibrate one plant. The others use its flow,
the difference in tube volume is taken into account. Any plant can be calibrated
separately.

In a small tank the flow drops noticeably as the tank empties. Then make a
second measurement with an almost empty tank and save it as a second level: the
flow will depend on the volume of water in the tank.

When you enter the actual tank volume, the calculation is compared with reality.
If the flow is clearly off, the card offers to correct it. A recalibration
reminder can be turned on under the gear.

The old way (flow from the pump datasheet, outlet height, correction) stays in
the machine form behind the "Advanced mode" checkbox.

## Interface

- **Machines** — watering machine cards: tank, pump, plants, manual watering.
- **Waterings** — what is watering now and waiting in the queue, upcoming scheduled
  waterings and the journal. The journal is stored in the database and survives
  restarts; skipped scheduled waterings are listed with the reason. The page
  refreshes itself.
- **Problems** — open problems with a hint on what to do. The tab counter turns
  red when watering is impossible somewhere.
- The gear on the right — notification and MQTT settings, plus the connection to
  Home Assistant.

## Add-on options

On the add-on's **Configuration** tab:

| Option | What it does |
| --- | --- |
| `log_level` | Log detail: `debug`, `info`, `warning`, `error`. |
| `timezone` | Time zone for schedules and quiet hours, for example `Europe/Berlin`. Empty means the Home Assistant time zone. |

MQTT and notifications are set up in the interface, under the gear.

## MQTT

Over MQTT the machines appear in Home Assistant as devices (discovery). Turn MQTT
on and pick the broker in the interface settings:

- **Automatic** — the broker provided by Home Assistant, i.e. the Mosquitto add-on.
  The add-on gets the address and password from the Supervisor.
- **Manual** — your own broker: host, port, username and password.

After saving, the add-on reconnects right away and the settings show whether the
broker is reachable. The password is never sent back to the interface: leaving the
field empty keeps the old one.

## Push notifications

Pushes go through the Home Assistant Companion app: every phone with the app is a
`notify.mobile_app_<name>` service. Install the app and sign in to your Home
Assistant.

Notifications are set up in the interface, under the gear: which phones (none
selected means all), what to report, quiet hours, urgent pushes. With **Advanced
settings** checked you can change the notification texts and the address opened on
tap. Unchecking it brings back the default texts; your own are kept.

- A repeat of the same trouble replaces the previous push, and "problem solved"
  replaces the problem push.
- Urgent pushes are delivered immediately (high priority on Android,
  time-sensitive on iOS) and arrive even during quiet hours. On Android they use a
  separate channel ("PlantControl: срочно"), so you can set its sound and vibration
  separately.
- Tapping a push opens the PlantControl panel.

Use the **Test push** button in the settings to check delivery.

## Problems and watering

While a blocking problem is open (no connection to Home Assistant, pump or valve
unavailable, unknown pump state, empty tank), nothing waters: not by hand, not on
schedule, not from the queue. The state is checked again right before every
watering, so a pump that has just disappeared will not be switched on. A valve
problem only affects its own plant; the others still get watered. Muting a problem
does not allow watering.

## What appears in Home Assistant

Every machine becomes a device: water left and tank fill level, status, last
watering time, a problem flag, a "Water" button per plant, a dose field and a
"Tank refilled" button — handy to press from an automation triggered by an NFC tag.
For now these entities and push notification texts are named in Russian; you can
rename entities in Home Assistant and change the push texts in the advanced
notification settings.

Events on the bus (`plant_control_watering_done`, `plant_control_watering_failed`,
`plant_control_problem_opened` and others) let automations react on their own.

## Data and backups

Machines, schedules and the journal are stored in the add-on's `/data` folder. It
is kept across updates and included in Home Assistant backups together with the
add-on.

## Updates

New versions show up in Home Assistant like for any add-on. See
[CHANGELOG.md](CHANGELOG.md) for what changed. To get beta versions, add the
repository as `https://github.com/Mkilord/plant-control#beta` instead of the
regular one. Dev versions (every change, untested) come from
`https://github.com/Mkilord/plant-control#dev-channel`.

## Troubleshooting

- Check the add-on's **Log** tab. For more detail set `log_level: debug` and
  restart the add-on.
- Look at the **Problems** tab in the interface — it tells you what to do.
- Report bugs in [Issues](https://github.com/Mkilord/plant-control/issues) with the
  add-on version and the log.
