# PlantControl

Ядро адресного полива растений. Содержит только бизнес-логику, без зависимостей от Home Assistant. Инфраструктура подключается позже через порты.

## Структура

- `src/plant_control/domain` - доменная модель: сущности, объекты-значения, правила
- `src/plant_control/application` - сервисы приложения и порты
- `tests` - тесты, повторяют структуру `src`

## Запуск

```
uv sync
uv run pytest
uv run mypy src tests
uv run ruff check .
```
