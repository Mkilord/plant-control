<script setup lang="ts">
import { computed, ref } from "vue";
import { api, errorText, humanError, problemText, type Machine } from "../api";
import { ml, time } from "../format";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import CopyMachineDialog from "./CopyMachineDialog.vue";
import ScheduleDialog from "./ScheduleDialog.vue";
import TankDialog from "./TankDialog.vue";
import TankGauge from "./TankGauge.vue";
import WaterDialog from "./WaterDialog.vue";

const props = defineProps<{ machine: Machine }>();
const emit = defineEmits<{ changed: [] }>();

const showWater = ref(false);
const showTank = ref(false);
const showSchedule = ref(false);
const showCopy = ref(false);
const error = ref("");

const status = computed(() => props.machine.status);
const hasCollector = computed(() => props.machine.config.plumbing.type === "collector");

// Растения машины. У машины с коллектором рядом состояние клапана.
const plants = computed(() =>
  props.machine.config.routes.map((route) => ({
    id: route.id,
    name: route.name || route.id,
    valve: status.value.valves[route.id],
  })),
);

const plantTitle = computed(() => {
  const named = props.machine.config.routes.map((r) => r.name).filter(Boolean);
  return named.length ? named.join(", ") : t("card.no_plant");
});

// Ближайший полив по расписанию среди всех растений машины.
const nextRun = computed(() => {
  const times = status.value.schedules
    .filter((item) => item.enabled && item.next_run_at)
    .map((item) => item.next_run_at as string)
    .sort();
  return times[0] ?? null;
});

// Заявка, которая ждёт своей очереди: пока горит эта метка, полив ещё не начался.
const waiting = computed(() => status.value.queue.find((item) => item.state === "queued") ?? null);

// Проблемы всей машины: пока они открыты, не полить ни одно растение.
// Проблема клапана мешает только своему растению - о ней скажет окно полива.
const machineBlockers = computed(() => status.value.blockers.filter((b) => !b.route_scoped));
const blockedText = computed(() => machineBlockers.value.map(problemText).join(", "));
// Растения, которые сейчас не полить из-за своего клапана.
const blockedPlants = computed(
  () => new Set(status.value.blockers.filter((b) => b.route_scoped).map((b) => b.target)),
);

const pumpChip = computed(() => {
  switch (status.value.pump.state) {
    case "on":
      return { text: t("card.pump_on"), cls: "on" };
    case "unknown":
      return { text: t("card.pump_unknown"), cls: "danger" };
    default:
      return { text: t("card.pump_off"), cls: "" };
  }
});

// Калибровка: идёт сейчас, не хватает замера, пора повторить.
const calibrating = computed(() => status.value.calibration_session !== null);
const needsCalibration = computed(() => status.value.flows.some((f) => f.source === "none"));
const calibrationDue = computed(() => status.value.flows.some((f) => f.due));
// Насос, бак или трубки поменялись после калибровки: эти растения не поливаются.
const staleRoutes = computed(() => status.value.flows.filter((f) => f.stale).map((f) => f.route_id));

function plantName(routeId: string): string {
  const route = props.machine.config.routes.find((r) => r.id === routeId);
  return route?.name || routeId;
}

async function keepCalibration(routeId: string) {
  error.value = "";
  try {
    await api.acceptCalibration(props.machine.id, routeId);
  } catch (e) {
    error.value = errorText(e);
  }
  emit("changed");
}
const suggestion = computed(() => status.value.flow_suggestion);
const suggestionText = computed(() => {
  const s = suggestion.value;
  if (!s) return "";
  const pct = Math.round(Math.abs(s.factor - 1) * 100);
  return t(s.factor > 1 ? "calib.suggest_more" : "calib.suggest_less", {
    pct,
    actual: ml(s.actual_ml),
    expected: ml(s.expected_ml),
    n: s.waterings,
  });
});

