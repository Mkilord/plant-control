<script setup lang="ts">
// Проблемы: их находит проверка состояния, руками можно подтвердить и приглушить.
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, errorText, type Machine, type Problem, type ProblemLogRecord } from "../api";
import AppIcon from "../components/AppIcon.vue";
import ClearJournalMenu from "../components/ClearJournalMenu.vue";
import { byDay, clock, span, time } from "../format";
import { hasMessage, t } from "../i18n";

const problems = ref<Problem[]>([]);
const log = ref<ProblemLogRecord[]>([]);
const shown = ref(30);
const cleared = ref("");
const machines = ref<Machine[]>([]);
const error = ref("");
const loaded = ref(false);
let timer: number | undefined;

async function refresh() {
  try {
    const [list, all, history] = await Promise.all([
      api.problems(),
      api.listMachines(),
      api.problemLog(),
    ]);
    problems.value = list;
    log.value = history;
    machines.value = all;
    error.value = "";
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loaded.value = true;
  }
}

// --- История ---

const logDays = computed(() => byDay(log.value.slice(0, shown.value), (r) => r.opened_at));

function lasted(record: ProblemLogRecord): string {
  if (!record.closed_at) return t("problems.log_ongoing");
  const seconds = (new Date(record.closed_at).getTime() - new Date(record.opened_at).getTime()) / 1000;
  return t("problems.log_lasted", { time: span(Math.max(1, seconds)) });
}

function clearable(days: number | null): ProblemLogRecord[] {
  const cutoff = days === null ? Infinity : Date.now() - days * 86_400_000;
  return log.value.filter((r) => r.closed_at && new Date(r.closed_at).getTime() < cutoff);
}

async function clearLog(days: number | null): Promise<number> {
  const { deleted } = await api.clearProblemLog({ older_than_days: days });
  return deleted;
}

async function afterClear(deleted: number) {
  cleared.value = t("journal.deleted", { count: deleted });
  await refresh();
}

async function removeRecord(record: ProblemLogRecord) {
  try {
    await api.clearProblemLog({ ids: [record.id] });
    log.value = log.value.filter((r) => r.id !== record.id);
  } catch (e) {
    error.value = errorText(e);
  }
}

function title(problem: Problem | ProblemLogRecord): string {
  const key = `problem.${problem.kind}`;
  return hasMessage(key) ? t(key) : problem.kind;
}

function machineName(id: string): string {
  return machines.value.find((m) => m.id === id)?.config.name ?? id;
}

// Чего касается проблема: растение по его клапану или сущность насоса.
function targetName(problem: Problem): string {
  if (!problem.target) return "";
  const machine = machines.value.find((m) => m.id === problem.machine_id);
  // Сущность насоса и так названа в подробностях: здесь только растение.
  const route = machine?.config.routes.find((r) => r.id === problem.target);
  return route ? route.name || route.id : "";
}

function fix(problem: Problem): string {
  const key = `fix.${problem.kind}`;
  return hasMessage(key) ? t(key) : "";
}

async function act(action: () => Promise<unknown>) {
  try {
    await action();
    await refresh();
  } catch (e) {
    error.value = errorText(e);
  }
}

