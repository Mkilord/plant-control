# PlantControl

Ядро адресного полива растений. Содержит только бизнес-логику, без зависимостей от Home Assistant. Инфраструктура подключается позже через порты.

## Структура

- `src/plant_control/domain` - доменная модель
  - `pump.py` - насос: паспорт с моделью расхода, остывание, предел времени работы
  - `collector.py` - коллектор из нормально закрытых клапанов, открыт не больше одного
  - `tank.py` - бак: форма, объем, запас под насосом
  - `flow.py` - модели расхода насоса: постоянная, линейная, табличная
  - `connection.py` - трубка, выход у растения, маршрут
  - `watering.py` - расчет полива: доза, лишний объем трубок, напор, время
  - `machine.py` - поливальная машина, корень агрегата
- `src/plant_control/application` - порты и сервисы
  - `watering_service.py` - сценарий полива: клапан, насос, паузы, безопасное завершение
  - `safety_service.py` - безопасный старт, аварийная остановка, сторож насоса
  - `pump_service.py` - ручное включение и выключение насоса
- `addon/backend` - бэкенд add-on'а Home Assistant: REST API и связь с HA
- `addon/frontend` - веб-интерфейс на Vue 3 и TypeScript
- `experiments` - стенд для сравнения стратегий расчета, в ядро не входит
- `tests` - тесты, повторяют структуру `src`

## Запуск

```
uv sync
uv run pytest
uv run mypy src tests experiments
uv run ruff check .
```

Стенд:

```
uv run python -m experiments.bench
```

Параметры бака, трубок и насоса для стенда задаются в словаре `BASE` в `experiments/bench.py`.

## Бэкенд add-on'а

Бэкенд подключается к Home Assistant через WebSocket API. Внутри add-on'а токен выдает Supervisor, при разработке адрес и токен берутся из `addon/backend/.env` (образец в `.env.example`).

```
cd addon/backend
uv sync
uv run python -m plant_control_addon
```

Документация API: `http://localhost:8099/docs`. База SQLite лежит в `addon/backend/data`.

Основные эндпоинты:

- `GET/POST /api/machines`, `GET/PUT/DELETE /api/machines/{id}` - конфигурация машин
- `POST /api/machines/{id}/plan` - расчет полива без запуска
- `POST /api/machines/{id}/water` - полив в фоне, ход полива виден в статусе машины
- `POST /api/machines/{id}/stop` - аварийная остановка
- `POST /api/machines/{id}/tank/refill`, `PUT /api/machines/{id}/tank/volume` - долив и измеренный объем
- `GET /api/ha/entities` - реле из Home Assistant для выбора в настройках

## Веб-интерфейс

Сборка, после которой бэкенд сам отдает интерфейс на `http://localhost:8099` (нужен `PLANT_CONTROL_STATIC_DIR=../frontend/dist` в `addon/backend/.env`):

```
cd addon/frontend
npm install
npm run build
```

Разработка с перезагрузкой на лету: бэкенд запущен отдельно, интерфейс открывается на `http://localhost:5173`, запросы к API проксируются на бэкенд.

```
npm run dev
```