async function resolveSuggestion(apply: boolean) {
  error.value = "";
  try {
    await api.resolveFlowSuggestion(props.machine.id, apply);
  } catch (e) {
    error.value = errorText(e);
  }
  emit("changed");
}

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
  <article class="card machine" :class="{ busy: status.busy }">
    <header class="head">
      <span class="badge"><AppIcon name="plant" :size="22" /></span>
      <div class="titles">
        <h2>{{ machine.config.name }}</h2>
        <p class="plant" :title="plantTitle">
          <AppIcon :name="hasCollector ? 'collector' : 'tube'" :size="14" />
          {{ hasCollector ? t("type.collector") : plantTitle }}
        </p>
      </div>
      <RouterLink
        class="icon-button"
        :to="`/machines/${machine.id}`"
        :title="t('card.settings')"
        :aria-label="t('card.settings')"
      >
        <AppIcon name="edit" :size="19" />
      </RouterLink>
    </header>

    <div class="chips">
      <span v-if="calibrating" class="chip on pulse">
        <AppIcon name="pump" :size="12" /> {{ t("calib.chip_running") }}
      </span>
      <span v-else-if="status.busy" class="chip on pulse">
        <AppIcon name="droplet" :size="12" /> {{ t("card.watering") }}
      </span>
      <RouterLink
        v-if="needsCalibration && !calibrating"
        :to="`/machines/${machine.id}/calibrate`"
        class="chip warn"
      >
        <AppIcon name="alert" :size="12" /> {{ t("calib.chip_needed") }}
      </RouterLink>
      <RouterLink
        v-else-if="calibrationDue && !calibrating"
        :to="`/machines/${machine.id}/calibrate`"
        class="chip warn"
      >
        <AppIcon name="clock" :size="12" /> {{ t("calib.chip_due") }}
      </RouterLink>
      <span v-if="waiting" class="chip">
        <AppIcon name="clock" :size="12" />
        {{
          waiting.position
            ? t("card.queue_position", { position: waiting.position })
            : t("card.queued")
        }}
      </span>
      <span class="chip" :class="pumpChip.cls">
        <AppIcon name="pump" :size="12" /> {{ pumpChip.text }}
      </span>
      <RouterLink
        v-if="machineBlockers.length"
        to="/problems"
        class="chip danger"
        :title="blockedText"
      >
        <AppIcon name="alert" :size="12" /> {{ t("card.blocked") }}
      </RouterLink>
    </div>

    <ul v-if="machineBlockers.length" class="blocked small">
      <li v-for="blocker in machineBlockers" :key="blocker.kind + blocker.target">
        {{ problemText(blocker) }}
      </li>
    </ul>

    <div v-if="staleRoutes.length && !calibrating" class="suggestion small">
      <p>{{ t("calib.stale_card", { plants: staleRoutes.map(plantName).join(", ") }) }}</p>
      <div class="row">
        <RouterLink class="button primary" :to="`/machines/${machine.id}/calibrate?route=${staleRoutes[0]}`">
          {{ t("calib.recalibrate") }}
        </RouterLink>
        <button v-for="routeId in staleRoutes" :key="routeId" @click="keepCalibration(routeId)">
          {{ staleRoutes.length > 1 ? t("calib.keep_for", { plant: plantName(routeId) }) : t("calib.keep") }}
        </button>
      </div>
    </div>

    <div v-if="suggestion" class="suggestion small">
      <p>{{ suggestionText }}</p>
      <div class="row">
        <button class="primary" @click="resolveSuggestion(true)">{{ t("calib.suggest_apply") }}</button>
        <button @click="resolveSuggestion(false)">{{ t("calib.suggest_dismiss") }}</button>
      </div>
    </div>

    <TankGauge :tank="status.tank" />

    <ul v-if="hasCollector" class="plants">
      <li v-for="plant in plants" :key="plant.id">
        <AppIcon name="plant" :size="14" />
        <span class="plant-name">{{ plant.name }}</span>
        <span v-if="blockedPlants.has(plant.id)" class="plant-blocked" :title="t('card.blocked')">
          <AppIcon name="alert" :size="14" />
        </span>
        <span
          class="dot"
          :class="{ open: plant.valve === 'open', unknown: plant.valve === 'unknown' }"
          :title="plant.valve"
        />
      </li>
    </ul>

    <p v-if="status.last_watering" class="last small">
      <AppIcon name="clock" :size="14" />
      <span class="muted">{{ t("card.last") }}</span>
      {{ time(status.last_watering.started_at) }}, {{ ml(status.last_watering.dose_ml) }}
      <span v-if="status.last_watering.ok" class="chip on">{{ t("card.ok") }}</span>
      <span v-else class="chip danger" :title="humanError(status.last_watering.error)">
        {{ t("card.error") }}
      </span>
    </p>

    <p class="last small">
      <AppIcon name="clock" :size="14" />
      <span class="muted">{{ t("card.next") }}</span>
      <template v-if="nextRun">{{ time(nextRun) }}</template>
      <span v-else class="muted">{{ t("card.no_schedule") }}</span>
    </p>

    <div v-if="error" class="error">{{ error }}</div>

    <footer class="actions">
      <button
        class="primary"
        :disabled="status.busy || machineBlockers.length > 0"
        :title="machineBlockers.length ? blockedText : undefined"
        @click="showWater = true"
      >
        <AppIcon name="droplet" />{{ t("card.water") }}
      </button>
      <button @click="showTank = true"><AppIcon name="refill" />{{ t("card.tank") }}</button>
      <button @click="showSchedule = true">
        <AppIcon name="clock" />{{ t("card.schedule") }}
      </button>
      <RouterLink
        class="button"
        :to="`/machines/${machine.id}/calibrate`"
        :title="t('calib.title')"
      >
        <AppIcon name="pump" />{{ t("calib.button") }}
      </RouterLink>
      <button :title="t('copy.button_hint')" @click="showCopy = true">
        <AppIcon name="plus" />{{ t("copy.button") }}
      </button>
      <span class="spacer" />
      <button class="danger" :class="{ solid: status.busy }" @click="stop">
        <AppIcon name="stop" :size="16" />{{ t("card.stop") }}
      </button>
    </footer>

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
    <CopyMachineDialog
      v-if="showCopy"
      :machine="machine"
      @close="showCopy = false"
      @changed="emit('changed')"
    />
    <ScheduleDialog
      v-if="showSchedule"
      :machine="machine"
      @close="showSchedule = false"
      @changed="emit('changed')"
    />
  </article>
