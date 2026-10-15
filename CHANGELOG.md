# Changelog

All notable changes to PlantControl are listed here. Versions follow
[Semantic Versioning](https://semver.org/); beta versions carry a `-beta.N` suffix.

## 0.1.0-beta.1

First public beta.

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
