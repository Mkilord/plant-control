"""Сборка стратегий из словаря. Конфигурация эксперимента - это данные."""

from typing import Any

from plant_control.domain.connection import Connection, Outlet, Route
from plant_control.domain.flow import ConstantFlow, FlowCurve, LinearFlow, TableFlow
from plant_control.domain.tank import (
    HorizontalCylinder,
    RectangularTank,
    Tank,
    TankGeometry,
    VerticalCylinder,
)
from plant_control.domain.watering import (
    CollectorPlumbing,
    DirectPlumbing,
    HeadModel,
    MidDoseHead,
    Plumbing,
    StartLevelHead,
    StepwiseHead,
)

# dict[str, Any] - словарь со строковыми ключами и любыми значениями.
Config = dict[str, Any]


def build_geometry(cfg: Config) -> TankGeometry:
    # match - аналог switch с разбором значений (Python 3.10+).
    match cfg["shape"]:
        case "vertical_cylinder":
            return VerticalCylinder(cfg["diameter_mm"], cfg["height_mm"])
        case "horizontal_cylinder":
            return HorizontalCylinder(cfg["diameter_mm"], cfg["length_mm"])
        case "rectangular":
            return RectangularTank(cfg["width_mm"], cfg["depth_mm"], cfg["height_mm"])
        case other:
            raise ValueError(f"unknown tank shape: {other}")


def build_tank(cfg: Config) -> Tank:
    """Запас под насосом задаётся либо reserve_ml, либо intake_height_mm."""
    geometry = build_geometry(cfg)
    volume = cfg.get("volume_ml")
    if "reserve_ml" in cfg:
        return Tank.with_reserve(geometry, cfg["reserve_ml"], volume)
    return Tank(
        geometry,
        volume_ml=geometry.capacity_ml() if volume is None else volume,
        intake_height_mm=cfg.get("intake_height_mm", 0.0),
    )


def build_flow(cfg: Config) -> FlowCurve:
    match cfg["model"]:
        case "constant":
            return ConstantFlow(cfg["flow_ml_s"])
        case "linear":
            return LinearFlow(cfg["max_flow_ml_s"], cfg["max_head_mm"])
        case "table":
            return TableFlow(tuple((float(h), float(q)) for h, q in cfg["points"]))
        case other:
            raise ValueError(f"unknown flow model: {other}")


def build_connection(cfg: Config) -> Connection:
    return Connection(cfg["length_mm"], cfg["inner_radius_mm"])


def build_route(cfg: Config) -> Route:
    return Route(
        connection=build_connection(cfg["connection"]),
        outlet=Outlet(cfg["outlet_height_mm"]),
        correction=cfg.get("correction", 1.0),
    )


def build_plumbing(cfg: Config) -> Plumbing:
    match cfg["type"]:
        case "direct":
            return DirectPlumbing(cfg.get("back_to_tank_fraction", 0.5))
        case "collector":
            return CollectorPlumbing(build_connection(cfg["supply"]))
        case other:
            raise ValueError(f"unknown plumbing: {other}")


def build_head_model(cfg: Config) -> HeadModel:
    match cfg["model"]:
        case "start":
            return StartLevelHead()
        case "mid":
            return MidDoseHead()
        case "stepwise":
            return StepwiseHead(cfg.get("steps", 20))
        case other:
            raise ValueError(f"unknown head model: {other}")
