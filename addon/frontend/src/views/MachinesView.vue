<script setup lang="ts">
import { t } from "../i18n";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, errorText, type Machine } from "../api";
import AppIcon from "../components/AppIcon.vue";
import MachineCard from "../components/MachineCard.vue";

const machines = ref<Machine[]>([]);
const busyCount = computed(() => machines.value.filter((m) => m.status.busy).length);
const error = ref("");
const loaded = ref(false);

let timer: number | undefined;

async function refresh() {
  try {
    machines.value = await api.listMachines();
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
      <div>
        <h1>{{ t("list.title") }}</h1>
        <p v-if="machines.length" class="muted small subtitle">
          {{ t("list.summary", { count: machines.length, busy: busyCount }) }}
        </p>
      </div>
      <span class="spacer" />
      <RouterLink class="button primary" to="/machines/new">
        <AppIcon name="plus" />{{ t("list.add") }}
      </RouterLink>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div v-if="loaded && !machines.length && !error" class="card empty">
      <div class="empty-icon"><AppIcon name="plant" :size="40" /></div>
      <p>{{ t("list.empty") }}</p>
      <p class="muted small">{{ t("list.empty_hint") }}</p>
      <RouterLink class="button primary" to="/machines/new"><AppIcon name="plus" />{{ t("list.add") }}</RouterLink
      >
    </div>

    <div class="grid">
      <MachineCard v-for="m in machines" :key="m.id" :machine="m" @changed="refresh" />
    </div>
  </div>
</template>

<style scoped>
.subtitle {
  margin: 2px 0 0;
}

.empty-icon {
  color: var(--accent-plant);
  margin-bottom: 8px;
}

.empty {
  text-align: center;
  padding: 32px 16px;
}
</style>
