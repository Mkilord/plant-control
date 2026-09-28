<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  api,
  errorText,
  type Flow,
  type HaEntity,
  type HeadModel,
  type MachineConfig,
  type RouteConfig,
} from "../api";
import AppIcon from "../components/AppIcon.vue";
import FormField from "../components/FormField.vue";
import FormSection from "../components/FormSection.vue";
import NumField from "../components/NumField.vue";
import { t } from "../i18n";

const props = defineProps<{ id?: string }>();
const router = useRouter();

const isNew = computed(() => !props.id);
const config = ref<MachineConfig>(defaultConfig());
const entities = ref<HaEntity[]>([]);
const entitiesError = ref("");
const error = ref("");
const saving = ref(false);
const loading = ref(false);
// Точки табличной модели насоса в текстовом виде: "высота расход" по строке.
const tablePoints = ref("0 20\n400 12\n800 0");

function defaultRoute(id: string): RouteConfig {
  return {
    id,
    name: "",
    valve_entity_id: null,
    connection: { length_mm: 700, inner_diameter_mm: 4 },
    outlet_height_mm: 300,
    correction: 1,
  };
}

function defaultConfig(): MachineConfig {
  return {
    name: "",
    tank: {
      geometry: { shape: "measured", volume_ml: 2000, height_mm: 150 },
      reserve_ml: 500,
    },
    pump: {
      entity_id: "",
      flow: { model: "constant", flow_ml_s: 10 },
      max_runtime_s: 60,
      cooldown_s: 10,
    },
    plumbing: { type: "direct", back_to_tank_fraction: 0.5 },
    head_model: "mid",
    routes: [defaultRoute("main")],
    timings: { valve_lead_s: 0.5, valve_lag_s: 0.5 },
  };
}

// --- Бак ---
// В API форма и ориентация - одно поле shape. В интерфейсе они разделены:
// способ задания (по замеру или по форме), форма, ориентация (только для цилиндра).

type TankMode = "measured" | "shape";
type TankShape = "cylinder" | "rectangular";
type Orientation = "vertical" | "horizontal";

const tankMode = computed<TankMode>({
  get: () => (config.value.tank.geometry.shape === "measured" ? "measured" : "shape"),
  set: (mode) => {
    config.value.tank.geometry =
      mode === "measured"
        ? { shape: "measured", volume_ml: 2000, height_mm: 150 }
        : { shape: "vertical_cylinder", diameter_mm: 130, height_mm: 150 };
  },
});

const tankShape = computed<TankShape>({
  get: () => (config.value.tank.geometry.shape === "rectangular" ? "rectangular" : "cylinder"),
  set: (shape) => {
    config.value.tank.geometry =
      shape === "rectangular"
        ? { shape: "rectangular", width_mm: 150, depth_mm: 100, height_mm: 150 }
        : { shape: "vertical_cylinder", diameter_mm: 130, height_mm: 150 };
  },
});

const orientation = computed<Orientation>({
  get: () =>
    config.value.tank.geometry.shape === "horizontal_cylinder" ? "horizontal" : "vertical",
  set: (value) => {
    const geometry = config.value.tank.geometry;
    const diameter = "diameter_mm" in geometry ? geometry.diameter_mm : 130;
    config.value.tank.geometry =
      value === "horizontal"
        ? { shape: "horizontal_cylinder", diameter_mm: diameter, length_mm: 300 }
        : { shape: "vertical_cylinder", diameter_mm: diameter, height_mm: 150 };
  },
});

// Объём бака вводится в литрах, хранится в мл.
const tankVolumeL = computed({
  get: () => {
    const geometry = config.value.tank.geometry;
    return geometry.shape === "measured" ? geometry.volume_ml / 1000 : 0;
  },
  set: (liters: number) => {
    const geometry = config.value.tank.geometry;
    if (geometry.shape === "measured") geometry.volume_ml = Math.round(liters * 1000);
  },
});

// --- Насос ---

