<script setup lang="ts">
// Поливы: что идёт сейчас, что ждёт очереди, что будет по расписанию и журнал.
// Страница обновляется сама: расписания проверяются на сервере, кнопки не нужны.
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  api,
  errorText,
  humanError,
  type Machine,
  type QueueItem,
  type QueueView,
  type Schedule,
} from "../api";
import AppIcon, { type IconName } from "../components/AppIcon.vue";
import SharedSchedules from "../components/SharedSchedules.vue";
import { byDay, clock, ml, span, untilText } from "../format";
import { t } from "../i18n";

const queue = ref<QueueView>({ running: [], queued: [], history: [] });
const schedules = ref<Schedule[]>([]);
const machines = ref<Machine[]>([]);
const error = ref("");
const loaded = ref(false);
// Текущее время для "идёт 0:42" и "через 2 ч": тикает раз в секунду.
const now = ref(new Date());

let poll: number | undefined;
let tick: number | undefined;

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
  } finally {
    loaded.value = true;
  }
}

onMounted(async () => {
  await refresh();
  poll = window.setInterval(() => {
    if (!document.hidden) void refresh();
  }, 2000);
  tick = window.setInterval(() => (now.value = new Date()), 1000);
});
onUnmounted(() => {
  window.clearInterval(poll);
  window.clearInterval(tick);
});

// --- Названия ---

function machineName(item: QueueItem | Schedule): string {
  if ("machine_name" in item && item.machine_name) return item.machine_name;
  return machines.value.find((m) => m.id === item.machine_id)?.config.name ?? t("waterings.deleted");
}

function plantName(item: QueueItem | Schedule): string {
  if ("plant_name" in item && item.plant_name) return item.plant_name;
  const machine = machines.value.find((m) => m.id === item.machine_id);
  return machine?.config.routes.find((r) => r.id === item.route_id)?.name || item.route_id;
}

// --- Сейчас ---

const active = computed(() => [...queue.value.running, ...queue.value.queued]);

function elapsed(item: QueueItem): string {
  const start = item.started_at ?? item.requested_at;
  return span((now.value.getTime() - new Date(start).getTime()) / 1000);
}

async function cancel(item: QueueItem) {
  try {
    await api.cancelRequest(item.id);
    await refresh();
  } catch (e) {
    error.value = errorText(e);
  }
}

// --- Ближайшие ---

const upcoming = computed(() =>
  schedules.value
    .filter((s) => s.enabled && s.next_run_at)
    .sort((a, b) => a.next_run_at!.localeCompare(b.next_run_at!)),
);
const upcomingDays = computed(() => byDay(upcoming.value, (s) => s.next_run_at!));
const disabledCount = computed(() => schedules.value.filter((s) => !s.enabled).length);

// --- Журнал ---

type Filter = "all" | "problems";
const filter = ref<Filter>("all");
const shown = ref(30);

const journal = computed(() =>
  queue.value.history.filter(
    (item) => filter.value === "all" || !["done", "cancelled"].includes(item.state),
  ),
);
const journalDays = computed(() =>
  byDay(journal.value.slice(0, shown.value), (item) => item.finished_at ?? item.requested_at),
);
const problemCount = computed(
  () => queue.value.history.filter((item) => !["done", "cancelled"].includes(item.state)).length,
);

const STATE: Record<QueueItem["state"], { icon: IconName; tone: string }> = {
  queued: { icon: "clock", tone: "" },
  running: { icon: "droplet", tone: "on" },
  done: { icon: "check", tone: "on" },
  failed: { icon: "alert", tone: "danger" },
  cancelled: { icon: "stop", tone: "" },
  expired: { icon: "clock", tone: "warn" },
  skipped: { icon: "skip", tone: "warn" },
};

