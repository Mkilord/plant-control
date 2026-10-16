<script setup lang="ts">
// Машина собирает записи справочников (бак, насос, коллектор, группа питания,
// расписания), свои трубки и растения, и привязывает реле из Home Assistant.
// Новая машина заводится мастером по шагам, существующая правится одной формой.
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  api,
  errorText,
  type HaEntity,
  type HeadModel,
  type Machine,
  type MachineConfig,
  type RouteConfig,
  type RouteFlowStatus,
} from "../api";
import { findEntry, loadCatalog, entriesOf, summary } from "../catalog";
import { ml, seconds } from "../format";
import { t, type MessageKey } from "../i18n";
import AppIcon from "../components/AppIcon.vue";
import CatalogEditDialog from "../components/CatalogEditDialog.vue";
import CatalogPicker from "../components/CatalogPicker.vue";
import FormField from "../components/FormField.vue";
import FormSection from "../components/FormSection.vue";
import NumField from "../components/NumField.vue";

const props = defineProps<{ id?: string }>();
const router = useRouter();

const isNew = computed(() => !props.id);
const config = ref<MachineConfig>(defaultConfig());
const entities = ref<HaEntity[]>([]);
const entitiesError = ref("");
// Сущности, занятые другими машинами: одно реле не может служить двум машинам.
const takenEntities = ref<Map<string, string>>(new Map());
const error = ref("");
const saving = ref(false);
const loading = ref(false);
// Чем сейчас считается полив каждого маршрута (из статуса сохранённой машины).
const flows = ref<RouteFlowStatus[]>([]);
const calibrationSession = ref<string | null>(null);
const pulsing = ref("");
const pulseError = ref("");
// Правка выбранной записи справочника прямо из формы.
const editing = ref<{ kind: "tank" | "pump" | "collector" | "power"; id: string } | null>(null);
// Пикеры, в которых сейчас вводят новую запись справочника.
const drafting = ref(new Set<string>());

function onDrafting(kind: string, on: boolean) {
  const next = new Set(drafting.value);
  if (on) next.add(kind);
  else next.delete(kind);
  drafting.value = next;
}

// Созданная мастером машина: последний шаг предлагает калибровку.
const created = ref<Machine | null>(null);

function defaultRoute(id: string): RouteConfig {
  return {
    id,
    name: "",
    valve_entity_id: null,
    connection: { length_mm: 700, inner_diameter_mm: 4 },
    outlet_height_mm: 300,
    correction: 1,
    default_dose_ml: 100,
    schedule: null,
    schedule_link: null,
    calibration: null,
  };
}

function defaultConfig(): MachineConfig {
  return {
    name: "",
    tank_type: "",
    pump: { model: "", entity_id: "" },
    plumbing: { type: "direct", back_to_tank_fraction: 0.5 },
    head_model: "mid",
    flow_mode: "calibrated",
    base_route: null,
    routes: [defaultRoute("main")],
    power_group: null,
  };
}

// --- Шаги мастера ---

type Step = "general" | "collector" | "tank" | "pump" | "tubes" | "power" | "schedule";
const STEP_TITLE: Record<Step, MessageKey> = {
  general: "general.title",
  collector: "tube.supply_section",
  tank: "tank.section",
  pump: "pump.section",
  tubes: "wizard.machine.tubes",
  power: "power.title",
  schedule: "card.schedule",
};

const hasCollector = computed(() => config.value.plumbing.type === "collector");
const steps = computed<Step[]>(() =>
  ["general", "collector", "tank", "pump", "tubes", "power", "schedule"].filter(
    (step) => step !== "collector" || hasCollector.value,
  ) as Step[],
);
const stepIndex = ref(0);
const step = computed(() => steps.value[stepIndex.value]);

// В мастере виден один шаг, в форме правки - все разделы.
function shown(name: Step): boolean {
  return !isNew.value || step.value === name;
}

