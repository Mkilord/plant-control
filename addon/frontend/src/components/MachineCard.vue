<script setup lang="ts">
import { computed, ref } from "vue";
import { api, errorText, type Machine } from "../api";
import { ml, time } from "../format";
import TankDialog from "./TankDialog.vue";
import TankGauge from "./TankGauge.vue";
import WaterDialog from "./WaterDialog.vue";

const props = defineProps<{ machine: Machine }>();
const emit = defineEmits<{ changed: [] }>();

const showWater = ref(false);
const showTank = ref(false);
const error = ref("");

const status = computed(() => props.machine.status);

const pumpChip = computed(() => {
  switch (status.value.pump.state) {
    case "on":
      return { text: "насос работает", cls: "on" };
    case "unknown":
      return { text: "насос: неизвестно", cls: "danger" };
    default:
      return { text: "насос выключен", cls: "" };
  }
});

const valveList = computed(() => Object.entries(status.value.valves));

async function stop() {
  error.value = "";
  try {
    const result = await api.stop(props.machine.id);
    if (result.errors.length) error.value = result.errors.join("; ");
  } catch (e) {
    error.value = errorText(e);
  }
  emit("changed");
}
</script>

<template>
  <div class="card machine">
    <div class="row head">
      <h2>{{ machine.config.name }}</h2>
      <span v-if="status.busy" class="chip on">поливает</span>
      <span class="chip" :class="pumpChip.cls">{{ pumpChip.text }}</span>
    </div>

    <TankGauge :tank="status.tank" />

    <div v-if="valveList.length" class="row small">
      <span class="muted">Клапаны:</span>
      <span
        v-for="[id, state] in valveList"
        :key="id"
        class="chip"
        :class="{ on: state === 'open', danger: state === 'unknown' }"
      >
        {{ id }}
      </span>
    </div>

    <div v-if="status.last_watering" class="small">
      <span class="muted">Последний полив:</span>
      {{ time(status.last_watering.started_at) }}, {{ ml(status.last_watering.dose_ml) }}
      <span v-if="status.last_watering.ok" class="chip on">ok</span>
      <span v-else class="chip danger" :title="status.last_watering.error ?? ''">ошибка</span>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div class="row actions">
      <button class="primary" :disabled="status.busy" @click="showWater = true">Полить</button>
      <button @click="showTank = true">Бак</button>
      <RouterLink class="button" :to="`/machines/${machine.id}`">Настроить</RouterLink>
      <button class="danger" :class="{ solid: status.busy }" @click="stop">Стоп</button>
    </div>

    <WaterDialog
      v-if="showWater"
      :machine="machine"
      @close="showWater = false"
      @started="emit('changed')"
    />
    <TankDialog
      v-if="showTank"
      :machine="machine"
      @close="showTank = false"
      @changed="emit('changed')"
    />
  </div>
</template>

<style scoped>
.machine {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.head h2 {
  flex: 1;
}

.actions {
  margin-top: auto;
}
</style>
