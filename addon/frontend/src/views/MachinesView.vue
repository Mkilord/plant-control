<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { api, errorText, type Health, type Machine } from "../api";
import MachineCard from "../components/MachineCard.vue";

const machines = ref<Machine[]>([]);
const health = ref<Health | null>(null);
const error = ref("");
const loaded = ref(false);

let timer: number | undefined;

async function refresh() {
  try {
    [machines.value, health.value] = await Promise.all([api.listMachines(), api.health()]);
    error.value = "";
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loaded.value = true;
  }
}

// Опрос статуса: чаще, пока идёт полив.
function schedule() {
  const busy = machines.value.some((m) => m.status.busy);
  timer = window.setTimeout(
    async () => {
      if (!document.hidden) await refresh();
      schedule();
    },
    busy ? 1000 : 3000,
  );
}

onMounted(async () => {
  await refresh();
  schedule();
});
onUnmounted(() => window.clearTimeout(timer));
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h1>Полив</h1>
      <span
        v-if="health"
        class="chip"
        :class="health.home_assistant === 'connected' ? 'on' : 'danger'"
      >
        {{ health.home_assistant === "connected" ? "HA на связи" : "HA: " + health.home_assistant }}
      </span>
      <span class="spacer" />
      <RouterLink class="button primary" to="/machines/new">Добавить поливалку</RouterLink>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div v-if="loaded && !machines.length && !error" class="card empty">
      <p>Поливалок пока нет.</p>
      <p class="muted small">
        Добавьте первую: укажите размеры бака, реле насоса из Home Assistant и трубку до растения.
      </p>
      <RouterLink class="button primary" to="/machines/new">Добавить поливалку</RouterLink>
    </div>

    <div class="grid">
      <MachineCard v-for="m in machines" :key="m.id" :machine="m" @changed="refresh" />
    </div>
  </div>
</template>

<style scoped>
.empty {
  text-align: center;
  padding: 32px 16px;
}
</style>
