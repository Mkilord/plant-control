"""Пуш-уведомления и события в Home Assistant.

Ядро выдаёт событие (что случилось), здесь оно превращается в текст и уходит:
уведомление - пушем на телефоны через приложение Home Assistant
(сервисы notify.mobile_app_*), событие - на шину, чтобы автоматизации
могли реагировать сами.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from plant_control.application.notifications import Event, EventKind

log = logging.getLogger(__name__)

# Префикс событий на шине: plant_control_watering_done и так далее.
EVENT_PREFIX = "plant_control"

TITLES: dict[EventKind, str] = {
    EventKind.WATERING_DONE: "Полив выполнен",
    EventKind.WATERING_FAILED: "Полив не удался",
    EventKind.PROBLEM_OPENED: "Проблема с поливом",
    EventKind.PROBLEM_CLOSED: "Проблема решена",
    EventKind.SCHEDULE_SKIPPED: "Полив по расписанию пропущен",
}

PROBLEMS: dict[str, str] = {
    "ha_disconnected": "нет связи с Home Assistant",
    "pump_entity_missing": "насос не найден в Home Assistant",
    "valve_entity_missing": "клапан не найден в Home Assistant",
    "pump_state_unknown": "состояние насоса неизвестно",
    "valve_state_unknown": "состояние клапана неизвестно",
    "pump_overrun": "насос работал дольше предела",
    "tank_empty": "в баке нет воды",
    "tank_low": "в баке мало воды",
    "watering_failed": "полив не удался",
    "schedule_skipped": "полив по расписанию пропущен",
}

REASONS: dict[str, str] = {
    "too_late": "время полива давно прошло",
    "recently_watered": "полив уже был недавно",
}


# Тексты по умолчанию. В {скобках} - подстановки, их список в PLACEHOLDERS.
MESSAGES: dict[EventKind, str] = {
    EventKind.WATERING_DONE: "{machine}: полито {plant}, {dose}.",
    EventKind.WATERING_FAILED: "{machine}: не удалось полить {plant}. {error}",
    EventKind.PROBLEM_OPENED: "{machine}: {problem} ({details}).",
    EventKind.PROBLEM_CLOSED: "{machine}: {problem} - больше не наблюдается.",
    EventKind.SCHEDULE_SKIPPED: "{machine}: полив {plant} пропущен, {reason}.",
}

# Какие подстановки есть у каждого вида события.
PLACEHOLDERS: dict[EventKind, tuple[str, ...]] = {
    EventKind.WATERING_DONE: ("machine", "plant", "dose", "time"),
    EventKind.WATERING_FAILED: ("machine", "plant", "dose", "error", "time"),
    EventKind.PROBLEM_OPENED: ("machine", "problem", "details", "time"),
    EventKind.PROBLEM_CLOSED: ("machine", "problem", "time"),
    EventKind.SCHEDULE_SKIPPED: ("machine", "plant", "reason", "time"),
}


@dataclass(frozen=True, slots=True)
class Texts:
    """Свои тексты уведомлений. Пустое или отсутствующее - текст по умолчанию."""

    titles: dict[EventKind, str] = field(default_factory=dict)
    messages: dict[EventKind, str] = field(default_factory=dict)

    def title(self, kind: EventKind) -> str:
        return self.titles.get(kind, "").strip() or TITLES[kind]

    def message(self, kind: EventKind) -> str:
        return self.messages.get(kind, "").strip() or MESSAGES[kind]


DEFAULT_TEXTS = Texts()


def title_for(event: Event, texts: Texts = DEFAULT_TEXTS, timezone: str | None = None) -> str:
    return render(texts.title(event.kind), values_for(event, timezone))


def message_for(event: Event, texts: Texts = DEFAULT_TEXTS, timezone: str | None = None) -> str:
    """Человеческий текст события по шаблону."""
    return render(texts.message(event.kind), values_for(event, timezone))


def values_for(event: Event, timezone: str | None = None) -> dict[str, str]:
    """Значения подстановок события."""
    data = event.data
    problem = str(data.get("problem") or "")
    reason = str(data.get("reason") or "")
    at = event.at.astimezone(ZoneInfo(timezone)) if timezone else event.at
    return {
        "machine": event.machine_name,
        "plant": _plant(data),
        "dose": _dose(data),
        "error": str(data.get("error") or ""),
        "problem": PROBLEMS.get(problem, problem),
        "details": str(data.get("details") or ""),
        "reason": REASONS.get(reason, reason),
        "time": at.strftime("%H:%M"),
    }


def render(template: str, values: dict[str, str]) -> str:
    """Подставить значения. Неизвестная подстановка остаётся как есть, пустые скобки убираются."""
    text = _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)
    # "({details})" без подробностей превращается в "()": убрать вместе с пробелом перед ними.
    text = re.sub(r"\s*\(\s*\)", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _plant(data: dict[str, Any]) -> str:
    route = data.get("route_id")
    return f"«{route}»" if route else "растение"


def _dose(data: dict[str, Any]) -> str:
    dose = data.get("dose_ml")
    return f"{round(float(dose))} мл" if dose is not None else "доза не указана"


def check_template(template: str) -> list[str]:
    """Неизвестные подстановки в шаблоне: их стоит показать человеку."""
    known = {name for names in PLACEHOLDERS.values() for name in names}
    return sorted({name for name in _PLACEHOLDER.findall(template) if name not in known})


class PushGateway(Protocol):
    async def get_services(self) -> dict[str, dict[str, Any]]: ...

    async def call_service_data(self, domain: str, service: str, data: dict[str, Any]) -> None: ...


class EventFirer(Protocol):
    async def fire_event(self, event_type: str, data: dict[str, Any]) -> None: ...


# Сервисы notify.* приложения Home Assistant на телефонах так и называются.
MOBILE_APP_PREFIX = "mobile_app_"
# Каналы Android: у каждого свои звук и важность, настраиваются в телефоне.
CHANNEL = "PlantControl"
URGENT_CHANNEL = "PlantControl: срочно"
# Особый канал приложения HA: звук идёт через будильник, слышно и в беззвучном режиме.
ALARM_CHANNEL = "alarm_stream"


class NoPushTargetsError(RuntimeError):
    """Некуда слать пуш: в HA нет ни одного телефона с приложением."""


class PushNotifier:
    """Реализация NotifierPort: пуш на телефоны через приложение Home Assistant.

    Каждому телефону с приложением HA соответствует сервис notify.mobile_app_<имя>.
    Список devices пуст - пуш уходит на все такие телефоны, их список берётся
    у HA при каждой отправке, поэтому новый телефон подхватывается сам.

    Настройки меняются на ходу через configure: их правят в интерфейсе.
    """

    def __init__(
        self,
        ha: PushGateway,
        devices: Sequence[str] = (),
        *,
        open_url: str | None = None,
        critical: bool = False,
        texts: Texts = DEFAULT_TEXTS,
        timezone: str | None = None,
    ) -> None:
        self._ha = ha
        self._timezone = timezone
        self.configure(devices, open_url=open_url, critical=critical, texts=texts)

    def configure(
        self,
        devices: Sequence[str] = (),
        *,
        open_url: str | None = None,
        critical: bool = False,
        texts: Texts = DEFAULT_TEXTS,
    ) -> None:
        self._devices = [_service_name(device) for device in devices if device.strip()]
        self._open_url = open_url
        self._critical = critical
        self._texts = texts

    async def available(self) -> list[str]:
        """Все телефоны с приложением HA: mobile_app_pixel_7 и так далее."""
        services = await self._ha.get_services()
        return sorted(
            name for name in services.get("notify", {}) if name.startswith(MOBILE_APP_PREFIX)
        )

    async def targets(self) -> list[str]:
        """Сервисы notify, на которые уйдёт пуш: выбранные телефоны или все."""
        if self._devices:
            return list(self._devices)
        return await self.available()

    async def send(self, event: Event) -> None:
        await self.push(
            title_for(event, self._texts, self._timezone),
            message_for(event, self._texts, self._timezone),
            self._push_data(event),
        )

    async def push(self, title: str, message: str, data: dict[str, Any]) -> list[str]:
        """Отправить на все телефоны. Один недоступный телефон не мешает остальным.

        Возвращает телефоны, куда пуш ушёл. Не ушёл никуда - исключение.
        """
        targets = await self.targets()
        if not targets:
            raise NoPushTargetsError(
                "no phones with the Home Assistant app: install it and sign in"
            )
        payload = {"title": title, "message": message, "data": data}
        delivered: list[str] = []
        errors: list[str] = []
        for target in targets:
            try:
                await self._ha.call_service_data("notify", target, payload)
            except Exception as error:
                log.warning("cannot push to notify.%s: %s", target, error)
                errors.append(f"{target}: {error}")
            else:
                delivered.append(target)
        if not delivered:
            raise RuntimeError("push failed on every phone: " + "; ".join(errors))
        return delivered

    def base_data(self) -> dict[str, Any]:
        """Общее для всех пушей: группа и что открыть по нажатию."""
        data: dict[str, Any] = {"group": EVENT_PREFIX, "channel": CHANNEL}
        if self._open_url:
            # url - для iOS, clickAction - для Android.
            data["url"] = self._open_url
            data["clickAction"] = self._open_url
        return data

    def _push_data(self, event: Event) -> dict[str, Any]:
        data = self.base_data()
        # Пуш с тем же tag заменяет прежний: повтор беды не копится,
        # а "проблема решена" встаёт на место "проблема".
        data["tag"] = push_tag(event)
        if event.urgent:
            # Доставить сразу, даже если телефон экономит заряд.
            data["priority"] = "high"
            data["ttl"] = 0
            data["importance"] = "high"
            data["channel"] = URGENT_CHANNEL
            data["push"] = {"interruption-level": "time-sensitive"}
            if self._critical:
                data["channel"] = ALARM_CHANNEL
                data["push"] = {
                    "interruption-level": "critical",
                    "sound": {"name": "default", "critical": 1, "volume": 1.0},
                }
        return data


def push_tag(event: Event) -> str:
    """Метка пуша. Открытие и закрытие одной проблемы делят метку."""
    if event.kind in (EventKind.PROBLEM_OPENED, EventKind.PROBLEM_CLOSED):
        problem = event.data.get("problem")
        target = event.data.get("target")
        suffix = f"problem_{problem}_{target}" if target else f"problem_{problem}"
        return f"{EVENT_PREFIX}_{event.machine_id}_{suffix}"
    return f"{EVENT_PREFIX}_{event.machine_id}_{event.kind.value}"


def _service_name(device: str) -> str:
    """ "notify.mobile_app_pixel" и "mobile_app_pixel" - одно и то же."""
    name = device.strip()
    return name.removeprefix("notify.")


class HaEventSink:
    """Реализация EventSinkPort: событие на шине Home Assistant."""

    def __init__(self, ha: EventFirer) -> None:
        self._ha = ha

    async def publish(self, event: Event) -> None:
        await self._ha.fire_event(
            f"{EVENT_PREFIX}_{event.kind.value}",
            {
                "machine_id": event.machine_id,
                "machine_name": event.machine_name,
                "at": event.at.isoformat(),
                **event.data,
            },
        )
