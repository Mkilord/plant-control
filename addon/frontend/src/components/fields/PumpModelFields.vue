<script setup lang="ts">
// Поля модели насоса: ограничения и, в расширенном режиме, паспорт расхода.
// Расхода в простом режиме нет: его даёт калибровка машины.
import { computed, ref, watch } from "vue";
import type { Flow, PumpModel } from "../../api";
import { t } from "../../i18n";
import AppIcon from "../AppIcon.vue";
import FormField from "../FormField.vue";
import NumField from "../NumField.vue";

const pump = defineModel<PumpModel>({ required: true });

const DEFAULT_LIMIT_S = 300;

// Предел работы можно выключить: тогда насос не ограничен по времени.
const limited = computed({
  get: () => pump.value.max_runtime_s !== null,
  set: (on: boolean) => {
    pump.value.max_runtime_s = on ? DEFAULT_LIMIT_S : null;
  },
});

const limit = computed({
  get: () => pump.value.max_runtime_s ?? DEFAULT_LIMIT_S,
  set: (value: number) => {
    pump.value.max_runtime_s = value;
  },
});

// Паспорт насоса: только для расширенного режима полива.
const passport = ref(pump.value.flow !== null);
const tablePoints = ref(
  pump.value.flow?.model === "table"
    ? pump.value.flow.points.map((p) => p.join(" ")).join("\n")
    : "0 20\n400 12\n800 0",
);

watch(passport, (on) => {
  pump.value.flow = on ? (pump.value.flow ?? { model: "constant", flow_ml_s: 10 }) : null;
});

const flowModel = computed({
  get: () => pump.value.flow?.model ?? "constant",
  set: (value: Flow["model"]) => {
    const defaults: Record<Flow["model"], Flow> = {
      constant: { model: "constant", flow_ml_s: 10 },
      linear: { model: "linear", max_flow_ml_s: 240 / 3.6, max_head_mm: 1000 },
      table: { model: "table", points: parsePoints(tablePoints.value) },
    };
    pump.value.flow = defaults[value];
  },
});

// Производители пишут расход в л/ч и высоту в метрах. Внутри мл/с и мм.
const qmaxLh = computed({
  get: () => (pump.value.flow?.model === "linear" ? round(pump.value.flow.max_flow_ml_s * 3.6, 2) : 0),
  set: (value: number) => {
    if (pump.value.flow?.model === "linear") pump.value.flow.max_flow_ml_s = value / 3.6;
  },
});

const hmaxM = computed({
  get: () => (pump.value.flow?.model === "linear" ? round(pump.value.flow.max_head_mm / 1000, 3) : 0),
  set: (value: number) => {
    if (pump.value.flow?.model === "linear") pump.value.flow.max_head_mm = value * 1000;
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
  if (pump.value.flow?.model === "table") pump.value.flow.points = parsePoints(text);
});
</script>

<template>
  <div class="fields">
    <FormField v-slot="{ id }" class="wide" :label="t('catalog.name')">
      <input :id="id" v-model="pump.name" required maxlength="100" :placeholder="t('catalog.pump_placeholder')" />
    </FormField>
  </div>

  <label class="check">
    <input v-model="limited" type="checkbox" />
    <span>{{ t("pump.limit_on") }}</span>
  </label>
  <p v-if="!limited" class="note warn-note">
    <AppIcon name="alert" />
    <span>{{ t("pump.limit_off_warn") }}</span>
  </p>

  <div class="fields">
    <NumField
      v-if="limited"
      v-model="limit"
      :label="t('pump.max_runtime')"
      :unit="t('unit.s')"
      :hint="t('pump.max_runtime_hint')"
      :min="1"
    />
    <NumField
      v-model="pump.cooldown_s"
      :label="t('pump.cooldown')"
      :unit="t('unit.s')"
      :hint="t('pump.cooldown_hint')"
      :min="0"
    />
  </div>

  <details class="passport" :open="passport">
    <summary>{{ t("pump.passport") }}</summary>
    <label class="check">
      <input v-model="passport" type="checkbox" />
      <span>{{ t("pump.passport_on") }}</span>
    </label>
    <template v-if="passport && pump.flow">
      <div class="fields">
        <FormField v-slot="{ id }" class="wide" :label="t('pump.model')">
          <select :id="id" v-model="flowModel">
            <option value="constant">{{ t("pump.model.constant") }}</option>
            <option value="linear">{{ t("pump.model.linear") }}</option>
            <option value="table">{{ t("pump.model.table") }}</option>
          </select>
        </FormField>
        <NumField
          v-if="pump.flow.model === 'constant'"
          v-model="pump.flow.flow_ml_s"
          :label="t('pump.flow')"
          :unit="t('unit.ml_s')"
          :hint="t('pump.flow_hint')"
          :min="0.01"
        />
        <template v-else-if="pump.flow.model === 'linear'">
          <NumField v-model="qmaxLh" :label="t('pump.qmax')" :unit="t('unit.l_h')" :hint="t('pump.qmax_hint')" :min="0.01" />
          <NumField v-model="hmaxM" :label="t('pump.hmax')" :unit="t('unit.m')" :hint="t('pump.hmax_hint')" :min="0.001" />
        </template>
      </div>
      <p class="note">
        <AppIcon name="info" />
        <span>{{ t(`pump.model_hint.${pump.flow.model}`) }}</span>
      </p>
      <FormField v-if="pump.flow.model === 'table'" v-slot="{ id }" :label="t('pump.points')">
        <textarea :id="id" v-model="tablePoints" rows="4" />
      </FormField>
    </template>
  </details>
</template>

<style scoped>
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

.warn-note {
  --accent: var(--warn);
}

.passport {
  margin-top: 14px;
}

.passport summary {
  cursor: pointer;
  font-weight: 600;
}
</style>
