"""Стенд: поливаем одинаковыми дозами, пока бак не опустеет, и сравниваем стратегии.

Стенд работает с расчётом напрямую, без машины и коллектора: здесь важна гидравлика,
а не клапаны.

Запуск из корня проекта:
    uv run python -m experiments.bench
"""

from typing import Any

from experiments.factory import (
    build_flow,
    build_head_model,
    build_plumbing,
    build_route,
    build_tank,
)
from plant_control.domain.errors import NotEnoughWaterError, PumpCannotDeliverError
from plant_control.domain.watering import calculate_watering

# Испытательный стенд: бак 2 л, нижние 500 мл под погружным насосом, рабочие 1500 мл.
# ВНИМАНИЕ: размеры бака, трубок и характеристики насоса - заглушки.
# Подставь свои: диаметр и высоту бака, длину и внутренний радиус трубок,
# расход и максимальный напор насоса из паспорта, высоту выхода над дном бака.
BASE: dict[str, Any] = {
    # Цилиндр диаметром 130 мм и высотой 151 мм - около 2000 мл.
    "tank": {"shape": "vertical_cylinder", "diameter_mm": 130, "height_mm": 151, "reserve_ml": 500},
    "flow": {"model": "linear", "max_flow_ml_s": 20, "max_head_mm": 800},
    "route": {"connection": {"length_mm": 700, "inner_radius_mm": 2}, "outlet_height_mm": 400},
    "plumbing": {"type": "direct", "back_to_tank_fraction": 0.5},
    "head_model": {"model": "mid"},
    "dose_ml": 100,
}

COLLECTOR = {"type": "collector", "supply": {"length_mm": 500, "inner_radius_mm": 2}}

# {**BASE, "flow": ...} - копия словаря BASE с заменой одного ключа.
EXPERIMENTS: dict[str, dict[str, Any]] = {
    "direct, half back to tank": BASE,
    "direct, all back to tank": {
        **BASE,
        "plumbing": {"type": "direct", "back_to_tank_fraction": 1.0},
    },
    "direct, all into plant": {
        **BASE,
        "plumbing": {"type": "direct", "back_to_tank_fraction": 0.0},
    },
    "collector": {**BASE, "plumbing": COLLECTOR},
    "collector, constant flow": {
        **BASE,
        "plumbing": COLLECTOR,
        "flow": {"model": "constant", "flow_ml_s": 20},
    },
}


def run(name: str, cfg: dict[str, Any]) -> None:
    tank = build_tank(cfg["tank"])
    flow = build_flow(cfg["flow"])
    route = build_route(cfg["route"])
    plumbing = build_plumbing(cfg["plumbing"])
    head_model = build_head_model(cfg["head_model"])

    print(
        f"\n=== {name} === tank {tank.volume_ml:.0f} ml "
        f"(usable {tank.usable_volume_ml:.0f}), dose {cfg['dose_ml']} ml"
    )
    print(
        f"{'#':>3} {'level mm':>9} {'head mm':>8} {'flow ml/s':>10} "
        f"{'pumped':>7} {'consumed':>9} {'time s':>7}"
    )

    supply_is_filled = False
    total_time = 0.0
    number = 0
    while True:
        try:
            plan = calculate_watering(
                tank=tank,
                flow=flow,
                route=route,
                dose_ml=cfg["dose_ml"],
                plumbing=plumbing,
                head_model=head_model,
                supply_is_filled=supply_is_filled,
            )
        except (NotEnoughWaterError, PumpCannotDeliverError) as error:
            print(f"    stop: {error}")
            break
        number += 1
        total_time += plan.duration_s
        print(
            f"{number:>3} {plan.level_start_mm:>9.1f} {plan.head_start_mm:>8.1f} "
            f"{plan.average_flow_ml_s:>10.2f} {plan.pumped_ml:>7.1f} "
            f"{plan.consumed_ml:>9.1f} {plan.duration_s:>7.2f}"
        )
        tank.draw(plan.consumed_ml)
        supply_is_filled = plumbing.requires_collector
    print(f"    waterings: {number}, total pump time: {total_time:.1f} s")


def main() -> None:
    for name, cfg in EXPERIMENTS.items():
        run(name, cfg)


if __name__ == "__main__":
    main()
