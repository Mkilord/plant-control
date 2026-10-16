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
  | { type: "collector"; collector_type: string; supply: ConnectionConfig };

export type Rule =
  | { type: "weekly"; days: number[]; times: string[] }
  | { type: "interval"; every_days: number; times: string[]; start_date: string | null };

export interface ScheduleConfig {
  enabled: boolean;
  rule: Rule;
  dose_ml: number | null;
  season_factor: number;
  catch_up_h: number;
  min_gap_h: number;
}

export interface ScheduleLink {
  template: string;
  enabled: boolean;
}

export interface FlowPoint {
  tank_volume_ml: number;
  flow_ml_s: number;
}

export interface RouteCalibration {
  flow_points: FlowPoint[];
  prime_s: number;
  afterflow_ml: number;
  method: "marks" | "timed" | "manual";
  calibrated_at: string | null;
  spread_pct: number | null;
  record_id: number | null;
  // На чём сделан замер. Не совпадает с текущим железом - калибровка устарела.
  fingerprint?: string | null;
  // Калибровка пришла с копией машины: имя исходной машины.
  copied_from?: string | null;
}

export interface RouteConfig {
  id: string;
  name: string;
  valve_entity_id: string | null;
  connection: ConnectionConfig;
  outlet_height_mm: number;
  correction: number;
  default_dose_ml: number;
  schedule: ScheduleConfig | null;
  // Расписание из справочника. Своё расписание и ссылка не бывают вместе.
  schedule_link: ScheduleLink | null;
  // Свой замер маршрута. null - наследует расход базового маршрута.
  calibration: RouteCalibration | null;
}

// calibrated - полив по калибровке маршрутов; advanced - по паспорту насоса.
export type FlowMode = "calibrated" | "advanced";

export type HeadModel = "start" | "mid" | "stepwise";

// Машина как её хранят: ссылки на справочники плюс своё (трубки, растения, реле).
export interface MachineConfig {
  name: string;
  tank_type: string;
  pump: { model: string; entity_id: string };
  plumbing: Plumbing;
  head_model: HeadModel;
  flow_mode: FlowMode;
  base_route: string | null;
  routes: RouteConfig[];
  power_group: string | null;
}

