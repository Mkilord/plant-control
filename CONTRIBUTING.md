# Contributing to PlantControl

**English** | [Русский](CONTRIBUTING.ru.md)

Bug reports, ideas and pull requests are welcome. For anything larger than a small
fix, please open an issue first so we can agree on the approach.

By contributing you agree that your contribution is licensed under the
[GPL-3.0-or-later](LICENSE), like the rest of the project.

## Project layout

- `src/plant_control`: the core, watering logic without any Home Assistant
  dependency.
  - `domain`: pump, tank, flow models, tubes and collector, watering calculation,
    machine, schedule, problems, power groups.
  - `application`: ports and services. Watering scenario, safety (safe start,
    emergency stop, pump watchdog), queue, scheduler, health checks, notifications.
- `addon/backend`: the add-on backend. REST API (FastAPI), Home Assistant client,
  MQTT, notifications, storage.
- `addon/frontend`: the web interface (Vue 3, TypeScript, Vite).
- `config.yaml`, `Dockerfile`, `run.py`, `translations/`: Home Assistant add-on
  packaging. `repository.yaml` makes this repository an add-on repository.
- `experiments`: a bench for comparing calculation strategies, not part of the
  add-on.
- `tests`: core tests, mirroring `src`.

## Development setup

You need Python 3.13+, [uv](https://docs.astral.sh/uv/) and Node.js 22.

Core:

```
uv sync
uv run pytest
uv run mypy src tests experiments
uv run ruff check .
```

Backend (connects to a real Home Assistant over the WebSocket API; put the address
and a long-lived access token into `addon/backend/.env`, see `.env.example`):

```
cd addon/backend
uv sync
uv run pytest
uv run python -m plant_control_addon
```

API docs are served at `http://localhost:8099/docs`. The SQLite database lives in
`addon/backend/data`.

Frontend with hot reload (the backend runs separately, API requests are proxied):

```
cd addon/frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. `npm run build` produces `dist/`, which the backend
serves itself when `PLANT_CONTROL_STATIC_DIR=../frontend/dist` is set.

CI runs the same checks for every push and pull request
(`.github/workflows/ci.yaml`).

### Testing the add-on on a real Home Assistant

Copy the repository to `/addons/plant_control` on the Home Assistant machine
(Samba share or SSH add-on) and comment out the `image:` line in `config.yaml`.
The add-on then shows up under **Local add-ons** and the Supervisor builds it
from the `Dockerfile`. Bump `version` to make Home Assistant pick up changes, or
use **Rebuild**.

## Branches and channels

| Branch | What it holds | Address in Home Assistant |
| --- | --- | --- |
| `dev` | Day-to-day work. Pull requests go here. | none |
| `dev-channel` | The latest `dev` build. Maintained by GitHub Actions, do not push to it. | `...plant-control#dev-channel` |
| `beta` | Beta: what is ready for testing on real setups. | `...plant-control#beta` |
| `main` | Released versions only. | `...plant-control` |

Changes flow one way: `dev`, then `beta`, then `main`, always as fast-forward
merges, so the branches never diverge.

Home Assistant tells add-ons apart by the repository address. Each channel
installs as a separate add-on with its own data, so channel branch names never
change.

## Versions

The version in `config.yaml` always says which release is being prepared. It is
also the image tag. Home Assistant offers an update only when the version grows.

| Where | `config.yaml` | Build version | Who sets it |
| --- | --- | --- | --- |
| `dev` after releasing `0.1.0` | `0.2.0-dev` | `0.2.0-dev.N` | you, right after the release |
| `dev`, preparing a beta | `0.2.0-beta.1` | `0.2.0-dev.N` | you, before the beta |
| `beta` | `0.2.0-beta.1` | `0.2.0-beta.1` | comes from `dev` |
| `main` | `0.2.0` | `0.2.0` | comes from `beta` |

`N` is the number of commits in `dev`. GitHub Actions fills it in; it is never
written to `config.yaml`. The interface shows the same version: the `Dockerfile`
passes it into the frontend build.

## Dev channel

Every push to `dev` runs **Dev channel** (`.github/workflows/dev-channel.yaml`):

1. The build version is `X.Y.Z` from `config.yaml` plus `-dev.N`.
2. **Builder** builds the images for that version.
3. Once the images exist, the `dev-channel` branch is overwritten with this
   commit, the build version and the name "PlantControl (dev)".

So Home Assistant never sees a version without an image. A new push cancels an
unfinished build, so the channel always gets the latest commit.

## Changelog

Everything that lands in `dev` goes into the `Unreleased` section of
`CHANGELOG.md` right away. On release the section gets the version number.

## Releasing

### Beta

1. On `dev`, set the beta version in `config.yaml`, for example `0.2.0-beta.1`,
   and rename the `Unreleased` section of `CHANGELOG.md` to that version.
2. Commit, then move `beta` forward and push:

   ```
   git checkout beta
   git merge --ff-only dev
   git push origin beta
   git checkout dev
   ```

3. The **Builder** workflow builds `ghcr.io/mkilord/plant-control-{amd64,aarch64}`
   for that version. Wait until it is green: until the image exists, Home Assistant
   sees the new version but cannot install it.

### Stable

1. On `dev` (which equals `beta` at this point), set the version without a
   suffix, for example `0.2.0`, and merge the beta sections of `CHANGELOG.md` into
   one.
2. Commit and move both channels forward:

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

3. Wait for **Builder**, then create a GitHub release from the tag with the
   changelog section as notes.
4. On `dev`, set the next version right away, for example `0.3.0-dev`, and add an
   empty `Unreleased` section to `CHANGELOG.md`.

### One-time setup

After the very first image build, open the packages on GitHub (profile,
**Packages**, `plant-control-amd64` and `plant-control-aarch64`, **Package
settings**) and set visibility to **Public**. Otherwise Home Assistant cannot pull
the images.
