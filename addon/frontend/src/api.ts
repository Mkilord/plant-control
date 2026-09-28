import { hasMessage, t } from "./i18n";

// Типы повторяют схемы бэкенда (addon/backend/.../config.py и api/machines.py).

export type Geometry =
  | { shape: "measured"; volume_ml: number; height_mm: number }
  | { shape: "vertical_cylinder"; diameter_mm: number; height_mm: number }
  | { shape: "horizontal_cylinder"; diameter_mm: number; length_mm: number }
  | { shape: "rectangular"; width_mm: number; depth_mm: number; height_mm: number };

export type Flow =
  | { model: "constant"; flow_ml_s: number }
  | { model: "linear"; max_flow_ml_s: number; max_head_mm: number }
  | { model: "table"; points: [number, number][] };

export interface ConnectionConfig {
  length_mm: number;
  inner_diameter_mm: number;
}

export type Plumbing =
  | { type: "direct"; back_to_tank_fraction: number }
  | { type: "collector"; supply: ConnectionConfig };

export interface RouteConfig {
  id: string;
  name: string;
  valve_entity_id: string | null;
  connection: ConnectionConfig;
  outlet_height_mm: number;
  correction: number;
}

export type HeadModel = "start" | "mid" | "stepwise";

export interface MachineConfig {
  name: string;
  tank: { geometry: Geometry; reserve_ml: number };
  pump: { entity_id: string; flow: Flow; max_runtime_s: number; cooldown_s: number };
  plumbing: Plumbing;
  head_model: HeadModel;
  routes: RouteConfig[];
  timings: { valve_lead_s: number; valve_lag_s: number };
}

export interface WateringResult {
  route_id: string;
  dose_ml: number;
  started_at: string;
  finished_at: string;
  ok: boolean;
  error: string | null;
}

export interface MachineStatus {
  busy: boolean;
  tank: {
    volume_ml: number;
    usable_ml: number;
    capacity_ml: number;
    reserve_ml: number;
    level_mm: number;
  };
  pump: { state: "on" | "off" | "unknown"; started_at: string | null; stopped_at: string | null };
  valves: Record<string, "open" | "closed" | "unknown">;
  supply_is_filled: boolean;
  last_watering: WateringResult | null;
}

export interface Machine {
  id: string;
  config: MachineConfig;
  status: MachineStatus;
}

export interface Plan {
  dose_ml: number;
  pumped_ml: number;
  consumed_ml: number;
  level_start_mm: number;
  level_end_mm: number;
  head_start_mm: number;
  head_end_mm: number;
  flow_start_ml_s: number;
  flow_end_ml_s: number;
  duration_s: number;
}

export interface HaEntity {
  entity_id: string;
  domain: string;
  name: string;
  state: string;
}

export interface Health {
  status: string;
  home_assistant: string;
  machines: number;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null,
  ) {
    super(message);
  }
}

interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  // Путь без ведущего слэша: так он считается от текущей страницы и работает внутри Ingress.
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) {
    return undefined as T;
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw toError(response.status, data);
  }
  return data as T;
}

function toError(status: number, data: unknown): ApiError {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    // Ошибка домена: {"error": "NotEnoughWaterError", "detail": "..."}
    if (typeof record.error === "string") {
      const key = `errors.${record.error}`;
      const text = hasMessage(key) ? t(key) : String(record.detail ?? record.error);
      return new ApiError(text, status, record.error);
    }
    // Ошибка валидации FastAPI: {"detail": [{"loc": [...], "msg": "..."}]}
    if (Array.isArray(record.detail)) {
      const issues = (record.detail as ValidationIssue[])
        .map((issue) => `${issue.loc.filter((part) => part !== "body").join(".")}: ${issue.msg}`)
        .join("; ");
      return new ApiError(issues, status, "ValidationError");
    }
    if (typeof record.detail === "string") {
      return new ApiError(record.detail, status, null);
    }
  }
  return new ApiError(t("errors.status", { status }), status, null);
}

export const api = {
  health: () => request<Health>("GET", "api/health"),
  haEntities: () => request<HaEntity[]>("GET", "api/ha/entities"),
  listMachines: () => request<Machine[]>("GET", "api/machines"),
  getMachine: (id: string) => request<Machine>("GET", `api/machines/${id}`),
  createMachine: (config: MachineConfig) => request<Machine>("POST", "api/machines", config),
  updateMachine: (id: string, config: MachineConfig) =>
    request<Machine>("PUT", `api/machines/${id}`, config),
  deleteMachine: (id: string) => request<void>("DELETE", `api/machines/${id}`),
  plan: (id: string, routeId: string, doseMl: number) =>
    request<Plan>("POST", `api/machines/${id}/plan`, { route_id: routeId, dose_ml: doseMl }),
  water: (id: string, routeId: string, doseMl: number) =>
    request<Plan>("POST", `api/machines/${id}/water`, { route_id: routeId, dose_ml: doseMl }),
  stop: (id: string) => request<{ errors: string[] }>("POST", `api/machines/${id}/stop`),
  refill: (id: string, volumeMl: number | null) =>
    request<Machine>("POST", `api/machines/${id}/tank/refill`, { volume_ml: volumeMl }),
  setVolume: (id: string, volumeMl: number) =>
    request<Machine>("PUT", `api/machines/${id}/tank/volume`, { volume_ml: volumeMl }),
};

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
