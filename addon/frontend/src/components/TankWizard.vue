<script setup lang="ts">
// Мастер бака: ведёт по шагам и объясняет, что и где мерить.
// На выходе тип бака для справочника.
import { computed, ref } from "vue";
import type { Geometry, TankType } from "../api";
import { capacityMl, heightMm } from "../catalog";
import { ml } from "../format";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import FormField from "./FormField.vue";
import NumField from "./NumField.vue";

const emit = defineEmits<{ done: [item: TankType]; cancel: [] }>();

type Method = "shape" | "fill";
type Shape = "vertical_cylinder" | "horizontal_cylinder" | "rectangular";
type ReserveWay = "none" | "intake" | "drain";

const step = ref(1);
const method = ref<Method>("shape");
const shape = ref<Shape>("vertical_cylinder");
const diameter = ref(250);
const height = ref(300);
const length = ref(500);
const width = ref(300);
const depth = ref(200);
const fillLiters = ref(10);
const fillHeight = ref(250);
const reserveWay = ref<ReserveWay>("intake");
const intakeMm = ref(20);
const drainedMl = ref(300);
const name = ref("");

const geometry = computed<Geometry>(() => {
  if (method.value === "fill") {
    return { shape: "measured", volume_ml: Math.round(fillLiters.value * 1000), height_mm: fillHeight.value };
  }
  switch (shape.value) {
    case "vertical_cylinder":
      return { shape: "vertical_cylinder", diameter_mm: diameter.value, height_mm: height.value };
    case "horizontal_cylinder":
      return { shape: "horizontal_cylinder", diameter_mm: diameter.value, length_mm: length.value };
    case "rectangular":
      return { shape: "rectangular", width_mm: width.value, depth_mm: depth.value, height_mm: height.value };
  }
  return { shape: "measured", volume_ml: 1000, height_mm: 100 };
});

// Объём воды ниже уровня level_mm: нужен, чтобы перевести высоту заборника в мл.
function volumeAtLevel(g: Geometry, level: number): number {
  const h = Math.max(0, Math.min(level, heightMm(g)));
  switch (g.shape) {
    case "measured":
      return (g.volume_ml * h) / g.height_mm;
    case "vertical_cylinder":
      return (Math.PI * (g.diameter_mm / 2) ** 2 * h) / 1000;
    case "rectangular":
      return (g.width_mm * g.depth_mm * h) / 1000;
    case "horizontal_cylinder": {
      const r = g.diameter_mm / 2;
      const segment = r * r * Math.acos((r - h) / r) - (r - h) * Math.sqrt(Math.max(0, 2 * r * h - h * h));
      return (segment * g.length_mm) / 1000;
    }
  }
}

const capacity = computed(() => capacityMl(geometry.value));
const reserve = computed(() => {
  switch (reserveWay.value) {
    case "none":
      return 0;
    case "intake":
      return Math.round(volumeAtLevel(geometry.value, intakeMm.value));
    case "drain":
      return Math.round(drainedMl.value);
  }
  return 0;
});
const reserveTooBig = computed(() => reserve.value >= capacity.value);

const defaultName = computed(() => t("wizard.tank.default_name", { volume: ml(capacity.value) }));

function finish() {
  emit("done", {
    name: name.value.trim() || defaultName.value,
    geometry: geometry.value,
    reserve_ml: reserve.value,
  });
}

const SHAPES: { value: Shape; label: "wizard.tank.shape_bucket" | "wizard.tank.shape_barrel" | "wizard.tank.shape_box" }[] = [
  { value: "vertical_cylinder", label: "wizard.tank.shape_bucket" },
  { value: "horizontal_cylinder", label: "wizard.tank.shape_barrel" },
  { value: "rectangular", label: "wizard.tank.shape_box" },
];
</script>

