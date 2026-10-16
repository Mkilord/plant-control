# Участие в разработке PlantControl

[English](CONTRIBUTING.md) | **Русский**

Сообщения об ошибках, идеи и pull request'ы приветствуются. Если изменение больше
мелкой правки, сначала откройте issue, чтобы договориться о подходе.

Присылая изменения, вы соглашаетесь, что они распространяются на условиях
[GPL-3.0-or-later](LICENSE), как и весь проект.

## Структура

- `src/plant_control`: ядро, логика полива без зависимостей от Home Assistant.
  - `domain`: насос, бак, модели расхода, трубки и коллектор, расчёт полива,
    машина, расписание, проблемы, группы питания.
  - `application`: порты и сервисы. Сценарий полива, безопасность (безопасный
    старт, аварийная остановка, сторож насоса), очередь, планировщик, проверка
    состояния, уведомления.
- `addon/backend`: бэкенд дополнения. REST API (FastAPI), клиент Home Assistant,
  MQTT, уведомления, хранилище.
- `addon/frontend`: веб-интерфейс (Vue 3, TypeScript, Vite).
- `config.yaml`, `Dockerfile`, `run.py`, `translations/`: упаковка в дополнение
  Home Assistant. `repository.yaml` делает репозиторий репозиторием дополнений.
- `experiments`: стенд для сравнения стратегий расчёта, в дополнение не входит.
- `tests`: тесты ядра, повторяют структуру `src`.

## Подготовка

Нужны Python 3.13+, [uv](https://docs.astral.sh/uv/) и Node.js 22.

Ядро:

```
uv sync
uv run pytest
uv run mypy src tests experiments
uv run ruff check .
```

Стенд: `uv run python -m experiments.bench`, параметры в словаре `BASE` в
`experiments/bench.py`.

Бэкенд подключается к настоящему Home Assistant через WebSocket API: адрес и
долгоживущий токен задаются в `addon/backend/.env` (образец в `.env.example`).

```
cd addon/backend
uv sync
uv run pytest
uv run python -m plant_control_addon
```

Документация API: `http://localhost:8099/docs`. База SQLite лежит в
`addon/backend/data`.

Фронт с перезагрузкой на лету (бэкенд запущен отдельно, запросы к API
проксируются на него):

```
cd addon/frontend
npm ci
npm run dev
```

Интерфейс открывается на `http://localhost:5173`. `npm run build` собирает `dist/`,
и бэкенд отдаёт его сам, если задано `PLANT_CONTROL_STATIC_DIR=../frontend/dist`.

Те же проверки CI запускает на каждый push и pull request
(`.github/workflows/ci.yaml`).

### Проверка на настоящем Home Assistant

Скопируйте репозиторий в `/addons/plant_control` на машине с Home Assistant
(через Samba share или SSH) и закомментируйте строку `image:` в `config.yaml`.
Дополнение появится в разделе **Локальные дополнения**, и Supervisor соберёт его
из `Dockerfile`. Чтобы Home Assistant подхватил изменения, увеличьте `version`
или нажмите **Пересобрать**.

## Ветки и каналы

| Ветка | Что в ней | Адрес в Home Assistant |
| --- | --- | --- |
| `dev` | Повседневная работа. Pull request'ы сюда. | нет |
| `dev-channel` | Последняя сборка `dev`. Ведёт GitHub Actions, руками не трогать. | `...plant-control#dev-channel` |
| `beta` | Бета: то, что готово к проверке на настоящих установках. | `...plant-control#beta` |
| `main` | Только выпущенные версии. | `...plant-control` |

Изменения идут в одну сторону: `dev`, потом `beta`, потом `main`, всегда
перемоткой (fast-forward), так что ветки не расходятся.

Home Assistant различает дополнения по адресу репозитория. Каждый канал ставится
отдельным дополнением со своими данными, поэтому имена веток каналов не меняются.

## Версии

Версия в `config.yaml` всегда говорит, какой релиз готовится. Она же тег образа.
Home Assistant предлагает обновление, только когда версия растёт.

| Где | Что в `config.yaml` | Версия сборки | Кто ставит |
| --- | --- | --- | --- |
| `dev` после релиза `0.1.0` | `0.2.0-dev` | `0.2.0-dev.N` | вы, сразу после релиза |
| `dev`, готовим бету | `0.2.0-beta.1` | `0.2.0-dev.N` | вы, перед бетой |
| `beta` | `0.2.0-beta.1` | `0.2.0-beta.1` | приходит из `dev` |
| `main` | `0.2.0` | `0.2.0` | приходит из `beta` |

`N` это число коммитов в `dev`. Его подставляет GitHub Actions, в `config.yaml`
его не пишут. Интерфейс показывает ту же версию: `Dockerfile` передаёт её в
сборку фронта.

## Dev-канал

Каждый пуш в `dev` запускает **Dev channel** (`.github/workflows/dev-channel.yaml`):

1. Считается версия сборки: `X.Y.Z` из `config.yaml` плюс `-dev.N`.
2. **Builder** собирает образы с этой версией.
3. Когда образы готовы, ветка `dev-channel` перезаписывается этим коммитом с
   версией сборки и именем "PlantControl (dev)".

Так Home Assistant не увидит версию, для которой ещё нет образа. Новый пуш
отменяет недоделанную сборку, в канал уходит последний коммит.

## История изменений

Всё, что попало в `dev`, сразу записывается в `CHANGELOG.md` в раздел
`Unreleased`. При выпуске раздел получает номер версии.

## Выпуск версии

### Бета

1. В `dev` поставьте в `config.yaml` версию беты, например `0.2.0-beta.1`, и
   переименуйте раздел `Unreleased` в `CHANGELOG.md` в эту версию.
2. Закоммитьте, перемотайте `beta` и отправьте:

   ```
   git checkout beta
   git merge --ff-only dev
   git push origin beta
   git checkout dev
   ```

3. Workflow **Builder** соберёт `ghcr.io/mkilord/plant-control-{amd64,aarch64}`
   этой версии. Дождитесь зелёного статуса: пока образа нет, Home Assistant видит
   новую версию, но установить её не может.

### Стабильная

1. В `dev` (к этому моменту она совпадает с `beta`) поставьте версию без
   суффикса, например `0.2.0`, и сведите бета-разделы `CHANGELOG.md` в один.
2. Закоммитьте и перемотайте оба канала:

   ```
   git checkout beta
   git merge --ff-only dev
   git push origin beta
   git checkout main
   git merge --ff-only beta
   git push origin main
   git tag v0.2.0
   git push origin v0.2.0
   git checkout dev
   ```

3. Дождитесь **Builder** и создайте на GitHub выпуск (Release) из тега, вставив
   раздел из `CHANGELOG.md` в описание.
4. В `dev` сразу поставьте следующую версию, например `0.3.0-dev`, и добавьте в
   `CHANGELOG.md` пустой раздел `Unreleased`.

### Один раз после первой сборки

Откройте пакеты на GitHub (профиль, **Packages**, `plant-control-amd64` и
`plant-control-aarch64`, **Package settings**) и поставьте видимость
**Public**. Иначе Home Assistant не сможет скачать образы.
