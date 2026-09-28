<script setup lang="ts">
// Проблемы: их находит проверка состояния, руками можно подтвердить и приглушить.
import { onMounted, onUnmounted, ref } from "vue";
import { api, errorText, type Problem } from "../api";
import AppIcon from "../components/AppIcon.vue";
import { time } from "../format";
import { hasMessage, t } from "../i18n";

const problems = ref<Problem[]>([]);
const names = ref<Record<string, string>>({});
const error = ref("");
let timer: number | undefined;

async function refresh() {
  try {
    const [list, machines] = await Promise.all([api.problems(), api.listMachines()]);
    problems.value = list;
    names.value = Object.fromEntries(machines.map((m) => [m.id, m.config.name]));
    error.value = "";
  } catch (e) {
    error.value = errorText(e);
  }
}

function title(problem: Problem): string {
  const key = `problem.${problem.kind}`;
  return hasMessage(key) ? t(key) : problem.kind;
}

function machineName(id: string): string {
  return names.value[id] || id;
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
      <h1 class="title">{{ t("problems.title") }}</h1>
      <span class="spacer" />
      <button @click="act(() => api.checkProblems())">
        <AppIcon name="alert" />{{ t("problems.check") }}
      </button>
    </div>
    <p class="muted small">{{ t("problems.desc") }}</p>

    <div v-if="error" class="error">{{ error }}</div>

    <div v-if="!problems.length" class="card empty">
      <div class="empty-icon"><AppIcon name="check" :size="40" /></div>
      <p>{{ t("problems.empty") }}</p>
    </div>

    <article v-for="problem in problems" :key="problem.id" class="card problem">
      <header class="head">
        <span class="badge" :class="problem.severity"><AppIcon name="alert" :size="20" /></span>
        <div class="titles">
          <h2>{{ title(problem) }}</h2>
          <p class="muted small">
            {{ machineName(problem.machine_id) }}
            <template v-if="problem.target">/ {{ problem.target }}</template>
            &middot; {{ t("problems.since", { time: time(problem.opened_at) }) }}
          </p>
        </div>
      </header>

      <p v-if="problem.details" class="small">{{ problem.details }}</p>

      <div class="chips">
        <span v-if="problem.blocking" class="chip danger">{{ t("problems.blocking") }}</span>
        <span v-if="problem.acknowledged" class="chip">{{ t("problems.acknowledged") }}</span>
        <span v-if="problem.muted_until" class="chip">
          {{ t("problems.muted", { until: time(problem.muted_until) }) }}
        </span>
      </div>

      <footer class="actions">
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
