"""Версия и файлы для канала dev.

Канал dev - отдельная ветка dev-channel. Её собирает GitHub Actions из каждого
коммита в dev: та же ветка, только в config.yaml своя версия сборки, а в имени
пометка (dev). Так Home Assistant видит новую версию после каждого пуша в dev,
а в самой dev не появляются служебные коммиты.

Версия: следующая после версии из config.yaml плюс номер сборки.
    0.1.0          -> 0.1.1-dev.N  (вышел релиз, dev уже про следующий)
    0.2.0-beta.1   -> 0.2.0-dev.N  (готовится 0.2.0)
N - число коммитов в dev. dev двигается только вперёд, поэтому N только растёт,
и Supervisor считает каждую сборку новее предыдущей.

    python dev_channel.py version <count>   напечатать версию сборки
    python dev_channel.py apply <version>   переписать config.yaml и repository.yaml
"""

import re
import sys
from pathlib import Path

VERSION_LINE = re.compile(r'^version:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)
NAME_LINE = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$")
SUFFIX = " (dev)"


def base_version(config: str) -> str:
    match = VERSION_LINE.search(config)
    if match is None:
        raise ValueError("config.yaml has no version")
    return match.group(1)


def dev_version(base: str, build: int) -> str:
    match = SEMVER.match(base)
    if match is None:
        raise ValueError(f"version {base!r} is not X.Y.Z or X.Y.Z-suffix")
    major, minor, patch, prerelease = match.groups()
    if prerelease is None:
        # Релиз уже вышел: сборки dev идут к следующему патчу.
        patch = str(int(patch) + 1)
    return f"{major}.{minor}.{patch}-dev.{build}"


def with_version(config: str, version: str) -> str:
    return VERSION_LINE.sub(f'version: "{version}"', config, count=1)


def with_dev_name(text: str) -> str:
    def rename(match: re.Match[str]) -> str:
        name = match.group(1).strip('"')
        return match.group(0) if name.endswith(SUFFIX) else f'name: "{name}{SUFFIX}"'

    return NAME_LINE.sub(rename, text, count=1)


def main(argv: list[str]) -> None:
    root = Path(__file__).resolve().parents[2]
    config_path = root / "config.yaml"
    config = config_path.read_text(encoding="utf-8")
    match argv:
        case ["version", count]:
            print(dev_version(base_version(config), int(count)))
        case ["apply", version]:
            config_path.write_text(with_dev_name(with_version(config, version)), encoding="utf-8")
            repository = root / "repository.yaml"
            repository.write_text(
                with_dev_name(repository.read_text(encoding="utf-8")), encoding="utf-8"
            )
        case _:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
