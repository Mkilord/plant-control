// Справочники в интерфейсе: общий список, значения по умолчанию, короткие описания записей.
import { ref } from "vue";
import {
  api,
  type CatalogEntry,
  type CatalogItems,
  type CatalogKind,
  type CatalogListing,
  type Geometry,
} from "./api";
import { ml } from "./format";
import { t, type MessageKey } from "./i18n";

// Один список на всё приложение: формы и мастера видят одни и те же записи.
export const catalog = ref<CatalogListing>({
  tank: [],
  pump: [],
  collector: [],
  schedule: [],
  power: [],
});
export const catalogError = ref("");

export async function loadCatalog(): Promise<CatalogListing> {
  try {
    catalog.value = await api.catalog();
    catalogError.value = "";
  } catch (e) {
    catalogError.value = e instanceof Error ? e.message : String(e);
  }
  return catalog.value;
}

export function entriesOf<K extends CatalogKind>(kind: K): CatalogEntry<K>[] {
  return catalog.value[kind] as CatalogEntry<K>[];
}

export function findEntry<K extends CatalogKind>(
  kind: K,
  id: string | null | undefined,
): CatalogEntry<K> | undefined {
  return id ? entriesOf(kind).find((entry) => entry.id === id) : undefined;
}

export function itemName(kind: CatalogKind, id: string | null | undefined): string {
  return findEntry(kind, id)?.item.name ?? (id || "");
}

// Глубокая копия. structuredClone не принимает реактивные объекты Vue, а здесь они почти всегда.
export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function defaultItem<K extends CatalogKind>(kind: K): CatalogItems[K] {
  const defaults: CatalogItems = {
    tank: {
      name: "",
      geometry: { shape: "measured", volume_ml: 2000, height_mm: 150 },
      reserve_ml: 300,
    },
    pump: { name: "", max_runtime_s: 300, cooldown_s: 0, flow: null },
    collector: { name: "", outlets: 4, valve_lead_s: 0.5, valve_lag_s: 0.5 },
    schedule: {
      name: "",
      rule: { type: "weekly", days: [0, 3], times: ["08:00"] },
      dose_ml: null,
      season_factor: 1,
      catch_up_h: 3,
      min_gap_h: 6,
    },
    power: { name: "", max_concurrent: 1, min_start_gap_s: 2, max_wait_min: null },
  };
  return clone(defaults[kind]);
}

export const KIND_TITLE: Record<CatalogKind, MessageKey> = {
  tank: "catalog.kind.tank",
  pump: "catalog.kind.pump",
  collector: "catalog.kind.collector",
  schedule: "catalog.kind.schedule",
  power: "catalog.kind.power",
};

export const KIND_ICON = {
  tank: "tank",
  pump: "pump",
  collector: "collector",
  schedule: "clock",
  power: "sliders",
} as const;

// Объём бака в мл по геометрии: для подписи в списках.
export function capacityMl(geometry: Geometry): number {
  switch (geometry.shape) {
    case "measured":
      return geometry.volume_ml;
    case "vertical_cylinder":
      return (Math.PI * (geometry.diameter_mm / 2) ** 2 * geometry.height_mm) / 1000;
    case "horizontal_cylinder":
      return (Math.PI * (geometry.diameter_mm / 2) ** 2 * geometry.length_mm) / 1000;
    case "rectangular":
      return (geometry.width_mm * geometry.depth_mm * geometry.height_mm) / 1000;
  }
}

// Высота воды при полном баке, мм.
export function heightMm(geometry: Geometry): number {
  return geometry.shape === "horizontal_cylinder" ? geometry.diameter_mm : geometry.height_mm;
}

export function summary<K extends CatalogKind>(kind: K, item: CatalogItems[K]): string {
  switch (kind) {
    case "tank": {
      const tank = item as CatalogItems["tank"];
      return t("catalog.sum.tank", {
        volume: ml(capacityMl(tank.geometry)),
        reserve: ml(tank.reserve_ml),
      });
    }
    case "pump": {
      const pump = item as CatalogItems["pump"];
      return pump.max_runtime_s === null
        ? t("catalog.sum.pump_unlimited")
        : t("catalog.sum.pump", { max: pump.max_runtime_s });
    }
    case "collector": {
      const collector = item as CatalogItems["collector"];
      return t("catalog.sum.collector", { n: collector.outlets });
    }
    case "schedule": {
      const schedule = item as CatalogItems["schedule"];
      const rule = schedule.rule;
      const times = rule.times.map((value) => value.slice(0, 5)).join(", ");
      const when =
        rule.type === "weekly"
          ? rule.days.length === 7
            ? t("catalog.sum.every_day")
            : rule.days.map((day) => t(`weekday.${day}` as MessageKey)).join(" ")
          : t("catalog.sum.every_n", { n: rule.every_days });
      const dose = schedule.dose_ml ? `, ${ml(schedule.dose_ml)}` : "";
      return `${when}, ${times}${dose}`;
    }
    case "power": {
      const power = item as CatalogItems["power"];
      return t("catalog.sum.power", { n: power.max_concurrent, gap: power.min_start_gap_s });
    }
  }
  return "";
}