// Сколько работал полив. Только для удачных: у прерванных цифра ничего не говорит.
function duration(item: QueueItem): string {
  if (item.state !== "done" || !item.started_at || !item.finished_at) return "";
  return span((new Date(item.finished_at).getTime() - new Date(item.started_at).getTime()) / 1000);
}
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <div>
        <h1>{{ t("waterings.title") }}</h1>
        <p class="muted small subtitle">{{ t("waterings.desc") }}</p>
      </div>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div class="cards">
      <!-- Сейчас -->
      <section class="card now" :class="{ live: queue.running.length }">
        <h2 class="section-title">
          <AppIcon name="droplet" :size="18" />{{ t("waterings.now") }}
        </h2>
        <p v-if="loaded && !active.length" class="muted small quiet">
          {{ t("waterings.idle") }}
        </p>
        <ul class="items">
          <li v-for="item in active" :key="item.id" class="item">
            <span class="state" :class="item.state === 'running' ? 'on pulse' : ''">
              <AppIcon :name="item.state === 'running' ? 'droplet' : 'clock'" :size="16" />
            </span>
            <div class="main">
              <div class="line">
                <strong>{{ plantName(item) }}</strong>
                <span class="muted">{{ machineName(item) }}</span>
              </div>
              <div class="meta muted small">
                <template v-if="item.state === 'running'">
                  {{ t("waterings.running_for", { time: elapsed(item) }) }}
                </template>
                <template v-else>
                  {{ t("waterings.waiting", { position: item.position ?? 1, time: elapsed(item) }) }}
                </template>
                · {{ ml(item.dose_ml) }} · {{ t(`waterings.source_${item.source}`) }}
              </div>
            </div>
            <button class="danger small-button" @click="cancel(item)">
              {{ item.state === "running" ? t("waterings.stop") : t("waterings.cancel") }}
            </button>
          </li>
        </ul>
      </section>

      <!-- Ближайшие по расписанию -->
      <section class="card">
        <h2 class="section-title">
          <AppIcon name="calendar" :size="18" />{{ t("waterings.upcoming") }}
        </h2>
        <p v-if="loaded && !upcoming.length" class="muted small quiet">
          {{ t("waterings.no_upcoming") }}
          <RouterLink to="/">{{ t("waterings.no_upcoming_hint") }}</RouterLink>
        </p>
        <div v-for="day in upcomingDays" :key="day.label" class="day">
          <div class="day-label">{{ day.label }}</div>
          <ul class="items">
            <li v-for="item in day.items" :key="item.id" class="item">
              <span class="time">{{ clock(item.next_run_at) }}</span>
              <div class="main">
                <div class="line">
                  <strong>{{ plantName(item) }}</strong>
                  <span class="muted">{{ item.machine_name }}</span>
                </div>
              </div>
              <span class="muted small nowrap">{{ ml(item.dose_ml) }}</span>
              <span class="chip nowrap">{{ untilText(item.next_run_at!, now) }}</span>
            </li>
          </ul>
        </div>
        <p v-if="disabledCount" class="muted small footnote">
          {{ t("waterings.disabled", { count: disabledCount }) }}
        </p>
      </section>

      <!-- Общие расписания -->
      <SharedSchedules :machines="machines" @changed="refresh" />

      <!-- Журнал -->
      <section class="card">
        <div class="section-head">
          <h2 class="section-title">
            <AppIcon name="history" :size="18" />{{ t("waterings.journal") }}
          </h2>
          <span class="spacer" />
          <div class="segmented" role="group">
            <button :class="{ active: filter === 'all' }" @click="filter = 'all'">
              {{ t("waterings.filter_all") }}
            </button>
            <button :class="{ active: filter === 'problems' }" @click="filter = 'problems'">
              {{ t("waterings.filter_problems") }}
              <span v-if="problemCount" class="mini-count">{{ problemCount }}</span>
            </button>
          </div>
        </div>

        <p v-if="loaded && !journal.length" class="muted small quiet">
          {{ filter === "all" ? t("waterings.no_journal") : t("waterings.no_journal_problems") }}
        </p>

        <div v-for="day in journalDays" :key="day.label" class="day">
          <div class="day-label">{{ day.label }}</div>
          <ul class="items">
            <li v-for="item in day.items" :key="item.id" class="item">
              <span class="time">{{ clock(item.finished_at ?? item.requested_at) }}</span>
              <span class="state" :class="STATE[item.state].tone" :title="t(`queue.state_${item.state}`)">
                <AppIcon :name="STATE[item.state].icon" :size="15" />
              </span>
              <div class="main">
                <div class="line">
                  <strong>{{ plantName(item) }}</strong>
                  <span class="muted">{{ machineName(item) }}</span>
                </div>
                <div class="meta muted small">
                  {{ t(`queue.state_${item.state}`) }}
                  <template v-if="item.state !== 'skipped'"> · {{ ml(item.dose_ml) }}</template>
                  <template v-if="duration(item)"> · {{ duration(item) }}</template>
                  · {{ t(`waterings.source_${item.source}`) }}
                </div>
                <div v-if="item.error" class="reason small" :class="STATE[item.state].tone">
                  {{ humanError(item.error) }}
                </div>
              </div>
            </li>
          </ul>
        </div>

        <button v-if="journal.length > shown" class="more" @click="shown += 30">
          {{ t("waterings.more", { count: journal.length - shown }) }}
        </button>
      </section>
    </div>
  </div>
</template>

<style scoped>
.subtitle {
  margin: 2px 0 0;
}

.section-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  margin: 0 0 8px;
}

.section-head .section-title {
  margin: 0;
}

.now.live {
  border-color: color-mix(in srgb, var(--primary) 45%, var(--border));
}

.quiet {
  margin: 4px 0 0;
}

.day + .day {
  margin-top: 10px;
}

.day-label {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  padding: 8px 0 4px;
}

.items {
  list-style: none;
  margin: 0;
  padding: 0;
}

.item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 0;
  border-top: 1px solid var(--border);
  font-size: 14px;
}

.item:first-child {
  border-top: none;
}

.time {
  width: 44px;
  flex: none;
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  padding-top: 1px;
}

.state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex: none;
  border-radius: 50%;
  color: var(--muted);
  background: var(--bg);
}

.state.on {
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 14%, transparent);
}

.state.warn {
  color: var(--warn);
  background: color-mix(in srgb, var(--warn) 14%, transparent);
}

.state.danger {
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 14%, transparent);
}

.pulse {
  animation: pulse 1.6s ease-in-out infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.5;
  }
}

.main {
  flex: 1;
  min-width: 0;
}

.line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  align-items: baseline;
}

.meta {
  margin-top: 2px;
}

.reason {
  margin-top: 4px;
}

.reason.danger {
  color: var(--danger);
}

.reason.warn {
  color: var(--warn);
}

.nowrap {
  white-space: nowrap;
}

.small-button {
  padding: 4px 10px;
  font-size: 13px;
}

.footnote {
  margin: 10px 0 0;
}

.spacer {
  flex: 1;
}

.segmented {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.segmented button {
  border: none;
  border-radius: 0;
  padding: 4px 10px;
  font-size: 13px;
}

.segmented button + button {
  border-left: 1px solid var(--border);
}

.segmented button.active {
  background: var(--primary);
  color: var(--primary-text);
}

.mini-count {
  min-width: 16px;
  padding: 0 4px;
  border-radius: 8px;
  font-size: 11px;
  background: var(--warn);
  color: #fff;
}

.more {
  margin-top: 10px;
  width: 100%;
  justify-content: center;
}
</style>