const flowModel = computed({
  get: () => config.value.pump.flow.model,
  set: (value: Flow["model"]) => {
    const defaults: Record<Flow["model"], Flow> = {
      constant: { model: "constant", flow_ml_s: 10 },
      linear: { model: "linear", max_flow_ml_s: 240 / 3.6, max_head_mm: 1000 },
      table: { model: "table", points: parsePoints(tablePoints.value) },
    };
    config.value.pump.flow = defaults[value];
  },
});

// Производители пишут расход в л/ч и высоту в метрах. Внутри мл/с и мм.
const qmaxLh = computed({
  get: () => {
    const flow = config.value.pump.flow;
    return flow.model === "linear" ? round(flow.max_flow_ml_s * 3.6, 2) : 0;
  },
  set: (value: number) => {
    const flow = config.value.pump.flow;
    if (flow.model === "linear") flow.max_flow_ml_s = value / 3.6;
  },
});

const hmaxM = computed({
  get: () => {
    const flow = config.value.pump.flow;
    return flow.model === "linear" ? round(flow.max_head_mm / 1000, 3) : 0;
  },
  set: (value: number) => {
    const flow = config.value.pump.flow;
    if (flow.model === "linear") flow.max_head_mm = value * 1000;
  },
});

function round(value: number, digits: number): number {
  const k = 10 ** digits;
  return Math.round(value * k) / k;
}

function parsePoints(text: string): [number, number][] {
  return text
    .split("\n")
    .map((line) => line.trim().split(/[\s;,]+/).map(Number))
    .filter((pair) => pair.length === 2 && pair.every((n) => Number.isFinite(n)))
    .map(([head, flow]) => [head, flow] as [number, number]);
}

watch(tablePoints, (text) => {
  if (config.value.pump.flow.model === "table") {
    config.value.pump.flow.points = parsePoints(text);
  }
});

// --- Тип и трубки ---

const hasCollector = computed(() => config.value.plumbing.type === "collector");

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

// Единственный маршрут машины без коллектора.
const mainRoute = computed(() => config.value.routes[0]);

