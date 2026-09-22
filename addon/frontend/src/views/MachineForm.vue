<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  api,
  errorText,
  type Flow,
  type Geometry,
  type HaEntity,
  type MachineConfig,
  type RouteConfig,
} from "../api";

const props = defineProps<{ id?: string }>();
const router = useRouter();

const isNew = computed(() => !props.id);
const config = ref<MachineConfig>(defaultConfig());
const entities = ref<HaEntity[]>([]);
const entitiesError = ref("");
const error = ref("");
const saving = ref(false);
const loading = ref(false);
// Точки табличной модели насоса в текстовом виде: "напор расход" по строке.
const tablePoints = ref("0 20\n400 12\n800 0");

function defaultRoute(id: string): RouteConfig {
  return {
    id,
    name: "",
    valve_entity_id: null,
    connection: { length_mm: 700, inner_radius_mm: 2 },
    outlet_height_mm: 300,
    correction: 1,
  };
}

function defaultConfig(): MachineConfig {
  return {
    name: "",
    tank: {
      geometry: { shape: "vertical_cylinder", diameter_mm: 130, height_mm: 151 },
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

// --- Переключение вариантов: при смене типа подставляем поля по умолчанию ---

const shape = computed({
  get: () => config.value.tank.geometry.shape,
  set: (value: Geometry["shape"]) => {
    const defaults: Record<Geometry["shape"], Geometry> = {
      vertical_cylinder: { shape: "vertical_cylinder", diameter_mm: 130, height_mm: 151 },
      horizontal_cylinder: { shape: "horizontal_cylinder", diameter_mm: 200, length_mm: 300 },
      rectangular: { shape: "rectangular", width_mm: 150, depth_mm: 100, height_mm: 150 },
    };
    config.value.tank.geometry = defaults[value];
  },
});

const flowModel = computed({
  get: () => config.value.pump.flow.model,
  set: (value: Flow["model"]) => {
    const defaults: Record<Flow["model"], Flow> = {
      constant: { model: "constant", flow_ml_s: 10 },
      linear: { model: "linear", max_flow_ml_s: 20, max_head_mm: 800 },
      table: { model: "table", points: parsePoints(tablePoints.value) },
    };
    config.value.pump.flow = defaults[value];
  },
});

const hasCollector = computed(() => config.value.plumbing.type === "collector");

const plumbingType = computed({
  get: () => config.value.plumbing.type,
  set: (value: "direct" | "collector") => {
    if (value === "direct") {
      config.value.plumbing = { type: "direct", back_to_tank_fraction: 0.5 };
      const first = config.value.routes[0] ?? defaultRoute("main");
      config.value.routes = [{ ...first, valve_entity_id: null }];
    } else {
      config.value.plumbing = {
        type: "collector",
        supply: { length_mm: 500, inner_radius_mm: 2 },
      };
      config.value.routes = config.value.routes.map((route, i) => ({
        ...route,
        id: route.id === "main" ? `v${i + 1}` : route.id,
      }));
      if (config.value.routes.length < 2) config.value.routes.push(defaultRoute(nextRouteId()));
    }
  },
});

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
  if (!props.id || !confirm(`Удалить поливалку «${config.value.name}»?`)) return;
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
      <RouterLink to="/" class="button">Назад</RouterLink>
      <h1>{{ isNew ? "Новая поливалка" : config.name || "Поливалка" }}</h1>
    </div>

    <p v-if="loading" class="muted">Загрузка...</p>

    <form v-else @submit.prevent="save">
      <datalist id="ha-entities">
        <option v-for="e in entities" :key="e.entity_id" :value="e.entity_id">{{ e.name }}</option>
      </datalist>

      <fieldset>
        <legend>Общее</legend>
        <div class="fields">
          <label class="field">
            <span>Название</span>
            <input v-model="config.name" required maxlength="100" placeholder="Фикус" />
          </label>
          <label class="field">
            <span>Схема</span>
            <select v-model="plumbingType">
              <option value="direct">Без коллектора: насос сразу к растению</option>
              <option value="collector">С коллектором: несколько растений</option>
            </select>
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Бак</legend>
        <div class="fields">
          <label class="field">
            <span>Форма</span>
            <select v-model="shape">
              <option value="vertical_cylinder">Цилиндр стоя</option>
              <option value="horizontal_cylinder">Цилиндр лёжа</option>
              <option value="rectangular">Прямоугольный</option>
            </select>
          </label>
          <template v-if="config.tank.geometry.shape === 'vertical_cylinder'">
            <label class="field">
              <span>Диаметр, мм</span>
              <input v-model.number="config.tank.geometry.diameter_mm" type="number" min="1" />
            </label>
            <label class="field">
              <span>Высота, мм</span>
              <input v-model.number="config.tank.geometry.height_mm" type="number" min="1" />
            </label>
          </template>
          <template v-else-if="config.tank.geometry.shape === 'horizontal_cylinder'">
            <label class="field">
              <span>Диаметр, мм</span>
              <input v-model.number="config.tank.geometry.diameter_mm" type="number" min="1" />
            </label>
            <label class="field">
              <span>Длина, мм</span>
              <input v-model.number="config.tank.geometry.length_mm" type="number" min="1" />
            </label>
          </template>
          <template v-else>
            <label class="field">
              <span>Ширина, мм</span>
              <input v-model.number="config.tank.geometry.width_mm" type="number" min="1" />
            </label>
            <label class="field">
              <span>Глубина, мм</span>
              <input v-model.number="config.tank.geometry.depth_mm" type="number" min="1" />
            </label>
            <label class="field">
              <span>Высота, мм</span>
              <input v-model.number="config.tank.geometry.height_mm" type="number" min="1" />
            </label>
          </template>
          <label class="field">
            <span>Запас под насосом, мл</span>
            <input v-model.number="config.tank.reserve_ml" type="number" min="0" step="50" />
            <span class="hint">Вода ниже забора погружного насоса, ей не поливают</span>
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Насос</legend>
        <p v-if="entitiesError" class="hint">
          Список реле из Home Assistant недоступен ({{ entitiesError }}), введите id вручную.
        </p>
        <div class="fields">
          <label class="field">
            <span>Реле в Home Assistant</span>
            <input
              v-model="config.pump.entity_id"
              list="ha-entities"
              required
              placeholder="switch.pump_1"
            />
          </label>
          <label class="field">
            <span>Модель расхода</span>
            <select v-model="flowModel">
              <option value="constant">Постоянный расход</option>
              <option value="linear">Линейная по паспорту</option>
              <option value="table">По точкам</option>
            </select>
          </label>
          <template v-if="config.pump.flow.model === 'constant'">
            <label class="field">
              <span>Расход, мл/с</span>
              <input
                v-model.number="config.pump.flow.flow_ml_s"
                type="number"
                min="0.01"
                step="0.1"
              />
              <span class="hint">Замер: сколько мл насос наливает за секунду</span>
            </label>
          </template>
          <template v-else-if="config.pump.flow.model === 'linear'">
            <label class="field">
              <span>Максимальный расход, мл/с</span>
              <input
                v-model.number="config.pump.flow.max_flow_ml_s"
                type="number"
                min="0.01"
                step="0.1"
              />
            </label>
            <label class="field">
              <span>Максимальный напор, мм</span>
              <input v-model.number="config.pump.flow.max_head_mm" type="number" min="1" />
            </label>
          </template>
          <label class="field">
            <span>Предел работы за раз, с</span>
            <input v-model.number="config.pump.max_runtime_s" type="number" min="1" />
          </label>
          <label class="field">
            <span>Остывание между поливами, с</span>
            <input v-model.number="config.pump.cooldown_s" type="number" min="0" />
          </label>
        </div>
        <label v-if="config.pump.flow.model === 'table'" class="field points">
          <span>Точки: напор мм и расход мл/с, по строке</span>
          <textarea v-model="tablePoints" rows="4" />
        </label>
      </fieldset>

      <fieldset v-if="config.plumbing.type === 'direct'">
        <legend>Трубка</legend>
        <div class="fields">
          <label class="field">
            <span>Стекает обратно в бак: {{ Math.round(config.plumbing.back_to_tank_fraction * 100) }}%</span>
            <input
              v-model.number="config.plumbing.back_to_tank_fraction"
              type="range"
              min="0"
              max="1"
              step="0.05"
            />
            <span class="hint">Какая часть воды из трубки уходит в бак после выключения насоса</span>
          </label>
        </div>
      </fieldset>

      <fieldset v-else>
        <legend>Коллектор</legend>
        <div class="fields">
          <label class="field">
            <span>Трубка бак-коллектор: длина, мм</span>
            <input v-model.number="config.plumbing.supply.length_mm" type="number" min="0" />
          </label>
          <label class="field">
            <span>Внутренний радиус, мм</span>
            <input
              v-model.number="config.plumbing.supply.inner_radius_mm"
              type="number"
              min="0.1"
              step="0.1"
            />
          </label>
          <label class="field">
            <span>Пауза клапан-насос, с</span>
            <input
              v-model.number="config.timings.valve_lead_s"
              type="number"
              min="0"
              step="0.1"
            />
          </label>
          <label class="field">
            <span>Пауза насос-клапан, с</span>
            <input
              v-model.number="config.timings.valve_lag_s"
              type="number"
              min="0"
              step="0.1"
            />
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>{{ hasCollector ? "Растения" : "Растение" }}</legend>
        <div v-for="(route, index) in config.routes" :key="index" class="route">
          <div class="fields">
            <label class="field">
              <span>Название</span>
              <input v-model="route.name" placeholder="Фикус" />
            </label>
            <label v-if="hasCollector" class="field">
              <span>Код</span>
              <input v-model="route.id" required pattern="[a-z0-9_\-]{1,32}" />
            </label>
            <label v-if="hasCollector" class="field">
              <span>Реле клапана</span>
              <input
                :value="route.valve_entity_id ?? ''"
                list="ha-entities"
                required
                placeholder="switch.valve_1"
                @input="route.valve_entity_id = ($event.target as HTMLInputElement).value || null"
              />
            </label>
            <label class="field">
              <span>Трубка до растения: длина, мм</span>
              <input v-model.number="route.connection.length_mm" type="number" min="0" />
            </label>
            <label class="field">
              <span>Внутренний радиус, мм</span>
              <input
                v-model.number="route.connection.inner_radius_mm"
                type="number"
                min="0.1"
                step="0.1"
              />
            </label>
            <label class="field">
              <span>Высота выхода над дном бака, мм</span>
              <input v-model.number="route.outlet_height_mm" type="number" />
            </label>
            <label class="field">
              <span>Поправка расхода</span>
              <input v-model.number="route.correction" type="number" min="0.01" step="0.01" />
              <span class="hint">1 - без поправки, подбирается по замеру</span>
            </label>
          </div>
          <button
            v-if="hasCollector && config.routes.length > 2"
            type="button"
            class="danger"
            @click="removeRoute(index)"
          >
            Убрать
          </button>
        </div>
        <button v-if="hasCollector" type="button" @click="addRoute">Добавить растение</button>
      </fieldset>

      <details class="card">
        <summary>Дополнительно</summary>
        <div class="fields advanced">
          <label class="field">
            <span>Напор во время полива</span>
            <select v-model="config.head_model">
              <option value="start">По уровню в начале</option>
              <option value="mid">По уровню на середине дозы</option>
              <option value="stepwise">Пошагово</option>
            </select>
          </label>
        </div>
      </details>

      <div v-if="error" class="error">{{ error }}</div>

      <div class="row buttons">
        <button type="submit" class="primary" :disabled="saving">
          {{ isNew ? "Создать" : "Сохранить" }}
        </button>
        <RouterLink to="/" class="button">Отмена</RouterLink>
        <span class="spacer" />
        <button v-if="!isNew" type="button" class="danger" @click="remove">Удалить</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.form {
  max-width: 820px;
}

.route {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.route .fields {
  width: 100%;
}

.points {
  margin-top: 12px;
}

.advanced {
  margin-top: 12px;
}

details {
  margin-bottom: 16px;
}

summary {
  cursor: pointer;
  font-weight: 600;
}

.buttons {
  margin-top: 8px;
}

.buttons .spacer {
  flex: 1;
}
</style>
