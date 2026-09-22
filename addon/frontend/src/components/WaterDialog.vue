<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api, errorText, type Machine, type Plan } from "../api";
import { ml, seconds } from "../format";
import ModalDialog from "./ModalDialog.vue";

const props = defineProps<{ machine: Machine }>();
const emit = defineEmits<{ close: []; started: [] }>();

const routes = computed(() => props.machine.config.routes);
const routeId = ref(routes.value[0]?.id ?? "");
const dose = ref(100);
const plan = ref<Plan | null>(null);
const error = ref("");
const busy = ref(false);

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
  <ModalDialog :title="`Полить: ${machine.config.name}`" @close="emit('close')">
    <label v-if="routes.length > 1" class="field">
      <span>Растение</span>
      <select v-model="routeId">
        <option v-for="route in routes" :key="route.id" :value="route.id">
          {{ routeLabel(route.id) }}
        </option>
      </select>
    </label>
    <label class="field">
      <span>Доза, мл</span>
      <input v-model.number="dose" type="number" min="1" step="10" @keyup.enter="calculate" />
    </label>

    <table v-if="plan" class="kv">
      <tbody>
        <tr>
          <td>Время работы насоса</td>
          <td><b>{{ seconds(plan.duration_s) }}</b></td>
        </tr>
        <tr>
          <td>Насос прокачает</td>
          <td>{{ ml(plan.pumped_ml) }}</td>
        </tr>
        <tr>
          <td>Уйдёт из бака</td>
          <td>{{ ml(plan.consumed_ml) }}</td>
        </tr>
        <tr>
          <td>Напор в начале / в конце</td>
          <td>{{ Math.round(plan.head_start_mm) }} / {{ Math.round(plan.head_end_mm) }} мм</td>
        </tr>
        <tr>
          <td>Расход в начале / в конце</td>
          <td>{{ plan.flow_start_ml_s.toFixed(1) }} / {{ plan.flow_end_ml_s.toFixed(1) }} мл/с</td>
        </tr>
      </tbody>
    </table>

    <div v-if="error" class="error">{{ error }}</div>

    <div class="row">
      <button :disabled="busy || dose <= 0" @click="calculate">Рассчитать</button>
      <button class="primary" :disabled="busy || dose <= 0" @click="water">Полить</button>
    </div>
  </ModalDialog>
</template>