function stepError(name: Step): string {
  const c = config.value;
  switch (name) {
    case "general":
      return c.name.trim() ? "" : t("wizard.machine.need_name");
    case "collector":
      if (c.plumbing.type !== "collector") return "";
      if (!c.plumbing.collector_type) return t("wizard.machine.need_collector");
      if (c.routes.some((route) => !route.valve_entity_id)) return t("wizard.machine.need_valves");
      return "";
    case "tank":
      return c.tank_type ? "" : t("wizard.machine.need_tank");
    case "pump":
      if (!c.pump.model) return t("wizard.machine.need_pump");
      return c.pump.entity_id ? "" : t("wizard.machine.need_pump_entity");
    default:
      return "";
  }
}

function next() {
  const problem = stepError(step.value);
  error.value = problem;
  if (!problem) stepIndex.value = Math.min(stepIndex.value + 1, steps.value.length - 1);
}

function back() {
  error.value = "";
  stepIndex.value = Math.max(0, stepIndex.value - 1);
}

// --- Тип машины и растения ---

const machineType = computed({
  get: () => config.value.plumbing.type,
  set: (value: "direct" | "collector") => {
    if (value === "direct") {
      config.value.plumbing = { type: "direct", back_to_tank_fraction: 0.5 };
      const first = config.value.routes[0] ?? defaultRoute("main");
      config.value.routes = [{ ...first, id: "main", valve_entity_id: null }];
    } else {
      config.value.plumbing = {
        type: "collector",
        collector_type: "",
        supply: { length_mm: 500, inner_diameter_mm: 4 },
      };
      config.value.routes = config.value.routes.map((route, i) => ({
        ...route,
        id: route.id === "main" ? `v${i + 1}` : route.id,
      }));
      if (config.value.routes.length < 2) config.value.routes.push(defaultRoute(nextRouteId()));
    }
  },
});

const collectorType = computed({
  get: () => (config.value.plumbing.type === "collector" ? config.value.plumbing.collector_type || null : null),
  set: (value: string | null) => {
    if (config.value.plumbing.type === "collector") config.value.plumbing.collector_type = value ?? "";
  },
});
const outlets = computed(() => findEntry("collector", collectorType.value)?.item.outlets ?? 32);

const mainRoute = computed(() => config.value.routes[0]);

const backPercent = computed({
  get: () => {
    const plumbing = config.value.plumbing;
    return plumbing.type === "direct" ? Math.round(plumbing.back_to_tank_fraction * 100) : 0;
  },
  set: (value: number) => {
    const plumbing = config.value.plumbing;
    if (plumbing.type === "direct") plumbing.back_to_tank_fraction = Math.min(100, Math.max(0, value)) / 100;
  },
});

function nextRouteId(): string {
  const used = new Set(config.value.routes.map((r) => r.id));
  let n = 1;
  while (used.has(`v${n}`)) n++;
  return `v${n}`;
}

function addRoute() {
  config.value.routes.push(defaultRoute(nextRouteId()));
}

function removeRoute(index: number) {
  config.value.routes.splice(index, 1);
}

// --- Справочники в форме ---

const tankType = computed({
  get: () => config.value.tank_type || null,
  set: (value: string | null) => (config.value.tank_type = value ?? ""),
});
const pumpModel = computed({
  get: () => config.value.pump.model || null,
  set: (value: string | null) => (config.value.pump.model = value ?? ""),
});
const powerGroup = computed({
  get: () => config.value.power_group,
  set: (value: string | null) => (config.value.power_group = value),
});

// Расширенный режим: полив по паспорту насоса и напору вместо калибровки.
const advanced = computed({
  get: () => config.value.flow_mode === "advanced",
  set: (value: boolean) => {
    config.value.flow_mode = value ? "advanced" : "calibrated";
  },
});
const pumpHasPassport = computed(() => Boolean(findEntry("pump", config.value.pump.model)?.item.flow));

// Расписание растения: нет, из справочника или своё (настраивается на карточке).
function scheduleChoice(route: RouteConfig): string {
  if (route.schedule_link) return route.schedule_link.template;
  return route.schedule ? "own" : "";
}