</template>

<style scoped>
.machine {
  display: flex;
  flex-direction: column;
  gap: 12px;
  border-top: 3px solid var(--accent-plant);
  transition: box-shadow 0.2s;
}

.machine.busy {
  border-top-color: var(--primary);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary) 40%, transparent);
}

.head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  color: var(--accent-plant);
  background: color-mix(in srgb, var(--accent-plant) 14%, transparent);
  flex: none;
}

.titles {
  flex: 1;
  min-width: 0;
}

.plant {
  margin: 2px 0 0;
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--muted);
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.pulse {
  animation: pulse 1.6s ease-in-out infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.55;
  }
}

.plants {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 14px;
}

.plants li {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
}

.plant-name {
  color: var(--text);
  flex: 1;
}

a.chip {
  text-decoration: none;
}

.blocked {
  margin: 0;
  padding-left: 18px;
  color: var(--danger);
}

.plant-blocked {
  display: inline-flex;
  color: var(--danger);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--reserve);
}

.dot.open {
  background: var(--ok);
}

.dot.unknown {
  background: var(--danger);
}

.last {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 0;
  color: var(--muted);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.spacer {
  flex: 1;
}

.suggestion {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--warn) 50%, transparent);
  background: color-mix(in srgb, var(--warn) 10%, transparent);
}

.suggestion p {
  margin: 0 0 8px;
}
</style>
