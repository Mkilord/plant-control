<script setup lang="ts">
import { t } from "../i18n";
import { computed, ref, watch } from "vue";
import { api, errorText, problemText, type Machine, type Plan } from "../api";
import { ml, seconds } from "../format";
import AppIcon from "./AppIcon.vue";
import ModalDialog from "./ModalDialog.vue";
import NumField from "./NumField.vue";

const props = defineProps<{ machine: Machine }>();
const emit = defineEmits<{ close: []; started: [] }>();

const routes = computed(() => props.machine.config.routes);
const routeId = ref(routes.value[0]?.id ?? "");

// Доза растения: из его расписания (общего или своего, с сезонной поправкой),
// а без расписания - доза растения из настроек машины.
function doseFor(id: string): number {
  const scheduled = props.machine.status.schedules.find((s) => s.route_id === id);
  if (scheduled) return Math.round(scheduled.dose_ml);
  return routes.value.find((r) => r.id === id)?.default_dose_ml ?? 100;
}

const dose = ref(doseFor(routeId.value));
const plan = ref<Plan | null>(null);
const error = ref("");
const busy = ref(false);

// Что мешает поливу выбранного растения: проблемы машины и его клапана.
const blockers = computed(() =>
  props.machine.status.blockers.filter((b) => !b.route_scoped || b.target === routeId.value),
);
const blockedText = computed(() => blockers.value.map(problemText).join("; "));

// Другое растение - его доза.
watch(routeId, (id) => {
  dose.value = doseFor(id);
});

// Любое изменение входных данных делает расчёт устаревшим.
watch([routeId, dose], () => {
  plan.value = null;
});

async function calculate() {
  error.value = "";
  busy.value = true;
  try {
    plan.value = await api.plan(props.machine.id, routeId.value, dose.value);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}

async function water() {
  error.value = "";
  busy.value = true;
  try {
    await api.water(props.machine.id, routeId.value, dose.value);
    emit("started");
    emit("close");
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}

function routeLabel(id: string): string {
  const route = routes.value.find((r) => r.id === id);
  return route?.name ? `${route.name} (${id})` : id;
}
</script>

<template>
  <ModalDialog :title="t('water.title', { name: machine.config.name })" @close="emit('close')">
    <label v-if="routes.length > 1" class="field">
      <span>{{ t("water.plant") }}</span>
      <select v-model="routeId">
        <option v-for="route in routes" :key="route.id" :value="route.id">
          {{ routeLabel(route.id) }}
        </option>
      </select>
    </label>
    <NumField v-model="dose" :label="t('water.dose')" :unit="t('unit.ml')" :min="1" />

    <table v-if="plan" class="kv">
      <tbody>
        <tr>
          <td>{{ t("water.duration") }}</td>
          <td><b>{{ seconds(plan.duration_s) }}</b></td>
        </tr>
        <tr>
          <td>{{ t("water.pumped") }}</td>
          <td>{{ ml(plan.pumped_ml) }}</td>
        </tr>
        <tr>
          <td>{{ t("water.consumed") }}</td>
          <td>{{ ml(plan.consumed_ml) }}</td>
        </tr>
        <tr v-if="machine.config.flow_mode === 'advanced'">
          <td>{{ t("water.head") }}</td>
          <td>
            {{ Math.round(plan.head_start_mm) }} / {{ Math.round(plan.head_end_mm) }}
            {{ t("unit.mm") }}
          </td>
        </tr>
        <tr>
          <td>{{ t("water.flow") }}</td>
          <td>
            {{ plan.flow_start_ml_s.toFixed(1) }} / {{ plan.flow_end_ml_s.toFixed(1) }}
            {{ t("unit.ml_s") }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="blockers.length" class="error">
      {{ t("water.blocked", { reasons: blockedText }) }}
    </div>
    <div v-if="error" class="error">{{ error }}</div>

    <div class="row">
      <button :disabled="busy || dose <= 0" @click="calculate">
        <AppIcon name="calculator" />{{ t("water.calculate") }}
      </button>
      <button class="primary" :disabled="busy || dose <= 0 || blockers.length > 0" @click="water">
        <AppIcon name="droplet" />{{ t("water.start") }}
      </button>
    </div>
  </ModalDialog>
</template>