function setScheduleChoice(route: RouteConfig, value: string) {
  if (value === "own") return;
  route.schedule = null;
  route.schedule_link = value ? { template: value, enabled: true } : null;
}

const schedules = computed(() => entriesOf("schedule"));

// --- Калибровка ---

function flowOf(routeId: string): RouteFlowStatus | undefined {
  return flows.value.find((item) => item.route_id === routeId);
}

function flowSummary(item: RouteFlowStatus | undefined): string {
  if (!item || item.source === "none" || !item.flow_points.length) return t("calib.status_none");
  const flowText = `${item.flow_points[0].flow_ml_s.toFixed(1)} ${t("unit.ml_s")}`;
  const extra = `${t("calib.prime")}: ${seconds(item.prime_s ?? 0)}, ${t("calib.afterflow")}: ${ml(item.afterflow_ml ?? 0)}`;
  const base =
    item.source === "inherited"
      ? t("calib.status_inherited", { route: item.inherited_from ?? "", flow: flowText })
      : t("calib.status_own", { flow: flowText });
  const copied = item.copied_from ? `; ${t("calib.copied_from", { name: item.copied_from })}` : "";
  return `${base}; ${extra}${copied}`;
}

async function acceptCalibration(routeId: string) {
  if (!props.id) return;
  error.value = "";
  try {
    const machine = await api.acceptCalibration(props.id, routeId);
    flows.value = machine.status.flows;
  } catch (e) {
    error.value = errorText(e);
  }
}

// --- Реле ---

function entityTakenBy(entityId: string | null): string {
  return entityId ? (takenEntities.value.get(entityId) ?? "") : "";
}

const freeEntities = computed(() => entities.value.filter((e) => !takenEntities.value.has(e.entity_id)));

async function pulse(entityId: string | null) {
  if (!entityId) return;
  pulseError.value = "";
  pulsing.value = entityId;
  try {
    await api.pulse(entityId, 1);
  } catch (e) {
    pulseError.value = errorText(e);
  } finally {
    pulsing.value = "";
  }
}

const headModels: HeadModel[] = ["start", "mid", "stepwise"];

// --- Загрузка и сохранение ---

onMounted(async () => {
  api
    .haEntities()
    .then((list) => (entities.value = list))
    .catch((e) => (entitiesError.value = errorText(e)));
  void loadCatalog();
  api
    .listMachines()
    .then((machines) => {
      const taken = new Map<string, string>();
      for (const machine of machines) {
        if (machine.id === props.id) continue;
        taken.set(machine.config.pump.entity_id, machine.config.name);
        for (const route of machine.config.routes) {
          if (route.valve_entity_id) taken.set(route.valve_entity_id, machine.config.name);
        }
      }
      takenEntities.value = taken;
    })
    .catch(() => undefined);
  if (props.id) {
    loading.value = true;
    try {
      const machine = await api.getMachine(props.id);
      config.value = machine.config;
      flows.value = machine.status.flows;
      calibrationSession.value = machine.status.calibration_session;
    } catch (e) {
      error.value = errorText(e);
    } finally {
      loading.value = false;
    }
  }
});

