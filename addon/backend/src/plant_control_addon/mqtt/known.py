"""Машины, которые этот add-on публиковал в MQTT.

Брокер общий: на нём могут быть сущности другого экземпляра PlantControl
(например, стабильного и dev-канала). Убирать можно только своё, поэтому
add-on помнит id машин, которые сам публиковал, в том числе удалённых.
"""

import json
from collections.abc import Iterable
from typing import Protocol

SETTINGS_KEY = "mqtt_machines"


class SettingsStore(Protocol):
    async def load_setting(self, key: str) -> str | None: ...

    async def save_setting(self, key: str, value_json: str) -> None: ...

    async def journal_machine_ids(self) -> set[str]: ...


class KnownMachines:
    def __init__(self, store: SettingsStore | None = None) -> None:
        self._store = store
        self._ids: set[str] = set()
        self._loaded = store is None

    def __contains__(self, machine_id: object) -> bool:
        return machine_id in self._ids

    async def load(self, current: Iterable[str]) -> None:
        if self._loaded or self._store is None:
            return
        raw = await self._store.load_setting(SETTINGS_KEY)
        if raw is None:
            # Первый запуск с этим списком: свои машины, в том числе давно удалённые,
            # видны по журналам поливов, калибровок и проблем.
            self._ids = set(current) | await self._store.journal_machine_ids()
            await self._save()
        else:
            self._ids = {str(machine_id) for machine_id in json.loads(raw)}
        self._loaded = True

    async def add(self, machine_ids: Iterable[str]) -> None:
        new = set(machine_ids) - self._ids
        if new:
            self._ids |= new
            await self._save()

    async def _save(self) -> None:
        if self._store is not None:
            await self._store.save_setting(SETTINGS_KEY, json.dumps(sorted(self._ids)))
