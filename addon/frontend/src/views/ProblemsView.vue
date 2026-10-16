<script setup lang="ts">
// Проблемы: их находит проверка состояния, руками можно подтвердить и приглушить.
import { onMounted, onUnmounted, ref } from "vue";
import { api, errorText, type Machine, type Problem } from "../api";
import AppIcon from "../components/AppIcon.vue";
import { time } from "../format";
import { hasMessage, t } from "../i18n";

const problems = ref<Problem[]>([]);
const machines = ref<Machine[]>([]);
const error = ref("");
const loaded = ref(false);
let timer: number | undefined;

async function refresh() {
  try {
    const [list, all] = await Promise.all([api.problems(), api.listMachines()]);
    problems.value = list;
    machines.value = all;
    error.value = "";
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loaded.value = true;
  }
}

function title(problem: Problem): string {
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
    </div>
  </div>
</template>

<style scoped>
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