onMounted(async () => {
  await refresh();
  timer = window.setInterval(() => {
    if (!document.hidden) void refresh();
  }, 3000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <div>
        <h1>{{ t("problems.title") }}</h1>
        <p class="muted small subtitle">{{ t("problems.desc") }}</p>
      </div>
      <span class="spacer" />
      <button @click="act(() => api.checkProblems())">
        <AppIcon name="history" />{{ t("problems.check") }}
      </button>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div class="cards">
      <div v-if="loaded && !problems.length" class="card empty">
        <div class="empty-icon"><AppIcon name="check" :size="40" /></div>
        <p>{{ t("problems.empty") }}</p>
        <p class="muted small">{{ t("problems.empty_hint") }}</p>
      </div>

      <article v-for="problem in problems" :key="problem.id" class="card problem">
        <header class="head">
          <span class="badge" :class="problem.severity"><AppIcon name="alert" :size="20" /></span>
          <div class="titles">
            <h2>{{ title(problem) }}</h2>
            <p class="muted small">
              {{ machineName(problem.machine_id) }}
              <template v-if="targetName(problem)"> · {{ targetName(problem) }}</template>
              &middot; {{ t("problems.since", { time: time(problem.opened_at) }) }}
            </p>
          </div>
        </header>

        <p v-if="problem.details" class="small details">{{ problem.details }}</p>
        <p v-if="fix(problem)" class="note fix">
          <AppIcon name="info" />
          <span>{{ fix(problem) }}</span>
        </p>

        <div class="chips">
          <span v-if="problem.blocking" class="chip danger">{{ t("problems.blocking") }}</span>
          <span v-if="problem.acknowledged" class="chip">{{ t("problems.acknowledged") }}</span>
          <span v-if="problem.muted_until" class="chip">
            {{ t("problems.muted", { until: time(problem.muted_until) }) }}
          </span>
        </div>

        <footer class="actions">
          <template v-if="problem.kind === 'calibration_stale'">
            <RouterLink class="button primary" :to="`/machines/${problem.machine_id}/calibrate?route=${problem.target}`">
              <AppIcon name="pump" />{{ t("calib.recalibrate") }}
            </RouterLink>
            <button @click="act(() => api.acceptCalibration(problem.machine_id, problem.target))">
              {{ t("calib.keep") }}
            </button>
          </template>
          <RouterLink class="button" :to="`/machines/${problem.machine_id}`">
            <AppIcon name="edit" />{{ t("problems.open_machine") }}
          </RouterLink>
          <button v-if="!problem.acknowledged" @click="act(() => api.ackProblem(problem.id))">
            <AppIcon name="check" />{{ t("problems.ack") }}
          </button>
          <button v-if="!problem.muted_until" @click="act(() => api.muteProblem(problem.id, 24))">
            {{ t("problems.mute") }}
          </button>
          <button v-else @click="act(() => api.unmuteProblem(problem.id))">
            {{ t("problems.unmute") }}
          </button>
        </footer>
      </article>

      <!-- История: когда проблемы открывались и закрывались -->
      <section class="card">
        <div class="log-head">
          <h2 class="log-title"><AppIcon name="history" :size="18" />{{ t("problems.log") }}</h2>
          <ClearJournalMenu
            v-if="log.length"
            :what="t('journal.what_problems')"
            :note="t('journal.open_kept')"
            :count="(days) => clearable(days).length"
            :clear="clearLog"
            @done="afterClear"
          />
        </div>
        <p v-if="cleared" class="muted small">{{ cleared }}</p>
        <p v-if="loaded && !log.length" class="muted small">{{ t("problems.log_empty") }}</p>
        <div v-for="day in logDays" :key="day.label" class="day">
          <div class="day-label muted small">{{ day.label }}</div>
          <ul class="log">
            <li v-for="record in day.items" :key="record.id" class="log-item">
              <span class="log-time small">{{ clock(record.opened_at) }}</span>
              <span class="dot" :class="{ open: !record.closed_at, blocking: record.blocking }" />
              <div class="log-main">
                <div>
                  <strong>{{ title(record) }}</strong>
                  <span class="muted"> · {{ record.machine_name }}</span>
                </div>
                <div class="muted small">
                  {{ lasted(record) }}
                  <template v-if="record.blocking"> · {{ t("problems.blocking") }}</template>
                </div>
                <div v-if="record.details" class="small log-details">{{ record.details }}</div>
              </div>
              <button
                v-if="record.closed_at"
                type="button"
                class="icon-button remove"
                :title="t('journal.remove_one')"
                :aria-label="t('journal.remove_one')"
                @click="removeRecord(record)"
              >
                <AppIcon name="trash" :size="15" />
              </button>
            </li>
          </ul>
        </div>
        <button v-if="log.length > shown" class="ghost" @click="shown += 30">
          {{ t("waterings.more", { count: log.length - shown }) }}
        </button>
      </section>
    </div>
  </div>
</template>

<style scoped>
.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.log-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  margin: 0;
}

.day {
  margin-top: 10px;
}

.day-label {
  text-transform: capitalize;
}

.log {
  list-style: none;
  margin: 0;
  padding: 0;
}

.log-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 0;
  border-top: 1px solid var(--border);
  font-size: 14px;
}

.log-item:first-child {
  border-top: none;
}

.log-time {
  min-width: 38px;
  font-variant-numeric: tabular-nums;
  padding-top: 1px;
}

.dot {
  flex: none;
  width: 9px;
  height: 9px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--reserve);
}

.dot.blocking {
  background: color-mix(in srgb, var(--danger) 55%, var(--reserve));
}

.dot.open {
  background: var(--warn);
}

.dot.open.blocking {
  background: var(--danger);
}

.log-main {
  flex: 1;
  min-width: 0;
}

.log-details {
  color: var(--muted);
  overflow-wrap: anywhere;
}

.remove {
  padding: 4px 6px;
  opacity: 0.6;
}

.remove:hover,
.remove:focus-visible {
  color: var(--danger);
  opacity: 1;
}

.head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 12px;
  color: #fff;
  background: var(--accent-tank);
}

.badge.error {
  background: var(--danger);
}

.badge.warning {
  background: var(--warn);
}

.badge.info {
  background: var(--accent-tank);
}

.titles h2 {
  font-size: 16px;
  margin: 0;
}

.problem {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.subtitle {
  margin: 2px 0 0;
}

.spacer {
  flex: 1;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chips:empty {
  display: none;
}

.details {
  margin: 0;
}

.fix {
  margin: 0;
}

.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.empty {
  text-align: center;
  padding: 28px 16px;
}

.empty-icon {
  color: var(--accent-plant);
}
</style>