const backPercent = computed({
  get: () => {
    const plumbing = config.value.plumbing;
    return plumbing.type === "direct" ? Math.round(plumbing.back_to_tank_fraction * 100) : 0;
  },
  set: (value: number) => {
    const plumbing = config.value.plumbing;
    if (plumbing.type === "direct") {
      plumbing.back_to_tank_fraction = Math.min(100, Math.max(0, value)) / 100;
    }
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

const headModels: HeadModel[] = ["start", "mid", "stepwise"];

// --- Загрузка и сохранение ---

onMounted(async () => {
  api
    .haEntities()
    .then((list) => (entities.value = list))
    .catch((e) => (entitiesError.value = errorText(e)));
  if (props.id) {
    loading.value = true;
    try {
      const machine = await api.getMachine(props.id);
      config.value = machine.config;
      if (machine.config.pump.flow.model === "table") {
        tablePoints.value = machine.config.pump.flow.points.map((p) => p.join(" ")).join("\n");
      }
    } catch (e) {
      error.value = errorText(e);
    } finally {
      loading.value = false;
    }
  }
});

async function save() {
  error.value = "";
  saving.value = true;
  try {
    if (props.id) {
      await api.updateMachine(props.id, config.value);
    } else {
      await api.createMachine(config.value);
    }
    await router.push("/");
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
</script>

<template>
  <div class="page form">
    <div class="toolbar">
      <RouterLink to="/" class="button"><AppIcon name="back" />{{ t("form.back") }}</RouterLink>
      <h1>{{ isNew ? t("form.new") : config.name || t("form.machine") }}</h1>
    </div>

    <p v-if="loading" class="muted">{{ t("form.loading") }}</p>

    <form v-else @submit.prevent="save">
      <datalist id="ha-entities">
        <option v-for="e in entities" :key="e.entity_id" :value="e.entity_id">{{ e.name }}</option>
      </datalist>

      <!-- Общее -->
      <FormSection
        :title="t('general.title')"
        icon="info"
        accent="var(--accent-general)"
        :description="t('general.desc')"
      >
        <div class="fields">
          <FormField v-slot="{ id }" :label="t('general.name')">
            <input
              :id="id"
              v-model="config.name"
              required
              maxlength="100"
              :placeholder="t('general.name_placeholder')"
            />
          </FormField>
          <FormField v-if="!hasCollector && mainRoute" v-slot="{ id }" :label="t('general.plant')">
            <input
              :id="id"
              v-model="mainRoute.name"
              :placeholder="t('general.plant_placeholder')"
            />
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

      <!-- Бак -->
      <FormSection
        :title="t('tank.section')"
        icon="tank"
        accent="var(--accent-tank)"
        :description="t('tank.desc')"
      >
        <div class="fields">
          <FormField v-slot="{ id }" class="wide" :label="t('tank.mode')">
            <select :id="id" v-model="tankMode">
              <option value="measured">{{ t("tank.mode.measured") }}</option>
              <option value="shape">{{ t("tank.mode.shape") }}</option>
            </select>
          </FormField>
          <template v-if="tankMode === 'shape'">
            <FormField v-slot="{ id }" :label="t('tank.shape')">
              <select :id="id" v-model="tankShape">
                <option value="cylinder">{{ t("tank.shape.cylinder") }}</option>
                <option value="rectangular">{{ t("tank.shape.rectangular") }}</option>
              </select>
            </FormField>
            <FormField v-if="tankShape === 'cylinder'" v-slot="{ id }" :label="t('tank.orientation')">
              <select :id="id" v-model="orientation">
                <option value="vertical">{{ t("tank.orientation.vertical") }}</option>
                <option value="horizontal">{{ t("tank.orientation.horizontal") }}</option>
              </select>
            </FormField>
          </template>
        </div>
        <p class="note">
          <AppIcon name="info" />
          <span>
            {{ tankMode === "measured" ? t("tank.mode_hint_measured") : t("tank.mode_hint_shape") }}
          </span>
        </p>

        <div class="fields sub">
          <template v-if="config.tank.geometry.shape === 'measured'">
            <NumField
              v-model="tankVolumeL"
              :label="t('tank.volume')"
              :unit="t('unit.l')"
              :hint="t('tank.volume_hint')"
              :min="0.01"
            />
            <NumField
              v-model="config.tank.geometry.height_mm"
              :label="t('tank.height')"
              :unit="t('unit.mm')"
              :hint="t('tank.height_hint')"
              :min="1"
            />
          </template>
          <template v-else-if="config.tank.geometry.shape === 'vertical_cylinder'">
            <NumField
              v-model="config.tank.geometry.diameter_mm"
              :label="t('tank.diameter')"
              :unit="t('unit.mm')"
              :hint="t('tank.diameter_hint')"
              :min="1"
            />
            <NumField
              v-model="config.tank.geometry.height_mm"
              :label="t('tank.cyl_height')"
              :unit="t('unit.mm')"
              :hint="t('tank.cyl_height_hint')"
              :min="1"
            />
          </template>
          <template v-else-if="config.tank.geometry.shape === 'horizontal_cylinder'">
            <NumField
              v-model="config.tank.geometry.diameter_mm"
              :label="t('tank.diameter')"
              :unit="t('unit.mm')"
              :hint="t('tank.diameter_hint')"
              :min="1"
            />
            <NumField
              v-model="config.tank.geometry.length_mm"
              :label="t('tank.length')"
              :unit="t('unit.mm')"
              :min="1"
            />
          </template>
          <template v-else-if="config.tank.geometry.shape === 'rectangular'">
            <NumField
              v-model="config.tank.geometry.width_mm"
              :label="t('tank.width')"
              :unit="t('unit.mm')"
              :min="1"
            />
            <NumField
              v-model="config.tank.geometry.depth_mm"
              :label="t('tank.depth')"
              :unit="t('unit.mm')"
              :min="1"
            />
            <NumField
              v-model="config.tank.geometry.height_mm"
              :label="t('tank.rect_height')"
              :unit="t('unit.mm')"
              :hint="t('tank.cyl_height_hint')"
              :min="1"
            />
          </template>
          <NumField
            v-model="config.tank.reserve_ml"
            :label="t('tank.reserve')"
            :unit="t('unit.ml')"
            :hint="t('tank.reserve_hint')"
            :min="0"
          />
        </div>
      </FormSection>

      <!-- Насос -->
      <FormSection
        :title="t('pump.section')"
        icon="pump"
        accent="var(--accent-pump)"
        :description="t('pump.desc')"
      >
        <p v-if="entitiesError" class="note warn-note">
          <AppIcon name="alert" />
          <span>{{ t("pump.entities_unavailable", { error: entitiesError }) }}</span>
        </p>
        <div class="fields">
          <FormField v-slot="{ id }" :label="t('pump.entity')" :hint="t('pump.entity_hint')">
            <input
              :id="id"
              v-model="config.pump.entity_id"
              list="ha-entities"
              required
              placeholder="switch.pump_1"
            />
          </FormField>
          <FormField v-slot="{ id }" class="wide" :label="t('pump.model')">
            <select :id="id" v-model="flowModel">
              <option value="constant">{{ t("pump.model.constant") }}</option>
              <option value="linear">{{ t("pump.model.linear") }}</option>
              <option value="table">{{ t("pump.model.table") }}</option>
            </select>
          </FormField>
        </div>
        <p class="note">
          <AppIcon name="info" />
          <span>{{ t(`pump.model_hint.${config.pump.flow.model}`) }}</span>
        </p>

        <div class="fields sub">
          <template v-if="config.pump.flow.model === 'constant'">
            <NumField
              v-model="config.pump.flow.flow_ml_s"
              :label="t('pump.flow')"
              :unit="t('unit.ml_s')"
              :hint="t('pump.flow_hint')"
              :min="0.01"
            />
          </template>
          <template v-else-if="config.pump.flow.model === 'linear'">
            <NumField
              v-model="qmaxLh"
              :label="t('pump.qmax')"
              :unit="t('unit.l_h')"
              :hint="t('pump.qmax_hint')"
              :min="0.01"
            />
            <NumField
              v-model="hmaxM"
              :label="t('pump.hmax')"
              :unit="t('unit.m')"
              :hint="t('pump.hmax_hint')"
              :min="0.001"
            />
          </template>
          <NumField
            v-model="config.pump.max_runtime_s"
            :label="t('pump.max_runtime')"
            :unit="t('unit.s')"
            :hint="t('pump.max_runtime_hint')"
            :min="1"
          />
          <NumField
            v-model="config.pump.cooldown_s"
            :label="t('pump.cooldown')"
            :unit="t('unit.s')"
            :hint="t('pump.cooldown_hint')"
            :min="0"
          />
        </div>
        <FormField
          v-if="config.pump.flow.model === 'table'"
          v-slot="{ id }"
          class="sub"
          :label="t('pump.points')"
        >
          <textarea :id="id" v-model="tablePoints" rows="4" />
        </FormField>
      </FormSection>

      <!-- Трубка: без коллектора -->
      <FormSection
        v-if="config.plumbing.type === 'direct' && mainRoute"
        :title="t('tube.section')"
        icon="tube"
        accent="var(--accent-tube)"
        :description="t('tube.desc')"
      >
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
          <NumField
            v-model="mainRoute.outlet_height_mm"
            :label="t('tube.outlet')"
            :unit="t('unit.mm')"
            :hint="t('tube.outlet_hint')"
          />
          <NumField
            v-model="backPercent"
            :label="t('tube.back')"
            :unit="t('unit.percent')"
            :hint="t('tube.back_hint')"
            :min="0"
            :max="100"
          />
          <NumField
            v-model="mainRoute.correction"
            :label="t('tube.correction')"
            :hint="t('tube.correction_hint')"
            :min="0.01"
          />
        </div>
      </FormSection>

      <!-- Коллектор -->
      <template v-else-if="config.plumbing.type === 'collector'">
        <FormSection
          :title="t('tube.supply_section')"
          icon="collector"
          accent="var(--accent-tube)"
          :description="t('collector.desc')"
        >
          <div class="fields">
            <NumField
              v-model="config.plumbing.supply.length_mm"
              :label="t('tube.supply_length')"
              :unit="t('unit.mm')"
              :min="0"
            />
            <NumField
              v-model="config.plumbing.supply.inner_diameter_mm"
              :label="t('tube.diameter')"
              :unit="t('unit.mm')"
              :hint="t('tube.diameter_hint')"
              :min="0.1"
            />
            <NumField
              v-model="config.timings.valve_lead_s"
              :label="t('tube.lead')"
              :unit="t('unit.s')"
              :hint="t('tube.lead_hint')"
              :min="0"
            />
            <NumField
              v-model="config.timings.valve_lag_s"
              :label="t('tube.lag')"
              :unit="t('unit.s')"
              :hint="t('tube.lag_hint')"
              :min="0"
            />
          </div>
        </FormSection>

        <FormSection
          :title="t('plants.section')"
          icon="plant"
          accent="var(--accent-plant)"
          :description="t('plants.desc')"
        >
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
                <input
                  :id="id"
                  v-model="route.name"
                  :placeholder="t('general.plant_placeholder')"
                />
              </FormField>
              <FormField v-slot="{ id }" :label="t('plants.code')" :hint="t('plants.code_hint')">
                <input :id="id" v-model="route.id" required pattern="[a-z0-9_\-]{1,32}" />
              </FormField>
              <FormField v-slot="{ id }" :label="t('plants.valve')">
                <input
                  :id="id"
                  :value="route.valve_entity_id ?? ''"
                  list="ha-entities"
                  required
                  placeholder="switch.valve_1"
                  @input="route.valve_entity_id = ($event.target as HTMLInputElement).value || null"
                />
              </FormField>
              <NumField
                v-model="route.connection.length_mm"
                :label="t('tube.plant_length')"
                :unit="t('unit.mm')"
                :min="0"
              />
              <NumField
                v-model="route.connection.inner_diameter_mm"
                :label="t('tube.diameter')"
                :unit="t('unit.mm')"
                :hint="t('tube.diameter_hint')"
                :min="0.1"
              />
              <NumField
                v-model="route.outlet_height_mm"
                :label="t('tube.outlet')"
                :unit="t('unit.mm')"
                :hint="t('tube.outlet_hint')"
              />
              <NumField
                v-model="route.correction"
                :label="t('tube.correction')"
                :hint="t('tube.correction_hint')"
                :min="0.01"
              />
            </div>
          </div>
          <button type="button" @click="addRoute"><AppIcon name="plus" />{{ t("plants.add") }}</button>
        </FormSection>
      </template>

      <!-- Дополнительно -->
      <details class="card advanced-card">
        <summary><AppIcon name="sliders" />{{ t("advanced.title") }}</summary>
        <p class="note">
          <AppIcon name="info" />
          <span>{{ t("advanced.head_intro") }}</span>
        </p>
        <div class="fields sub">
          <FormField
            v-slot="{ id }"
            class="wide"
            :label="t('advanced.head')"
            :hint="t(`head_hint.${config.head_model}`)"
          >
            <select :id="id" v-model="config.head_model">
              <option v-for="model in headModels" :key="model" :value="model">
                {{ t(`head.${model}`) }}
              </option>
            </select>
          </FormField>
        </div>
      </details>

      <div v-if="error" class="error">{{ error }}</div>

      <div class="row buttons">
        <button type="submit" class="primary" :disabled="saving">
          <AppIcon name="check" />{{ isNew ? t("form.create") : t("form.save") }}
        </button>
        <RouterLink to="/" class="button">{{ t("form.cancel") }}</RouterLink>
        <span class="spacer" />
        <button v-if="!isNew" type="button" class="danger" @click="remove">
          <AppIcon name="trash" />{{ t("form.delete") }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.form {
  max-width: 880px;
}

.sub {
  margin-top: 14px;
}

.warn-note {
  --accent: var(--warn);
  margin: 0 0 12px;
}

.route {
  padding: 14px;
  margin-bottom: 12px;
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

.buttons {
  margin-top: 8px;
}

.buttons .spacer {
  flex: 1;
}
</style>
