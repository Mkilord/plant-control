<script setup lang="ts">
import { t } from "../i18n";
import { onMounted, onUnmounted, ref } from "vue";
import { api, errorText, type Health, type Machine } from "../api";
import AppIcon from "../components/AppIcon.vue";
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
      <h1 class="title">
        <span class="logo"><AppIcon name="droplet" :size="18" /></span>{{ t("app.title") }}
      </h1>
      <span
        v-if="health"
        class="chip ha"
        :class="health.home_assistant === 'connected' ? 'on' : 'danger'"
      >
        <span class="ha-dot" />
        {{
          health.home_assistant === "connected"
            ? t("list.ha_connected")
            : t("list.ha_status", { status: health.home_assistant })
        }}
      </span>
      <span class="spacer" />
      <RouterLink class="button primary" to="/machines/new"><AppIcon name="plus" />{{ t("list.add") }}</RouterLink
      >
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
.title {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  color: #fff;
  background: linear-gradient(135deg, var(--accent-tank), var(--accent-plant));
}

.ha {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.ha-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
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
