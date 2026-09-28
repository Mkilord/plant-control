<script setup lang="ts">
// Очередь поливов и расписания: кто поливает, кто ждёт, что было.
import { onMounted, onUnmounted, ref } from "vue";
import { api, errorText, type Machine, type QueueItem, type QueueView, type Schedule } from "../api";
import AppIcon from "../components/AppIcon.vue";
import { ml, time } from "../format";
import { t } from "../i18n";

const queue = ref<QueueView>({ running: [], queued: [], history: [] });
const schedules = ref<Schedule[]>([]);
const machines = ref<Machine[]>([]);
const error = ref("");
const note = ref("");
let timer: number | undefined;

async function refresh() {
  try {
    const [view, list, all] = await Promise.all([
      api.queue(),
      api.listSchedules(),
      api.listMachines(),
    ]);
    queue.value = view;
    schedules.value = list;
    machines.value = all;
    error.value = "";
  } catch (e) {
    error.value = errorText(e);
  }
}

function machineName(id: string): string {
  return machines.value.find((m) => m.id === id)?.config.name ?? id;
}

// В очереди хранится id маршрута, человеку показываем название растения.
function plantName(item: QueueItem | Schedule): string {
  const machine = machines.value.find((m) => m.id === item.machine_id);
  const route = machine?.config.routes.find((r) => r.id === item.route_id);
  return route?.name || item.route_id;
}

async function cancel(item: QueueItem) {
  try {
    await api.cancelRequest(item.id);
    await refresh();
  } catch (e) {
    error.value = errorText(e);
  }
}

async function check() {
  note.value = "";
  try {
    const report = await api.checkSchedules();
    note.value = t("queue.checked", { count: report.submitted.length });
    if (report.skipped.length) {
      note.value += ". " + t("queue.skipped", { items: report.skipped.join(", ") });
    }
    await refresh();
  } catch (e) {
    error.value = errorText(e);
  }
}

onMounted(async () => {
  await refresh();
  timer = window.setInterval(() => {
    if (!document.hidden) void refresh();
  }, 2000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="title">{{ t("queue.title") }}</h1>
      <span class="spacer" />
      <button @click="check"><AppIcon name="clock" />{{ t("queue.check") }}</button>
    </div>
    <p class="muted small">{{ t("queue.desc") }}</p>

    <div v-if="error" class="error">{{ error }}</div>
    <p v-if="note" class="muted small">{{ note }}</p>

    <section class="card">
      <h2 class="section-title"><AppIcon name="droplet" :size="18" />{{ t("queue.running") }}</h2>
      <p v-if="!queue.running.length" class="muted small">{{ t("queue.empty") }}</p>
      <ul class="items">
        <li v-for="item in queue.running" :key="item.id">
          <span class="chip on pulse">{{ t("queue.state_running") }}</span>
          <strong>{{ machineName(item.machine_id) }}</strong>
          <span class="muted">{{ plantName(item) }}</span>
          <span>{{ ml(item.dose_ml) }}</span>
          <span class="spacer" />
          <button class="danger" @click="cancel(item)">{{ t("queue.cancel") }}</button>
        </li>
      </ul>
    </section>

    <section class="card">
      <h2 class="section-title"><AppIcon name="clock" :size="18" />{{ t("queue.queued") }}</h2>
      <p v-if="!queue.queued.length" class="muted small">{{ t("queue.empty") }}</p>
      <ul class="items">
        <li v-for="item in queue.queued" :key="item.id">
          <span class="chip">{{ t("queue.position", { position: item.position ?? 1 }) }}</span>
          <strong>{{ machineName(item.machine_id) }}</strong>
          <span class="muted">{{ plantName(item) }}</span>
          <span>{{ ml(item.dose_ml) }}</span>
          <span class="muted small">{{ t(`queue.source_${item.source}`) }}</span>
          <span class="spacer" />
          <button class="danger" @click="cancel(item)">{{ t("queue.cancel") }}</button>
        </li>
      </ul>
    </section>

    <section class="card">
      <h2 class="section-title"><AppIcon name="calculator" :size="18" />{{ t("queue.schedules") }}</h2>
      <p v-if="!schedules.length" class="muted small">{{ t("queue.no_schedules") }}</p>
      <ul class="items">
        <li v-for="item in schedules" :key="item.id">
          <strong>{{ item.machine_name }}</strong>
          <span class="muted">{{ plantName(item) }}</span>
          <span>{{ ml(item.dose_ml) }}</span>
          <span class="spacer" />
          <span v-if="item.enabled && item.next_run_at" class="chip">
            {{ time(item.next_run_at) }}
          </span>
          <span v-else class="chip">{{ t("schedule.off") }}</span>
        </li>
      </ul>
    </section>

    <section class="card">
      <h2 class="section-title"><AppIcon name="check" :size="18" />{{ t("queue.history") }}</h2>
      <p v-if="!queue.history.length" class="muted small">{{ t("queue.no_history") }}</p>
      <ul class="items">
        <li v-for="item in queue.history" :key="item.id">
          <span class="chip" :class="item.state === 'done' ? 'on' : 'danger'">
            {{ t(`queue.state_${item.state}`) }}
          </span>
          <strong>{{ machineName(item.machine_id) }}</strong>
          <span class="muted">{{ plantName(item) }}</span>
          <span>{{ ml(item.dose_ml) }}</span>
          <span class="spacer" />
          <span class="muted small" :title="item.error ?? ''">
            {{ time(item.finished_at ?? item.requested_at) }}
          </span>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  margin: 0 0 8px;
}

.items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.items li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  padding: 6px 0;
  border-top: 1px solid var(--border);
}

.items li:first-child {
  border-top: none;
}

.spacer {
  flex: 1;
}
</style>
