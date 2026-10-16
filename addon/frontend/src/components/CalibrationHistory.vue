<script setup lang="ts">
// Что сейчас действует у каждого растения и журнал прошлых калибровок машины.
import { computed, onMounted, ref } from "vue";
import { api, errorText, type CalibrationRecord, type Machine, type RouteFlowStatus } from "../api";
import { ml, seconds, time } from "../format";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";

const props = defineProps<{ machine: Machine }>();

const records = ref<CalibrationRecord[]>([]);
const error = ref("");
const shown = ref(10);

onMounted(async () => {
  try {
    records.value = await api.calibrationHistory(props.machine.id);
  } catch (e) {
    error.value = errorText(e);
  }
});

function plantName(routeId: string): string {
  const route = props.machine.config.routes.find((r) => r.id === routeId);
  return route?.name || routeId;
}

// Запись журнала, из которой взят действующий замер растения.
const activeIds = computed(
  () =>
    new Set(
      props.machine.config.routes
        .map((route) => route.calibration?.record_id)
        .filter((id): id is number => typeof id === "number"),
    ),
);

function flowLine(flow: RouteFlowStatus): string {
  if (flow.source === "advanced") return t("calib.hist.advanced");
  if (flow.source === "none" || !flow.flow_points.length) return t("calib.status_none");
  const points = flow.flow_points.map((p) => `${p.flow_ml_s.toFixed(1)} ${t("unit.ml_s")}`).join(" / ");
  return t("calib.hist.params", {
    flow: points,
    prime: seconds(flow.prime_s ?? 0),
    after: ml(flow.afterflow_ml ?? 0),
  });
}

function sourceLine(flow: RouteFlowStatus): string {
  if (flow.source === "inherited") return t("calib.hist.inherited", { plant: plantName(flow.inherited_from ?? "") });
  if (flow.source !== "own") return "";
  const parts = [flow.calibrated_at ? t("calib.hist.measured", { date: time(flow.calibrated_at) }) : ""];
  if (flow.copied_from) parts.push(t("calib.copied_from", { name: flow.copied_from }));
  return parts.filter(Boolean).join(", ");
}

interface ResultData {
  flow_ml_s?: number;
  prime_s?: number;
  afterflow_ml?: number;
  spread_pct?: number | null;
}

function result(record: CalibrationRecord): ResultData | null {
  const data = record.data as { result?: ResultData };
  return data.result ?? null;
}

function methodText(record: CalibrationRecord): string {
  switch (record.method) {
    case "marks":
      return t("calib.method_marks");
    case "timed":
      return t("calib.method_timed");
    case "accepted":
      return t("calib.hist.accepted");
    default:
      return record.method;
  }
}

function secondLevel(record: CalibrationRecord): boolean {
  return (record.data as { mode?: string }).mode === "second_level";
}
</script>

<template>
  <section class="card step">
    <h2>{{ t("calib.hist.now") }}</h2>
    <ul class="flows">
      <li v-for="flow in machine.status.flows" :key="flow.route_id">
        <div class="line">
          <strong>{{ plantName(flow.route_id) }}</strong>
          <span v-if="flow.stale" class="chip warn"><AppIcon name="alert" :size="12" /> {{ t("calib.stale") }}</span>
          <span v-else-if="flow.due" class="chip warn">{{ t("calib.chip_due") }}</span>
        </div>
        <span class="small">{{ flowLine(flow) }}</span>
        <span v-if="sourceLine(flow)" class="muted small">{{ sourceLine(flow) }}</span>
      </li>
    </ul>
  </section>

  <section class="card step">
    <h2>{{ t("calib.hist.title") }}</h2>
    <div v-if="error" class="error">{{ error }}</div>
    <p v-else-if="!records.length" class="muted small">{{ t("calib.hist.empty") }}</p>
    <ul class="records">
      <li v-for="record in records.slice(0, shown)" :key="record.id">
        <div class="line">
          <span class="muted small nowrap">{{ time(record.created_at) }}</span>
          <strong>{{ plantName(record.route_id) }}</strong>
          <span class="muted small">{{ methodText(record) }}</span>
          <span v-if="secondLevel(record)" class="chip">{{ t("calib.hist.second_level") }}</span>
          <span v-if="activeIds.has(record.id)" class="chip on">{{ t("calib.hist.active") }}</span>
        </div>
        <span v-if="result(record)" class="small">
          {{
            t("calib.hist.params", {
              flow: `${(result(record)?.flow_ml_s ?? 0).toFixed(1)} ${t("unit.ml_s")}`,
              prime: seconds(result(record)?.prime_s ?? 0),
              after: ml(result(record)?.afterflow_ml ?? 0),
            })
          }}
          <template v-if="result(record)?.spread_pct != null">
            · {{ t("calib.spread") }} {{ result(record)?.spread_pct?.toFixed(1) }}%
          </template>
        </span>
      </li>
    </ul>
    <button v-if="records.length > shown" class="ghost" @click="shown += 20">
      {{ t("waterings.more", { count: records.length - shown }) }}
    </button>
  </section>
</template>

<style scoped>
.flows,
.records {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.flows li,
.records li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 0;
  border-top: 1px solid var(--border);
}

.flows li:first-child,
.records li:first-child {
  border-top: none;
}

.line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.nowrap {
  white-space: nowrap;
}
</style>