async function save() {
  if (isNew.value && stepIndex.value < steps.value.length - 1) {
    next();
    return;
  }
  for (const name of steps.value) {
    const problem = stepError(name);
    if (problem) {
      error.value = problem;
      return;
    }
  }
  error.value = "";
  saving.value = true;
  try {
    const ids = config.value.routes.map((route) => route.id);
    const payload: MachineConfig = {
      ...config.value,
      // Код базового маршрута могли переименовать или маршрут удалить.
      base_route:
        config.value.base_route && ids.includes(config.value.base_route) ? config.value.base_route : null,
    };
    if (props.id) {
      await api.updateMachine(props.id, payload);
      await router.push("/");
    } else {
      created.value = await api.createMachine(payload);
    }
  } catch (e) {
    error.value = errorText(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!props.id || !confirm(t("form.delete_confirm", { name: config.value.name }))) return;
  try {
    await api.deleteMachine(props.id);
    await router.push("/");
  } catch (e) {
    error.value = errorText(e);
  }
}

function onSavedAsNew(id: string) {
  const current = editing.value;
  if (!current) return;
  if (current.kind === "tank") tankType.value = id;
  else if (current.kind === "pump") pumpModel.value = id;
  else if (current.kind === "collector") collectorType.value = id;
  else powerGroup.value = id;
}
</script>

<template>
  <div class="page form">
    <div class="toolbar">
      <RouterLink to="/" class="button"><AppIcon name="back" />{{ t("form.back") }}</RouterLink>
      <h1>{{ isNew ? t("form.new") : config.name || t("form.machine") }}</h1>
    </div>

    <p v-if="loading" class="muted">{{ t("form.loading") }}</p>

    <!-- Машина создана: предложить калибровку. -->
    <section v-else-if="created" class="card done">
      <h2><AppIcon name="check" /> {{ t("wizard.machine.created", { name: created.config.name }) }}</h2>
      <p v-if="created.config.flow_mode === 'calibrated'">{{ t("wizard.machine.calibrate_now_hint") }}</p>
      <div class="row">
        <RouterLink
          v-if="created.config.flow_mode === 'calibrated'"
          class="button primary"
          :to="`/machines/${created.id}/calibrate`"
        >
          <AppIcon name="pump" />{{ t("wizard.machine.calibrate_now") }}
        </RouterLink>
        <RouterLink class="button" to="/">{{ t("wizard.machine.later") }}</RouterLink>
      </div>
    </section>

    <form v-else @submit.prevent="save">
      <datalist id="ha-entities">
        <option v-for="e in freeEntities" :key="e.entity_id" :value="e.entity_id">{{ e.name }}</option>
      </datalist>

      <!-- Шаги мастера -->
      <ol v-if="isNew" class="wizard-steps small">
        <li
          v-for="(name, index) in steps"
          :key="name"
          :class="{ active: index === stepIndex, done: index < stepIndex }"
        >
          <span class="num">{{ index + 1 }}</span>{{ t(STEP_TITLE[name]) }}
        </li>
      </ol>

      <!-- Общее -->
      <FormSection
        v-if="shown('general')"
        :title="t('general.title')"
        icon="info"
        accent="var(--accent-general)"
        :description="t('general.desc')"
      >
        <div class="fields">
          <FormField v-slot="{ id }" :label="t('general.name')">
            <input :id="id" v-model="config.name" required maxlength="100" :placeholder="t('general.name_placeholder')" />
          </FormField>
          <FormField v-if="!hasCollector && mainRoute" v-slot="{ id }" :label="t('general.plant')">
            <input :id="id" v-model="mainRoute.name" :placeholder="t('general.plant_placeholder')" />
          </FormField>
          <FormField v-slot="{ id }" :label="t('general.type')">
            <select :id="id" v-model="machineType">
              <option value="direct">{{ t("type.direct") }}</option>
              <option value="collector">{{ t("type.collector") }}</option>
            </select>
          </FormField>
        </div>
        <p class="note">
          <AppIcon :name="hasCollector ? 'collector' : 'tube'" />
          <span>{{ hasCollector ? t("type.collector_hint") : t("type.direct_hint") }}</span>
        </p>
      </FormSection>

      <!-- Коллектор и растения -->
      <FormSection
        v-if="hasCollector && shown('collector')"
        :title="t('tube.supply_section')"
        icon="collector"
        accent="var(--accent-plant)"
        :description="t('wizard.machine.collector_desc')"
      >
        <CatalogPicker v-model="collectorType" kind="collector" :label="t('catalog.one.collector')" @editing="onDrafting('collector', $event)" />
        <button
          v-if="collectorType"
          type="button"
          class="ghost edit-item"
          @click="editing = { kind: 'collector', id: collectorType }"
        >
          <AppIcon name="edit" />{{ t("catalog.edit") }}
        </button>

        <h3 class="sub-title">{{ t("plants.section") }}</h3>
        <p v-if="pulseError" class="error">{{ pulseError }}</p>
        <div v-for="(route, index) in config.routes" :key="index" class="route">
          <div class="route-head">
            <span class="route-number">{{ index + 1 }}</span>
            <strong>{{ route.name || t("card.no_plant") }}</strong>
            <span class="spacer" />
            <button
              v-if="config.routes.length > 2"
              type="button"
              class="icon-button"
              :title="t('plants.remove')"
              :aria-label="t('plants.remove')"
              @click="removeRoute(index)"
            >
              <AppIcon name="trash" />
            </button>
          </div>
          <div class="fields">
            <FormField v-slot="{ id }" :label="t('plants.name')">
              <input :id="id" v-model="route.name" :placeholder="t('general.plant_placeholder')" />
            </FormField>
            <FormField v-slot="{ id }" :label="t('plants.valve')">
              <span class="with-button">
                <input
                  :id="id"
                  :value="route.valve_entity_id ?? ''"
                  list="ha-entities"
                  required
                  placeholder="switch.valve_1"
                  @input="route.valve_entity_id = ($event.target as HTMLInputElement).value || null"
                />
                <button
                  type="button"
                  :disabled="!route.valve_entity_id || pulsing !== ''"
                  :title="t('wizard.machine.test_hint')"
                  @click="pulse(route.valve_entity_id)"
                >
                  {{ pulsing === route.valve_entity_id ? "..." : t("wizard.machine.test") }}
                </button>
              </span>
            </FormField>
            <FormField v-slot="{ id }" :label="t('plants.code')" :hint="t('plants.code_hint')">
              <input :id="id" v-model="route.id" required pattern="[a-z0-9_\-]{1,32}" />
            </FormField>
          </div>
          <p v-if="entityTakenBy(route.valve_entity_id)" class="error small">
            {{ t("wizard.machine.entity_taken", { machine: entityTakenBy(route.valve_entity_id) }) }}
          </p>
        </div>
        <button type="button" :disabled="config.routes.length >= outlets" @click="addRoute">
          <AppIcon name="plus" />{{ t("plants.add") }}
        </button>
        <p v-if="collectorType" class="muted small">
          {{ t("wizard.machine.outlets_used", { used: config.routes.length, total: outlets }) }}
        </p>
      </FormSection>

      <!-- Бак -->
      <FormSection
        v-if="shown('tank')"
        :title="t('tank.section')"
        icon="tank"
        accent="var(--accent-tank)"
        :description="t('tank.desc')"
      >
        <CatalogPicker v-model="tankType" kind="tank" wizard :label="t('catalog.one.tank')" @editing="onDrafting('tank', $event)" />
        <button v-if="tankType" type="button" class="ghost edit-item" @click="editing = { kind: 'tank', id: tankType }">
          <AppIcon name="edit" />{{ t("catalog.edit") }}
        </button>
      </FormSection>

      <!-- Насос -->
      <FormSection
        v-if="shown('pump')"
        :title="t('pump.section')"
        icon="pump"
        accent="var(--accent-pump)"
        :description="t('pump.desc')"
      >
        <p v-if="entitiesError" class="note warn-note">
          <AppIcon name="alert" />
          <span>{{ t("pump.entities_unavailable", { error: entitiesError }) }}</span>
        </p>
        <CatalogPicker v-model="pumpModel" kind="pump" :label="t('catalog.one.pump')" @editing="onDrafting('pump', $event)" />
        <button v-if="pumpModel" type="button" class="ghost edit-item" @click="editing = { kind: 'pump', id: pumpModel }">
          <AppIcon name="edit" />{{ t("catalog.edit") }}
        </button>
        <div class="fields sub">
          <FormField v-slot="{ id }" :label="t('pump.entity')" :hint="t('pump.entity_hint')">
            <span class="with-button">
              <input :id="id" v-model="config.pump.entity_id" list="ha-entities" required placeholder="switch.pump_1" />
              <button
                type="button"
                :disabled="!config.pump.entity_id || pulsing !== ''"
                :title="t('wizard.machine.test_pump_hint')"
                @click="pulse(config.pump.entity_id)"
              >
                {{ pulsing === config.pump.entity_id ? "..." : t("wizard.machine.test") }}
              </button>
            </span>
          </FormField>
        </div>
        <p v-if="entityTakenBy(config.pump.entity_id)" class="error small">
          {{ t("wizard.machine.entity_taken", { machine: entityTakenBy(config.pump.entity_id) }) }}
        </p>
        <p v-if="pulseError" class="error small">{{ pulseError }}</p>

        <label class="check">
          <input v-model="advanced" type="checkbox" />
          <span>{{ t("calib.advanced") }}</span>
        </label>
        <p v-if="advanced && !pumpHasPassport" class="note warn-note">
          <AppIcon name="alert" />
          <span>{{ t("wizard.machine.need_passport") }}</span>
        </p>
        <p v-else-if="!advanced" class="note">
          <AppIcon name="info" />
          <span>{{ t("calib.form_hint") }}</span>
        </p>
      </FormSection>

      <!-- Трубки -->
      <FormSection
        v-if="shown('tubes')"
        :title="t('wizard.machine.tubes')"
        icon="tube"
        accent="var(--accent-tube)"
        :description="t('wizard.machine.tubes_desc')"
      >
        <template v-if="config.plumbing.type === 'direct' && mainRoute">
          <div class="fields">
            <NumField
              v-model="mainRoute.connection.length_mm"
              :label="t('tube.length')"
              :unit="t('unit.mm')"
              :hint="t('tube.length_hint')"
              :min="0"
            />
            <NumField
              v-model="mainRoute.connection.inner_diameter_mm"
              :label="t('tube.diameter')"
              :unit="t('unit.mm')"
              :hint="t('tube.diameter_hint')"
              :min="0.1"
            />
            <template v-if="advanced">
              <NumField v-model="mainRoute.outlet_height_mm" :label="t('tube.outlet')" :unit="t('unit.mm')" :hint="t('tube.outlet_hint')" />
              <NumField v-model="backPercent" :label="t('tube.back')" :unit="t('unit.percent')" :hint="t('tube.back_hint')" :min="0" :max="100" />
              <NumField v-model="mainRoute.correction" :label="t('tube.correction')" :hint="t('tube.correction_hint')" :min="0.01" />
            </template>
          </div>
        </template>
        <template v-else-if="config.plumbing.type === 'collector'">
          <div class="fields">
            <NumField v-model="config.plumbing.supply.length_mm" :label="t('tube.supply_length')" :unit="t('unit.mm')" :min="0" />
            <NumField
              v-model="config.plumbing.supply.inner_diameter_mm"
              :label="t('tube.diameter')"
              :unit="t('unit.mm')"
              :hint="t('tube.diameter_hint')"
              :min="0.1"
            />
          </div>
          <div v-for="route in config.routes" :key="route.id" class="route">
            <div class="route-head"><AppIcon name="plant" :size="16" /><strong>{{ route.name || route.id }}</strong></div>
            <div class="fields">
              <NumField v-model="route.connection.length_mm" :label="t('tube.plant_length')" :unit="t('unit.mm')" :min="0" />
              <NumField
                v-model="route.connection.inner_diameter_mm"
                :label="t('tube.diameter')"
                :unit="t('unit.mm')"
                :hint="t('tube.diameter_hint')"
                :min="0.1"
              />
              <template v-if="advanced">
                <NumField v-model="route.outlet_height_mm" :label="t('tube.outlet')" :unit="t('unit.mm')" :hint="t('tube.outlet_hint')" />
                <NumField v-model="route.correction" :label="t('tube.correction')" :hint="t('tube.correction_hint')" :min="0.01" />
              </template>
            </div>
          </div>
        </template>
        <p v-if="!isNew && !advanced" class="note">
          <AppIcon name="info" />
          <span>{{ t("wizard.machine.tubes_stale_hint") }}</span>
        </p>
      </FormSection>

      <!-- Калибровка (только у сохранённой машины) -->
      <FormSection
        v-if="!isNew && !advanced"
        :title="t('calib.section')"
        icon="pump"
        accent="var(--accent-pump)"
        :description="t('calib.section_desc')"
      >
        <ul class="flows">
          <li v-for="route in config.routes" :key="route.id">
            <strong>{{ route.name || route.id }}</strong>
            <span class="muted small">{{ flowSummary(flowOf(route.id)) }}</span>
            <span v-if="flowOf(route.id)?.stale" class="stale">
              <span class="chip warn"><AppIcon name="alert" :size="12" /> {{ t("calib.stale") }}</span>
              <RouterLink class="button" :to="`/machines/${id}/calibrate?route=${route.id}`">{{ t("calib.recalibrate") }}</RouterLink>
              <button type="button" @click="acceptCalibration(route.id)">{{ t("calib.keep") }}</button>
            </span>
          </li>
        </ul>
        <RouterLink class="button" :to="`/machines/${id}/calibrate`">
          <AppIcon name="pump" />{{ calibrationSession ? t("calib.resume") : t("calib.open") }}
        </RouterLink>
        <FormField
          v-if="hasCollector"
          v-slot="{ id: fieldId }"
          class="base-route"
          :label="t('calib.base_route')"
          :hint="t('calib.base_route_hint')"
        >
          <select
            :id="fieldId"
            :value="config.base_route ?? ''"
            @change="config.base_route = ($event.target as HTMLSelectElement).value || null"
          >
            <option value="">{{ t("calib.base_auto") }}</option>
            <option v-for="route in config.routes" :key="route.id" :value="route.id">{{ route.name || route.id }}</option>
          </select>
        </FormField>
      </FormSection>

      <!-- Питание -->
      <FormSection
        v-if="shown('power')"
        :title="t('power.title')"
        icon="sliders"
        accent="var(--accent-extra)"
        :description="t('power.desc')"
      >
        <CatalogPicker
          v-model="powerGroup"
          kind="power"
          :label="t('power.group')"
          :hint="t('power.group_desc')"
          :none-label="t('power.none')"
          @editing="onDrafting('power', $event)"
        />
        <button v-if="powerGroup" type="button" class="ghost edit-item" @click="editing = { kind: 'power', id: powerGroup }">
          <AppIcon name="edit" />{{ t("catalog.edit") }}
        </button>
      </FormSection>

      <!-- Расписание -->
      <FormSection
        v-if="shown('schedule')"
        :title="t('card.schedule')"
        icon="clock"
        accent="var(--accent-tank)"
        :description="t('wizard.machine.schedule_desc')"
      >
        <div class="fields">
          <FormField
            v-for="route in config.routes"
            :key="route.id"
            v-slot="{ id }"
            :label="hasCollector ? route.name || route.id : t('schedule.plant')"
          >
            <select :id="id" :value="scheduleChoice(route)" @change="setScheduleChoice(route, ($event.target as HTMLSelectElement).value)">
              <option value="">{{ t("wizard.machine.no_schedule") }}</option>
              <option v-for="entry in schedules" :key="entry.id" :value="entry.id">
                {{ entry.item.name }} · {{ summary("schedule", entry.item) }}
              </option>
              <option v-if="route.schedule" value="own">{{ t("wizard.machine.own_schedule") }}</option>
            </select>
          </FormField>
        </div>
        <p class="note">
          <AppIcon name="info" />
          <span>
            {{ t("wizard.machine.schedule_hint") }}
            <RouterLink to="/catalog/schedule">{{ t("wizard.machine.schedule_catalog") }}</RouterLink>
          </span>
        </p>
        <div class="fields">
          <NumField
            v-for="route in config.routes"
            :key="`dose-${route.id}`"
            v-model="route.default_dose_ml"
            :label="t('wizard.machine.dose', { plant: route.name || route.id })"
            :hint="t('wizard.machine.dose_hint')"
            :unit="t('unit.ml')"
            :min="1"
          />
        </div>
      </FormSection>

      <!-- Дополнительно -->
      <details v-if="advanced && !isNew" class="card advanced-card">
        <summary><AppIcon name="sliders" />{{ t("advanced.title") }}</summary>
        <p class="note">
          <AppIcon name="info" />
          <span>{{ t("advanced.head_intro") }}</span>
        </p>
        <div class="fields sub">
          <FormField v-slot="{ id }" class="wide" :label="t('advanced.head')" :hint="t(`head_hint.${config.head_model}`)">
            <select :id="id" v-model="config.head_model">
              <option v-for="model in headModels" :key="model" :value="model">{{ t(`head.${model}`) }}</option>
            </select>
          </FormField>
        </div>
      </details>

      <div v-if="error" class="error">{{ error }}</div>

      <div v-if="!drafting.size" class="row buttons">
        <template v-if="isNew">
          <button v-if="stepIndex > 0" type="button" @click="back"><AppIcon name="back" />{{ t("wizard.back") }}</button>
          <button type="submit" class="primary" :disabled="saving">
            <template v-if="stepIndex < steps.length - 1">{{ t("wizard.next") }}</template>
            <template v-else><AppIcon name="check" />{{ t("form.create") }}</template>
          </button>
          <RouterLink to="/" class="button">{{ t("form.cancel") }}</RouterLink>
        </template>
        <template v-else>
          <button type="submit" class="primary" :disabled="saving"><AppIcon name="check" />{{ t("form.save") }}</button>
          <RouterLink to="/" class="button">{{ t("form.cancel") }}</RouterLink>
          <span class="spacer" />
          <button type="button" class="danger" @click="remove"><AppIcon name="trash" />{{ t("form.delete") }}</button>
        </template>
      </div>
    </form>

    <CatalogEditDialog
      v-if="editing"
      :kind="editing.kind"
      :item-id="editing.id"
      @close="editing = null"
      @saved-as-new="onSavedAsNew"
    />
  </div>
</template>

<style scoped>
.form {
  max-width: 880px;
}

.sub {
  margin-top: 14px;
}

.sub-title {
  margin: 18px 0 10px;
  font-size: 15px;
}

.warn-note {
  --accent: var(--warn);
  margin: 0 0 12px;
}

.edit-item {
  margin-top: 6px;
}

.route {
  padding: 14px;
  margin: 12px 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: color-mix(in srgb, var(--accent-plant) 4%, transparent);
}

.route-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.route-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background: var(--accent-plant);
}

.with-button {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.with-button input {
  flex: 1 1 180px;
  min-width: 0;
}

.spacer {
  flex: 1;
}

.advanced-card {
  margin-bottom: 16px;
  --accent: var(--accent-extra);
}

summary {
  cursor: pointer;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.check {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0;
  cursor: pointer;
}

.check input {
  width: auto;
  flex: none;
}

.base-route {
  margin: 12px 0;
  max-width: 420px;
}

.flows {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.flows li {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stale {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.wizard-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  list-style: none;
  margin: 0 0 16px;
  padding: 0;
  color: var(--muted);
}

.wizard-steps li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.wizard-steps .num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: 12px;
  border: 1px solid var(--border);
}

.wizard-steps li.active {
  color: var(--text);
  font-weight: 600;
}

.wizard-steps li.active .num {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--primary-text);
}

.wizard-steps li.done .num {
  background: var(--ok);
  border-color: var(--ok);
  color: #fff;
}

.done h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ok);
}

.buttons {
  margin-top: 8px;
  flex-wrap: wrap;
}
</style>