// Та же машина с подставленными справочниками. Только для чтения.
export interface MachineSetup {
  tank: { geometry: Geometry; reserve_ml: number };
  pump: { entity_id: string; flow: Flow | null; max_runtime_s: number | null; cooldown_s: number };
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

export interface RouteFlowStatus {
  route_id: string;
  // own - свой замер, inherited - от базового маршрута, none - замера нет, advanced - паспорт.
  source: "own" | "inherited" | "none" | "advanced";
  inherited_from: string | null;
  flow_points: FlowPoint[];
  prime_s: number | null;
  afterflow_ml: number | null;
  calibrated_at: string | null;
  due: boolean;
  // Насос, бак или трубки поменялись после замера: поливать нельзя.
  stale: boolean;
  copied_from: string | null;
}

export interface FlowSuggestion {
  factor: number;
  expected_ml: number;
  actual_ml: number;
  waterings: number;
  created_at: string;
}

export interface MachineStatus {
  busy: boolean;
  calibration_session: string | null;
  flows: RouteFlowStatus[];
  flow_suggestion: FlowSuggestion | null;
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
  schedules: ScheduleStatus[];
  queue: QueueItem[];
  // Проблемы, из-за которых поливать нельзя. route_scoped - мешает только растению target.
  blockers: Blocker[];
}

export interface Blocker {
  kind: string;
  target: string;
  route_scoped: boolean;
  details: string;
}

// --- Уведомления ---

export type EventKind =
  | "watering_done"
  | "watering_failed"
  | "problem_opened"
  | "problem_closed"
  | "schedule_skipped";

export const EVENT_KINDS: EventKind[] = [
  "watering_done",
  "watering_failed",
  "problem_opened",
  "problem_closed",
  "schedule_skipped",
];

export interface EventText {
  title: string;
  message: string;
}

export interface NotificationSettings {
  enabled: boolean;
  devices: string[];
  critical: boolean;
  events: EventKind[];
  quiet_from: string;
  quiet_to: string;
  advanced: boolean;
  texts: Partial<Record<EventKind, EventText>>;
  open_url: string;
}

export interface PushDevices {
  available: string[];
  targets: string[];
}

// --- MQTT ---

export interface MqttSettings {
  enabled: boolean;
  mode: "auto" | "manual";
  host: string;
  port: number;
  username: string;
  // Пароль сервер не отдаёт: только признак, что он задан.
  has_password: boolean;
  discovery_prefix: string;
}

// Правка: password null - оставить прежний.
export type MqttSettingsIn = Omit<MqttSettings, "has_password"> & { password: string | null };

export interface MqttStatus {
  state: "off" | "no_broker" | "connecting" | "connected" | "error";
  source: "" | "supervisor" | "env" | "manual";
  broker: string;
  error: string | null;
}

export interface NotificationTemplate {
  kind: EventKind;
  title: string;
  message: string;
  placeholders: string[];
}

export interface ScheduleStatus {
  route_id: string;
  // Расписание из справочника. null - своё.
  template: string | null;
  enabled: boolean;
  dose_ml: number;
  next_run_at: string | null;
  last_run_at: string | null;
}

export interface QueueItem {
  id: string;
  machine_id: string;
  route_id: string;
  dose_ml: number;
  source: "manual" | "schedule";
  state: "queued" | "running" | "done" | "failed" | "cancelled" | "expired" | "skipped";
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  position: number | null;
  // Названия для показа. machine_name null - машину уже удалили.
  machine_name: string | null;
  plant_name: string;
}

export interface QueueView {
  running: QueueItem[];
  queued: QueueItem[];
  history: QueueItem[];
}

export interface Schedule {
  id: string;
  machine_id: string;
  machine_name: string;
  route_id: string;
  enabled: boolean;
  dose_ml: number;
  next_run_at: string | null;
  last_run_at: string | null;
}

export interface Problem {
  id: string;
  machine_id: string;
  kind: string;
  target: string;
  severity: "info" | "warning" | "error";
  blocking: boolean;
  details: string;
  opened_at: string;
  last_seen_at: string;
  acknowledged: boolean;
  muted_until: string | null;
}

export interface Machine {
  id: string;
  config: MachineConfig;
  setup: MachineSetup;
  status: MachineStatus;
}

// --- Экспорт и импорт ---

export interface ExportBundle {
  format: "plant-control-machines";
  version: 1;
  exported_at: string;
  catalog: Partial<Record<CatalogKind, Record<string, unknown>>>;
  machines: { id: string; config: MachineConfig }[];
}

export interface ImportPlan {
  machines: { id: string; name: string; plants: number; taken: Record<string, string> }[];
  new_items: number;
  reused_items: number;
}

// --- Справочники ---

export type CatalogKind = "tank" | "pump" | "collector" | "schedule" | "power";
export const CATALOG_KINDS: CatalogKind[] = ["tank", "pump", "collector", "schedule", "power"];

export interface TankType {
  name: string;
  geometry: Geometry;
  reserve_ml: number;
}

export interface PumpModel {
  name: string;
  // null - предел работы выключен.
  max_runtime_s: number | null;
  cooldown_s: number;
  flow: Flow | null;
}

export interface CollectorType {
  name: string;
  outlets: number;
  valve_lead_s: number;
  valve_lag_s: number;
}

export interface ScheduleTemplate {
  name: string;
  rule: Rule;
  dose_ml: number | null;
  season_factor: number;
  catch_up_h: number;
  min_gap_h: number;
}

export interface PowerGroup {
  name: string;
  max_concurrent: number;
  min_start_gap_s: number;
  max_wait_min: number | null;
}

export interface CatalogItems {
  tank: TankType;
  pump: PumpModel;
  collector: CollectorType;
  schedule: ScheduleTemplate;
  power: PowerGroup;
}

export interface CatalogUser {
  machine_id: string;
  name: string;
  routes: string[];
}

export interface CatalogEntry<K extends CatalogKind = CatalogKind> {
  id: string;
  kind: K;
  item: CatalogItems[K];
  users: CatalogUser[];
}

export type CatalogListing = { [K in CatalogKind]: CatalogEntry<K>[] };

export interface CatalogImpact {
  machine_id: string;
  name: string;
  stale_routes: string[];
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

// --- Калибровка ---

export type CalibrationMethod = "marks" | "timed";

export interface CalibrationResult {
  flow_ml_s: number;
  prime_s: number;
  afterflow_ml: number;
  spread_pct: number | null;
  duration_s: number;
  warnings: string[];
}

export interface CalibrationRun {
  index: number;
  started_at: string;
  tank_volume_ml: number;
  marks: [number, number][];
  water_started_s: number | null;
  planned_s: number | null;
  stop_reason: string | null;
  stopped_after_s: number | null;
  volume_ml: number | null;
  result: CalibrationResult | null;
  error: string | null;
  excluded: boolean;
  completed: boolean;
}

export interface CalibrationSession {
  id: string;
  machine_id: string;
  route_id: string;
  method: CalibrationMethod;
  targets: number[];
  state: "ready" | "running" | "awaiting_volume" | "closed";
  elapsed_s: number | null;
  deadline_in_s: number | null;
  runs: CalibrationRun[];
  result: CalibrationResult | null;
  result_error: string | null;
  reference_volume_ml: number | null;
  second_level_possible: boolean;
  has_calibration: boolean;
}

// Запись журнала калибровок: прогоны и итог (data.result), или "оставлена" (method accepted).
export interface CalibrationRecord {
  id: number;
  route_id: string;
  method: string;
  created_at: string;
  data: Record<string, unknown>;
}

export interface CalibrationSettings {
  min_duration_s: number;
  max_spread_pct: number;
  overtime_factor: number;
  heartbeat_timeout_s: number;
  idle_timeout_s: number;
  tune_deviation_pct: number;
  tune_min_waterings: number;
  reminder_weeks: number | null;
  second_level_min_pct: number;
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

function issuesText(issues: ValidationIssue[]): string {
  return issues
    .map((issue) => `${issue.loc.filter((part) => part !== "body").join(".")}: ${issue.msg}`)
    .join("; ");
}

function toError(status: number, data: unknown): ApiError {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    // Ошибка домена: {"error": "NotEnoughWaterError", "detail": "..."}
    if (typeof record.error === "string") {
      const key = `errors.${record.error}`;
      const detail = Array.isArray(record.detail)
        ? issuesText(record.detail as ValidationIssue[])
        : String(record.detail ?? record.error);
      let text = hasMessage(key) ? t(key) : detail;
      // Запись справочника занята: назвать машины.
      if (Array.isArray(record.machines) && record.machines.length) {
        text += ": " + (record.machines as string[]).join(", ");
      }
      // Полив запрещён: перечислить, что именно мешает.
      if (Array.isArray(record.problems) && record.problems.length) {
        text += ": " + (record.problems as Blocker[]).map(problemText).join("; ");
      }
      return new ApiError(text, status, record.error);
    }
    // Ошибка валидации FastAPI: {"detail": [{"loc": [...], "msg": "..."}]}
    if (Array.isArray(record.detail)) {
      return new ApiError(issuesText(record.detail as ValidationIssue[]), status, "ValidationError");
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
  copyMachine: (id: string, name: string, pumpEntityId: string, valves: Record<string, string>) =>
    request<Machine>("POST", `api/machines/${id}/copy`, {
      name,
      pump_entity_id: pumpEntityId,
      valves,
    }),
  acceptCalibration: (id: string, routeId: string) =>
    request<Machine>("POST", `api/machines/${id}/routes/${routeId}/calibration/accept`),
  pulse: (entityId: string, seconds = 1) =>
    request<void>("POST", `api/ha/entities/${entityId}/pulse`, { seconds }),

  // Экспорт и импорт машин.
  exportMachines: (ids?: string[]) =>
    request<ExportBundle>(
      "GET",
      "api/export" + (ids?.length ? "?" + ids.map((id) => `machines=${encodeURIComponent(id)}`).join("&") : ""),
    ),
  previewImport: (bundle: ExportBundle) => request<ImportPlan>("POST", "api/import/preview", bundle),
  importMachines: (bundle: ExportBundle, machines: string[] | null) =>
    request<Machine[]>("POST", "api/import", { bundle, machines }),

  // Справочники.
  catalog: () => request<CatalogListing>("GET", "api/catalog"),
  catalogItem: <K extends CatalogKind>(kind: K, id: string) =>
    request<CatalogEntry<K>>("GET", `api/catalog/${kind}/${id}`),
  createItem: <K extends CatalogKind>(kind: K, item: CatalogItems[K]) =>
    request<CatalogEntry<K>>("POST", `api/catalog/${kind}`, item),
  updateItem: <K extends CatalogKind>(kind: K, id: string, item: CatalogItems[K]) =>
    request<CatalogEntry<K>>("PUT", `api/catalog/${kind}/${id}`, item),
  previewItem: <K extends CatalogKind>(kind: K, id: string, item: CatalogItems[K]) =>
    request<CatalogImpact[]>("POST", `api/catalog/${kind}/${id}/preview`, item),
  deleteItem: (kind: CatalogKind, id: string) =>
    request<void>("DELETE", `api/catalog/${kind}/${id}`),
  plan: (id: string, routeId: string, doseMl: number) =>
    request<Plan>("POST", `api/machines/${id}/plan`, { route_id: routeId, dose_ml: doseMl }),
  water: (id: string, routeId: string, doseMl: number) =>
    request<{ plan: Plan; request: QueueItem }>("POST", `api/machines/${id}/water`, {
      route_id: routeId,
      dose_ml: doseMl,
    }),
  stop: (id: string) => request<{ errors: string[] }>("POST", `api/machines/${id}/stop`),
  refill: (id: string, volumeMl: number | null) =>
    request<Machine>("POST", `api/machines/${id}/tank/refill`, { volume_ml: volumeMl }),
  setVolume: (id: string, volumeMl: number) =>
    request<Machine>("PUT", `api/machines/${id}/tank/volume`, { volume_ml: volumeMl }),

  // Расписание одного растения.
  setSchedule: (id: string, routeId: string, schedule: ScheduleConfig) =>
    request<Machine>("PUT", `api/machines/${id}/routes/${routeId}/schedule`, schedule),
  linkSchedule: (id: string, routeId: string, link: ScheduleLink) =>
    request<Machine>("PUT", `api/machines/${id}/routes/${routeId}/schedule-link`, link),
  clearSchedule: (id: string, routeId: string) =>
    request<Machine>("DELETE", `api/machines/${id}/routes/${routeId}/schedule`),
  listSchedules: () => request<Schedule[]>("GET", "api/schedules"),
  checkSchedules: () =>
    request<{ submitted: QueueItem[]; skipped: string[] }>("POST", "api/schedules/check"),

  // Очередь поливов.
  queue: () => request<QueueView>("GET", "api/queue"),
  enqueue: (machineId: string, routeId: string, doseMl: number, maxWaitMin?: number) =>
    request<QueueItem>("POST", "api/queue", {
      machine_id: machineId,
      route_id: routeId,
      dose_ml: doseMl,
      max_wait_min: maxWaitMin ?? null,
    }),
  cancelRequest: (requestId: string) => request<QueueItem>("DELETE", `api/queue/${requestId}`),

  // Проблемы.
  problems: () => request<Problem[]>("GET", "api/problems"),
  checkProblems: () => request<Problem[]>("POST", "api/problems/check"),
  ackProblem: (id: string) => request<Problem>("POST", `api/problems/${encodeURIComponent(id)}/ack`),
  muteProblem: (id: string, hours: number) =>
    request<Problem>("POST", `api/problems/${encodeURIComponent(id)}/mute`, { hours }),
  unmuteProblem: (id: string) =>
    request<Problem>("POST", `api/problems/${encodeURIComponent(id)}/unmute`),

  // Уведомления.
  notificationSettings: () => request<NotificationSettings>("GET", "api/notifications/settings"),
  saveNotificationSettings: (settings: NotificationSettings) =>
    request<NotificationSettings>("PUT", "api/notifications/settings", settings),
  pushDevices: () => request<PushDevices>("GET", "api/notifications/devices"),
  notificationTemplates: () =>
    request<NotificationTemplate[]>("GET", "api/notifications/templates"),
  previewNotification: (kind: EventKind, text: EventText) =>
    request<EventText>("POST", "api/notifications/preview", { kind, text }),
  mqttSettings: () => request<MqttSettings>("GET", "api/mqtt/settings"),
  saveMqttSettings: (settings: MqttSettingsIn) =>
    request<MqttSettings>("PUT", "api/mqtt/settings", settings),
  mqttStatus: () => request<MqttStatus>("GET", "api/mqtt/status"),
  // Калибровка насоса.
  openCalibration: (
    machineId: string,
    routeId: string,
    method: CalibrationMethod,
    marksMl: number[],
  ) =>
    request<CalibrationSession>("POST", `api/machines/${machineId}/calibration`, {
      route_id: routeId,
      method,
      marks_ml: marksMl,
    }),
  calibration: (sid: string) =>
    request<CalibrationSession>("GET", `api/calibration/sessions/${sid}`),
  calibrationHeartbeat: (sid: string) =>
    request<CalibrationSession>("POST", `api/calibration/sessions/${sid}/heartbeat`),
  calibrationStart: (sid: string) =>
    request<CalibrationSession>("POST", `api/calibration/sessions/${sid}/start`),
  calibrationRun: (sid: string, durationS: number) =>
    request<CalibrationSession>("POST", `api/calibration/sessions/${sid}/run`, {
      duration_s: durationS,
    }),
  calibrationMark: (sid: string, tS: number, volumeMl: number) =>
    request<CalibrationSession>("POST", `api/calibration/sessions/${sid}/mark`, {
      t_s: tS,
      volume_ml: volumeMl,
    }),
  calibrationStop: (sid: string) =>
    request<CalibrationSession>("POST", `api/calibration/sessions/${sid}/stop`),
  calibrationVolume: (sid: string, volumeMl: number) =>
    request<CalibrationSession>("POST", `api/calibration/sessions/${sid}/volume`, {
      volume_ml: volumeMl,
    }),
  calibrationSkipVolume: (sid: string) =>
    request<CalibrationSession>("POST", `api/calibration/sessions/${sid}/skip-volume`),
  calibrationExclude: (sid: string, index: number, excluded: boolean) =>
    request<CalibrationSession>("PUT", `api/calibration/sessions/${sid}/runs/${index}`, {
      excluded,
    }),
  calibrationSave: (sid: string, mode: "replace" | "second_level", makeBase: boolean) =>
    request<Machine>("POST", `api/calibration/sessions/${sid}/save`, {
      mode,
      make_base: makeBase,
    }),
  calibrationClose: (sid: string) =>
    request<void>("DELETE", `api/calibration/sessions/${sid}`),
  calibrationHistory: (machineId: string) =>
    request<CalibrationRecord[]>("GET", `api/machines/${machineId}/calibrations`),
  calibrationSettings: () => request<CalibrationSettings>("GET", "api/calibration/settings"),
  saveCalibrationSettings: (settings: CalibrationSettings) =>
    request<CalibrationSettings>("PUT", "api/calibration/settings", settings),
  resolveFlowSuggestion: (machineId: string, apply: boolean) =>
    request<Machine>("POST", `api/machines/${machineId}/flow-suggestion`, { apply }),

  testPush: () =>
    request<{ enabled: boolean; devices: string[] }>("POST", "api/notifications/test"),
};

export function problemText(problem: { kind: string }): string {
  const key = `problem.${problem.kind}`;
  return hasMessage(key) ? t(key) : problem.kind;
}

// Ошибка из журнала: "WateringBlockedError: watering is blocked: tank_empty" -> понятный текст.
// Для пропуска по расписанию в error лежит причина: recently_watered, too_late.
export function humanError(text: string | null): string {
  if (!text) return "";
  const reason = `reason.${text}`;
  if (hasMessage(reason)) return t(reason);
  const match = /^(\w+Error):\s*(.*)$/.exec(text);
  if (!match) return text;
  const [, name, detail] = match;
  const key = `errors.${name}`;
  if (!hasMessage(key)) return detail || name;
  if (name === "WateringBlockedError") {
    const kinds = detail.split(":").pop()!.split(",").map((kind) => kind.trim()).filter(Boolean);
    return kinds.length ? `${t(key)}: ${kinds.map((kind) => problemText({ kind })).join(", ")}` : t(key);
  }
  return t(key);
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