<template>
  <div class="wizard">
    <ol class="steps small">
      <li :class="{ active: step === 1, done: step > 1 }">{{ t("wizard.tank.step_method") }}</li>
      <li :class="{ active: step === 2, done: step > 2 }">{{ t("wizard.tank.step_measure") }}</li>
      <li :class="{ active: step === 3, done: step > 3 }">{{ t("wizard.tank.step_reserve") }}</li>
      <li :class="{ active: step === 4 }">{{ t("wizard.tank.step_done") }}</li>
    </ol>

    <!-- 1. Как мерить -->
    <section v-if="step === 1" class="choices">
      <button type="button" class="choice" :class="{ active: method === 'shape' }" @click="method = 'shape'">
        <strong>{{ t("wizard.tank.by_shape") }}</strong>
        <span class="muted small">{{ t("wizard.tank.by_shape_hint") }}</span>
      </button>
      <button type="button" class="choice" :class="{ active: method === 'fill' }" @click="method = 'fill'">
        <strong>{{ t("wizard.tank.by_fill") }}</strong>
        <span class="muted small">{{ t("wizard.tank.by_fill_hint") }}</span>
      </button>
    </section>

    <!-- 2. Замер -->
    <section v-else-if="step === 2">
      <template v-if="method === 'shape'">
        <div class="choices three">
          <button
            v-for="item in SHAPES"
            :key="item.value"
            type="button"
            class="choice"
            :class="{ active: shape === item.value }"
            @click="shape = item.value"
          >
            <svg viewBox="0 0 60 44" class="pic" aria-hidden="true">
              <template v-if="item.value === 'vertical_cylinder'">
                <ellipse cx="30" cy="8" rx="14" ry="4" />
                <path d="M16 8v28a14 4 0 0 0 28 0V8" />
              </template>
              <template v-else-if="item.value === 'horizontal_cylinder'">
                <ellipse cx="12" cy="22" rx="5" ry="14" />
                <path d="M12 8h36a5 14 0 0 1 0 28H12" />
              </template>
              <template v-else>
                <path d="M12 12h30v26H12z M12 12l8-6h30l-8 6 M50 6v26l-8 6" />
              </template>
            </svg>
            <span>{{ t(item.label) }}</span>
          </button>
        </div>
        <p class="note">
          <AppIcon name="info" />
          <span>{{ t("wizard.tank.measure_inside") }}</span>
        </p>
        <div class="fields">
          <template v-if="shape !== 'rectangular'">
            <NumField v-model="diameter" :label="t('tank.diameter')" :unit="t('unit.mm')" :hint="t('tank.diameter_hint')" :min="1" />
          </template>
          <template v-else>
            <NumField v-model="width" :label="t('tank.width')" :unit="t('unit.mm')" :min="1" />
            <NumField v-model="depth" :label="t('tank.depth')" :unit="t('unit.mm')" :min="1" />
          </template>
          <NumField
            v-if="shape === 'horizontal_cylinder'"
            v-model="length"
            :label="t('tank.length')"
            :unit="t('unit.mm')"
            :min="1"
          />
          <NumField
            v-else
            v-model="height"
            :label="t('tank.cyl_height')"
            :unit="t('unit.mm')"
            :hint="t('tank.cyl_height_hint')"
            :min="1"
          />
        </div>
      </template>
      <template v-else>
        <ol class="howto">
          <li>{{ t("wizard.tank.fill_1") }}</li>
          <li>{{ t("wizard.tank.fill_2") }}</li>
          <li>{{ t("wizard.tank.fill_3") }}</li>
        </ol>
        <div class="fields">
          <NumField v-model="fillLiters" :label="t('tank.volume')" :unit="t('unit.l')" :hint="t('tank.volume_hint')" :min="0.01" />
          <NumField v-model="fillHeight" :label="t('tank.height')" :unit="t('unit.mm')" :hint="t('tank.height_hint')" :min="1" />
        </div>
      </template>
      <p class="muted small">{{ t("wizard.tank.capacity", { volume: ml(capacity) }) }}</p>
    </section>

    <!-- 3. Запас -->
    <section v-else-if="step === 3">
      <p class="muted">{{ t("wizard.tank.reserve_intro") }}</p>
      <div class="choices">
        <button type="button" class="choice" :class="{ active: reserveWay === 'intake' }" @click="reserveWay = 'intake'">
          <strong>{{ t("wizard.tank.reserve_intake") }}</strong>
          <span class="muted small">{{ t("wizard.tank.reserve_intake_hint") }}</span>
        </button>
        <button type="button" class="choice" :class="{ active: reserveWay === 'drain' }" @click="reserveWay = 'drain'">
          <strong>{{ t("wizard.tank.reserve_drain") }}</strong>
          <span class="muted small">{{ t("wizard.tank.reserve_drain_hint") }}</span>
        </button>
        <button type="button" class="choice" :class="{ active: reserveWay === 'none' }" @click="reserveWay = 'none'">
          <strong>{{ t("wizard.tank.reserve_none") }}</strong>
          <span class="muted small">{{ t("wizard.tank.reserve_none_hint") }}</span>
        </button>
      </div>
      <div class="fields">
        <NumField v-if="reserveWay === 'intake'" v-model="intakeMm" :label="t('wizard.tank.intake')" :unit="t('unit.mm')" :min="0" />
        <NumField v-if="reserveWay === 'drain'" v-model="drainedMl" :label="t('wizard.tank.drained')" :unit="t('unit.ml')" :min="0" />
      </div>
      <p class="muted small">{{ t("wizard.tank.reserve_result", { reserve: ml(reserve) }) }}</p>
      <p v-if="reserveTooBig" class="error">{{ t("wizard.tank.reserve_too_big") }}</p>
    </section>

    <!-- 4. Итог -->
    <section v-else>
      <FormField v-slot="{ id }" :label="t('catalog.name')">
        <input :id="id" v-model="name" maxlength="100" :placeholder="defaultName" />
      </FormField>
      <ul class="result">
        <li>{{ t("wizard.tank.sum_volume", { volume: ml(capacity) }) }}</li>
        <li>{{ t("wizard.tank.sum_per_cm", { volume: ml((capacity / heightMm(geometry)) * 10) }) }}</li>
        <li>{{ t("wizard.tank.sum_usable", { volume: ml(Math.max(0, capacity - reserve)) }) }}</li>
      </ul>
      <p v-if="geometry.shape === 'horizontal_cylinder'" class="muted small">{{ t("wizard.tank.per_cm_note") }}</p>
    </section>

    <div class="row">
      <button v-if="step > 1" type="button" @click="step--"><AppIcon name="back" />{{ t("wizard.back") }}</button>
      <button type="button" class="ghost" @click="emit('cancel')">{{ t("form.cancel") }}</button>
      <span class="spacer" />
      <button v-if="step < 4" type="button" class="primary" :disabled="step === 3 && reserveTooBig" @click="step++">
        {{ t("wizard.next") }}
      </button>
      <button v-else type="button" class="primary" @click="finish">
        <AppIcon name="check" />{{ t("wizard.tank.save") }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.wizard {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.steps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  list-style: none;
  margin: 0;
  padding: 0;
  color: var(--muted);
}

.steps li.active {
  color: var(--text);
  font-weight: 600;
}

.steps li.done {
  color: var(--ok);
}

.choices {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  margin-bottom: 12px;
}

.choices.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.choice {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px;
  text-align: left;
  border-radius: 10px;
  white-space: normal;
}

.choices.three .choice {
  align-items: center;
  text-align: center;
}

.choice.active {
  border-color: var(--accent-tank);
  box-shadow: 0 0 0 1px var(--accent-tank);
}

.pic {
  width: 60px;
  height: 44px;
  fill: none;
  stroke: var(--accent-tank);
  stroke-width: 2;
}

.howto {
  margin: 0 0 12px;
  padding-left: 20px;
}

.result {
  margin: 12px 0 0;
  padding-left: 20px;
}

.spacer {
  flex: 1;
}
</style>
