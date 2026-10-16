# PlantControl documentation

**English** | [Русский](https://github.com/Mkilord/plant-control/blob/main/DOCS.ru.md)

Targeted plant watering in Home Assistant: your own watering machines, schedules,
a watering queue and problems. Home Assistant only has to provide relays for pumps
and valves. The interface opens inside Home Assistant (Ingress), no extra port is
needed.

## First steps

1. Install and start the add-on as described in the
   [installation guide](https://github.com/Mkilord/plant-control/blob/main/README.md#installation).
2. Open PlantControl from the sidebar.
3. On the **Machines** tab press **Add watering machine** and follow the wizard.
4. Calibrate the machine: the wizard offers it right after the machine is created.
5. Water once by hand with a small dose and check how much came out.
6. Add schedules to the plants.

## How machines are built

A machine is put together from equipment and its own parts.

- **Equipment** (the **Equipment** tab): tank types, pump models, collector types
  and power groups. An item is described once and fits many machines. Changing it
  changes every machine that uses it. If one machine needs a different variant,
  save the item as a new one.
- **The machine's own parts**: tubes, plants, the Home Assistant relays of the
  pump and valves, calibration and the water in the tank.

A relay can belong to one machine only.

### New machine wizard

The wizard goes step by step: general, collector (if there is one), tank, pump,
tubes, power, schedule. Each step lets you pick an existing equipment item or
enter a new one. Tanks have a measuring wizard that explains how to measure by
dimensions or by filling and how to find the reserve below the pump.

The **Test** button switches a pump or valve relay on for one second.

### Copying a machine

If you have several identical machines, set up one and copy it: the **...** menu
on the card, **Copy**. The copy gets the equipment, tubes, plants, schedules and
calibration. No recalibration is needed, only its own relays. You can make
several copies at once.

### Export and import

Machines can be saved to a file and loaded into another system or another
channel of the add-on:

- all machines: the **...** menu at the top of the **Machines** page, **Export all
  machines**;
- one machine: the **...** menu on the card, **Export**;
- loading: the **...** menu at the top of the page, **Import from file**.

The file holds the machines, their equipment, schedules and calibration. Tank
water and the journal are not carried over. Equipment with the same settings is
not duplicated on import. A machine whose relay is already taken is not
imported, and you see that before loading.

## Calibration

The flow is measured on site, not typed in. The whole machine is calibrated:
pump, tubes, tank and heights. The wizard opens from the **...** menu on the
card, **Calibrate**, and works on a phone and on a PC.

Put the container under the tube outlet at the plant, not under the pump: then
the real lift height and tube length are part of the measurement.

Two ways:

- **By marks.** Needs a container with markings. Set a volume and marks, for
  example 500, 1000 and 1500 ml. After Start press the button each time the
  water reaches a mark. The pump stops by itself at the last mark. Then enter how
  much water is in the container once it stops dripping.
- **By time.** The pump runs for a set time, the water is weighed (1 g = 1 ml) or
  measured. Two runs of different length, for example 10 and 30 s. More precise
  than marks and suits powerful pumps.

A run should take at least 20 seconds, otherwise the press error is noticeable.

The measurement gives the flow, the delay before the first water and how much
drips after the stop. Watering time: the delay plus (dose minus afterflow)
divided by the flow.

The first screen of the wizard shows the parameters in effect for each plant and
a list of past calibrations with the one in effect marked.

Safety: the pump never runs longer than its limit, stops if the last mark does
not come in time, and stops if the wizard page is closed or the connection is
lost. The machine does not water while being calibrated.

With a collector it is enough to calibrate one plant. The others use its flow
adjusted for their own tube. Any plant can be calibrated separately.

In a small tank the flow drops noticeably as the tank empties. Then make a
second measurement with an almost empty tank and save it as a second level.

### When a calibration becomes stale

A calibration remembers what it was measured on: pump model, tank, collector and
tubes. If any of these changes, the plant is not watered and the card shows a
warning with two buttons:

- **Calibrate** opens the wizard;
- **Keep calibration** clears the warning if the change does not affect the flow.

The machine name, relays, schedules and pump limits do not affect calibration.

### Flow tuning

When you enter the actual tank volume, the calculation is compared with reality.
If the flow is clearly off, the card offers to correct it. A recalibration
reminder can be turned on in the settings.

The old way (flow from the pump datasheet, outlet height, correction) stays in
the machine form behind the "Advanced mode" checkbox.

## Pump

A pump model has a run limit per start, 300 s by default. The watchdog stops the
pump if it runs longer. The limit can be turned off, but then the pump will not
stop on time if a relay sticks. The pause between waterings gives the pump rest.

## Schedules

A plant has either its own schedule or a shared one. Shared schedules live on
the **Waterings** tab: one schedule for many plants of different machines. The
**Plants** button of a schedule lists all plants; check the ones it should water.

Dose: if a shared schedule has a dose, that dose is watered. Otherwise the
plant's dose. The seasonal factor of the schedule multiplies the dose.

A new or changed schedule counts from the moment it is saved: times that have
already passed are neither watered nor recorded as skipped.

## Power groups

If several machines share one power supply, put them into a power group (the
**Equipment** tab). The group sets how many pumps run at once, the pause between
starts and, optionally, how long a request may wait for a slot.

## Interface

- **Machines**: machine cards. A card is collapsed: water left, next watering and
  the **Water** and **Tank** buttons. **Stop** shows up while the pump runs or a
  watering is in progress. Everything else is in the **...** menu, details open
  with the arrow.
- **Waterings**: what is watering now and waiting in the queue, upcoming
  waterings, shared schedules and the journal. The journal survives restarts and
  lists skipped scheduled waterings with the reason.
- **Equipment**: tanks, pumps, collectors and power groups.
- **Problems**: open problems with a hint on what to do. The counter turns red
  when watering is impossible somewhere.
- The gear on the right: notifications, MQTT and calibration.

The **Water** dialog fills in the plant's dose from its schedule.

## Add-on options

On the add-on's **Configuration** tab:

| Option | What it does |
| --- | --- |
| `log_level` | Log detail: `debug`, `info`, `warning`, `error`. |
| `timezone` | Time zone for schedules and quiet hours, for example `Europe/Berlin`. Empty means the Home Assistant time zone. |

MQTT and notifications are set up in the interface, under the gear.

## MQTT

Over MQTT the machines appear in Home Assistant as devices. Turn MQTT on and
pick the broker in the interface settings:

- **Automatic**: the broker provided by Home Assistant, usually the Mosquitto
  add-on. The add-on gets the address and password itself.
- **Manual**: your own broker, host, port, username and password.

After saving, the add-on reconnects right away. The password is never sent back
to the interface: leaving the field empty keeps the old one.

## Push notifications

Pushes go through the Home Assistant Companion app. Every phone with the app is
a `notify.mobile_app_<name>` service. Install the app and sign in to your Home
Assistant.

Under the gear you choose which phones (none selected means all), what to
report, quiet hours and urgent pushes. With "Advanced settings" checked you can
change the notification texts and the address opened on tap.

- A repeat of the same trouble replaces the previous push, and "problem solved"
  replaces the problem push.
- Urgent pushes arrive right away, even during quiet hours. On Android they use
  a separate channel "PlantControl: срочно" with its own sound and vibration.
- Tapping a push opens the PlantControl panel.

Use the "Test push" button to check delivery.

## Problems and watering

While a blocking problem is open (no connection to Home Assistant, pump or valve
unavailable, unknown pump state, empty tank, stale calibration), nothing waters:
not by hand, not on schedule. The state is checked again right before every
watering. A valve or calibration problem of a plant only affects that plant.
Muting a problem does not allow watering.

## What appears in Home Assistant

Every machine becomes a device: water left and tank fill level, status, last
watering time, a problem flag, a "Water" button per plant, a dose field and a
"Tank refilled" button, handy to press from an automation triggered by an NFC
tag. For now these entities and push texts are named in Russian; you can rename
entities in Home Assistant and change the push texts in the advanced
notification settings.

Events on the bus (`plant_control_watering_done`, `plant_control_watering_failed`,
`plant_control_problem_opened` and others) let automations react on their own.

## Data and backups

Machines, equipment, schedules and the journal are stored in the add-on's `/data`
folder. It is kept across updates and included in Home Assistant backups. Use
export to move machines to another system.

## Updates and channels

New versions show up in Home Assistant by themselves. See the
[changelog](https://github.com/Mkilord/plant-control/blob/main/CHANGELOG.md) for
what changed.

| Channel | Repository URL | Versions |
| --- | --- | --- |
| Stable | `https://github.com/Mkilord/plant-control` | `0.2.0` |
| Beta | `https://github.com/Mkilord/plant-control#beta` | `0.2.0-beta.1` |
| Dev | `https://github.com/Mkilord/plant-control#dev-channel` | `0.2.0-dev.57` |

Each channel installs as a separate add-on with its own data. Use export and
import to move machines between channels.

## Troubleshooting

- Check the add-on's **Log** tab. For more detail set `log_level: debug` and
  restart the add-on.
- Look at the **Problems** tab in the interface: it tells you what to do.
- Report bugs in [Issues](https://github.com/Mkilord/plant-control/issues) with
  the add-on version and the log.
