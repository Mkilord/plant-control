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
4. Check the watering plan and water once by hand with a small dose.
5. Add schedules to the plants.

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
regular one.

## Troubleshooting

- Check the add-on's **Log** tab. For more detail set `log_level: debug` and
  restart the add-on.
- Look at the **Problems** tab in the interface — it tells you what to do.
- Report bugs in [Issues](https://github.com/Mkilord/plant-control/issues) with the
  add-on version and the log.
