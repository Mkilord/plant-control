<script setup lang="ts">
// Мастер калибровки насоса. Работает и на телефоне у ёмкости, и на ПК.
// Пока страница открыта, раз в секунду уходит heartbeat: без него сервер
// выключит насос (страницу закрыли, пропала связь).
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  api,
  ApiError,
  errorText,
  type CalibrationMethod,
  type CalibrationResult,
  type CalibrationRun,
  type CalibrationSession,
  type Machine,
} from "../api";
import AppIcon from "../components/AppIcon.vue";
import CalibrationHistory from "../components/CalibrationHistory.vue";
import FormField from "../components/FormField.vue";
import NumField from "../components/NumField.vue";
import { ml, seconds } from "../format";
import { hasMessage, t } from "../i18n";

const props = defineProps<{ id: string }>();
const router = useRouter();
const route = useRoute();

const machine = ref<Machine | null>(null);
const session = ref<CalibrationSession | null>(null);
const error = ref("");
const busy = ref(false);
const loading = ref(true);

// --- Подготовка ---

const routeId = ref("");
const method = ref<CalibrationMethod>("marks");
const totalMl = ref(1500);
const markCount = ref(3);
const customMarks = ref(false);
const marksText = ref("500, 1000, 1500");
const durationsText = ref("10, 30");

function parseList(text: string): number[] {
  return text
    .split(/[\s;,]+/)
    .map((part) => Number(part.replace(",", ".")))
    .filter((n) => Number.isFinite(n) && n > 0);
}

const marks = computed(() => {
  if (customMarks.value) return [...new Set(parseList(marksText.value))].sort((a, b) => a - b);
  const count = Math.max(1, Math.min(10, Math.round(markCount.value)));
  return Array.from({ length: count }, (_, i) => Math.round((totalMl.value * (i + 1)) / count));
});

const durations = computed(() => parseList(durationsText.value));
// Предел прогона: предел насоса, а если он выключен - 10 минут, как на сервере.
const UNLIMITED_PUMP_RUN_S = 600;
const maxRuntime = computed(() => machine.value?.setup.pump.max_runtime_s ?? UNLIMITED_PUMP_RUN_S);
const routes = computed(() => machine.value?.config.routes ?? []);

function plantName(id: string): string {
  const found = routes.value.find((r) => r.id === id);
  return found?.name || id;
}

// --- Сессия ---

const state = computed(() => session.value?.state ?? "ready");
const currentRun = computed<CalibrationRun | null>(() => {
  const runs = session.value?.runs ?? [];
  return runs.length ? runs[runs.length - 1] : null;
});

// Время прогона по меткам считает клиент: от ответа сервера на "Старт".
const startedAt = ref<number | null>(null);
const nowMs = ref(performance.now());
const elapsed = computed(() =>
  startedAt.value === null ? 0 : Math.max(0, (nowMs.value - startedAt.value) / 1000),
);

const nextTarget = computed(() => {
  const s = session.value;
  const run = currentRun.value;
  if (!s || !run || s.method !== "marks") return null;
  return s.targets[run.marks.length] ?? null;
});

const waterStarted = computed(
  () => !!currentRun.value && (currentRun.value.water_started_s !== null || currentRun.value.marks.length > 0),
);

// Следующий прогон по времени: первая длительность, которой ещё не было.
const nextDuration = ref(10);
function pickNextDuration() {
  const done = new Set(
    (session.value?.runs ?? []).filter((r) => r.completed).map((r) => r.planned_s),
  );
  nextDuration.value = durations.value.find((d) => !done.has(d)) ?? durations.value[0] ?? 10;
}

const deadlineText = computed(() => {
  const s = session.value;
  if (!s || s.deadline_in_s === null) return "";
  return t("calib.autostop_in", { time: seconds(s.deadline_in_s) });
});

const volume = ref(0);
const saveMode = ref<"replace" | "second_level">("replace");
const makeBase = ref(false);

const hasCollector = computed(() => machine.value?.config.plumbing.type === "collector");
const isBase = computed(() => {
  const config = machine.value?.config;
  if (!config || !session.value) return true;
  return config.base_route === null || config.base_route === session.value.route_id;
});

// --- Загрузка ---

let heartbeat: number | undefined;
let ticker: number | undefined;
// Запрос действия в пути: ответ heartbeat в это время мог бы откатить состояние.
let acting = 0;

onMounted(async () => {
  try {
    machine.value = await api.getMachine(props.id);
    const requested = typeof route.query.route === "string" ? route.query.route : "";
    const firstUncalibrated = machine.value.status.flows.find((f) => f.source === "none" || f.stale);
    routeId.value =
      requested || firstUncalibrated?.route_id || machine.value.config.routes[0]?.id || "";
    const open = machine.value.status.calibration_session;
    if (open) {
      apply(await api.calibration(open));
      if (session.value?.state === "running" && session.value.elapsed_s !== null) {
        startedAt.value = performance.now() - session.value.elapsed_s * 1000;
      }
    }
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
  heartbeat = window.setInterval(beat, 1000);
  ticker = window.setInterval(() => (nowMs.value = performance.now()), 100);
});

onBeforeUnmount(() => {
  window.clearInterval(heartbeat);
  window.clearInterval(ticker);
  // Ушли со страницы посреди прогона: не ждать, пока сработает heartbeat.
  if (session.value?.state === "running") {
    api.calibrationStop(session.value.id).catch(() => undefined);
  }
});

async function beat() {
  const s = session.value;
  if (!s || acting) return;
  try {
    const fresh = await api.calibrationHeartbeat(s.id);
    if (!acting) apply(fresh);
  } catch (e) {
    // Сессию закрыли (аварийный стоп, долго не было связи).
    if (e instanceof ApiError && e.status === 404) {
      session.value = null;
      error.value = t("calib.session_lost");
    }
  }
}

function apply(next: CalibrationSession) {
  const wasRunning = session.value?.state === "running";
  session.value = next;
  if (next.state !== "running") startedAt.value = null;
  if (wasRunning && next.state === "awaiting_volume") {
    const run = currentRun.value;
    volume.value = run?.marks.length ? run.marks[run.marks.length - 1][1] : 0;
  }
  if (next.state === "ready") pickNextDuration();
  if (!next.has_calibration) saveMode.value = "replace";
}

async function act(action: () => Promise<CalibrationSession | void>) {
  error.value = "";
  busy.value = true;
  acting++;
  try {
    const result = await action();
    if (result) apply(result);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    acting--;
    busy.value = false;
  }
}

// --- Действия ---

function begin() {
  return act(async () => {
    const targets = method.value === "marks" ? marks.value : [];
    if (method.value === "timed") {
      const tooLong = durations.value.find((d) => d > maxRuntime.value);
      if (!durations.value.length) throw new Error(t("calib.need_durations"));
      if (tooLong) throw new Error(t("calib.too_long", { max: maxRuntime.value }));
    } else if (!targets.length) {
      throw new Error(t("calib.need_marks"));
    }
    const opened = await api.openCalibration(props.id, routeId.value, method.value, targets);
    makeBase.value = false;
    return opened;
  });
}

function startMarks() {
  return act(async () => {
    const s = session.value!;
    const result = await api.calibrationStart(s.id);
    startedAt.value = performance.now();
    return result;
  });
}

function startTimed() {
  return act(async () => {
    const s = session.value!;
    const result = await api.calibrationRun(s.id, nextDuration.value);
    startedAt.value = performance.now();
    return result;
  });
}

function mark(volumeMl: number) {
  const t0 = startedAt.value;
  if (t0 === null || !session.value) return;
  // Время берём в момент нажатия, до запроса.
  const at = (performance.now() - t0) / 1000;
  return act(() => api.calibrationMark(session.value!.id, at, volumeMl));
}

function stop() {
  return act(() => api.calibrationStop(session.value!.id));
}

function submitVolume() {
  return act(() => api.calibrationVolume(session.value!.id, volume.value));
}

function skipVolume() {
  return act(() => api.calibrationSkipVolume(session.value!.id));
}

function toggleRun(run: CalibrationRun) {
  return act(() => api.calibrationExclude(session.value!.id, run.index, !run.excluded));
}

async function save() {
  const s = session.value;
  if (!s) return;
  await act(async () => {
    await api.calibrationSave(s.id, saveMode.value, makeBase.value);
    session.value = null;
    await router.push("/");
  });
}

async function cancel() {
  const s = session.value;
  if (s) {
    await act(async () => {
      await api.calibrationClose(s.id);
      session.value = null;
    });
  }
  await router.push("/");
}

// --- Показ ---

function flowText(result: CalibrationResult): string {
  const lh = (result.flow_ml_s * 3.6).toFixed(1);
  return `${result.flow_ml_s.toFixed(2)} ${t("unit.ml_s")} (${lh} ${t("unit.l_h")})`;
}

function warningText(code: string): string {
  const key = `calib.warning.${code}`;
  return hasMessage(key) ? t(key) : code;
}

function stopText(code: string | null): string {
  if (!code) return "";
  const key = `calib.stop.${code}`;
  return hasMessage(key) ? t(key) : code;
}

const runCompleted = computed(() => {
  const reason = currentRun.value?.stop_reason;
  return reason === "last_mark" || reason === "timer";
});

const timer = computed(() => {
  const value = elapsed.value;
  const minutes = Math.floor(value / 60);
  const secs = (value % 60).toFixed(1);
  return minutes ? `${minutes}:${secs.padStart(4, "0")}` : secs;
});
</script>

<template>
  <div class="page calib">
    <div class="toolbar">
      <RouterLink to="/" class="button"><AppIcon name="back" />{{ t("form.back") }}</RouterLink>
      <h1>{{ t("calib.title") }}<template v-if="machine">: {{ machine.config.name }}</template></h1>
    </div>

    <p v-if="loading" class="muted">{{ t("form.loading") }}</p>

    <template v-else-if="machine">
      <!-- Подготовка -->
      <section v-if="!session" class="card step">
        <h2>{{ t("calib.setup") }}</h2>
        <div class="fields">
          <FormField v-if="routes.length > 1" v-slot="{ id }" :label="t('calib.plant')">
            <select :id="id" v-model="routeId">
              <option v-for="r in routes" :key="r.id" :value="r.id">{{ r.name || r.id }}</option>
            </select>
          </FormField>
        </div>

        <div class="methods" role="radiogroup">
          <label class="method" :class="{ active: method === 'marks' }">
            <input v-model="method" type="radio" value="marks" />
            <strong>{{ t("calib.method_marks") }}</strong>
            <span class="muted small">{{ t("calib.method_marks_hint") }}</span>
          </label>
          <label class="method" :class="{ active: method === 'timed' }">
            <input v-model="method" type="radio" value="timed" />
            <strong>{{ t("calib.method_timed") }}</strong>
            <span class="muted small">{{ t("calib.method_timed_hint") }}</span>
          </label>
        </div>

        <template v-if="method === 'marks'">
          <div class="fields">
            <template v-if="!customMarks">
              <NumField
                v-model="totalMl"
                :label="t('calib.total')"
                :unit="t('unit.ml')"
                :hint="t('calib.total_hint')"
                :min="1"
              />
              <NumField
                v-model="markCount"
                :label="t('calib.count')"
                :hint="t('calib.count_hint')"
                :min="1"
                :max="10"
              />
            </template>
            <FormField v-else v-slot="{ id }" class="wide" :label="t('calib.marks_list')">
              <input :id="id" v-model="marksText" inputmode="decimal" />
            </FormField>
          </div>
          <label class="check">
            <input v-model="customMarks" type="checkbox" />
            <span>{{ t("calib.custom_marks") }}</span>
          </label>
          <p class="small">
            {{ t("calib.marks_preview") }}
            <span v-for="m in marks" :key="m" class="chip">{{ ml(m) }}</span>
          </p>
        </template>
        <template v-else>
          <div class="fields">
            <FormField
              v-slot="{ id }"
              class="wide"
              :label="t('calib.durations')"
              :hint="t('calib.durations_hint')"
            >
              <input :id="id" v-model="durationsText" inputmode="decimal" />
            </FormField>
          </div>
        </template>

        <p v-if="machine.config.flow_mode === 'advanced'" class="note">
          <AppIcon name="info" />
          <span>{{ t("calib.switch_hint") }}</span>
        </p>
        <ul class="tips small">
          <li>{{ t("calib.tip_outlet") }}</li>
          <li>{{ t("calib.tip_duration") }}</li>
          <li>{{ t("calib.tip_limit", { max: maxRuntime }) }}</li>
          <li v-if="method === 'timed'">{{ t("calib.tip_scale") }}</li>
        </ul>

        <div v-if="error" class="error">{{ error }}</div>
        <div class="row">
          <button class="primary big" :disabled="busy || !routeId" @click="begin">
            <AppIcon name="play" />{{ t("calib.begin") }}
          </button>
        </div>
      </section>

      <CalibrationHistory v-if="!session" :machine="machine" />

      <template v-else>
        <p class="muted">
          {{ plantName(session.route_id) }} ·
          {{ session.method === "marks" ? t("calib.method_marks") : t("calib.method_timed") }}
        </p>

        <!-- Прогон -->
        <section class="card step run">
          <template v-if="state === 'ready'">
            <h2>{{ t("calib.run_n", { n: session.runs.length + 1 }) }}</h2>
            <template v-if="session.method === 'marks'">
              <p>{{ t("calib.ready_marks") }}</p>
              <p class="small">
                <span v-for="m in session.targets" :key="m" class="chip">{{ ml(m) }}</span>
              </p>
              <button class="primary big" :disabled="busy" @click="startMarks">
                <AppIcon name="play" />{{ busy ? t("calib.starting") : t("calib.start_pump") }}
              </button>
            </template>
            <template v-else>
              <p>{{ t("calib.ready_timed") }}</p>
              <div class="fields">
                <NumField
                  v-model="nextDuration"
                  :label="t('calib.run_for')"
                  :unit="t('unit.s')"
                  :min="1"
                  :max="maxRuntime"
                />
              </div>
              <button class="primary big" :disabled="busy" @click="startTimed">
                <AppIcon name="play" />{{
                  busy ? t("calib.starting") : t("calib.run_for_n", { n: nextDuration })
                }}
              </button>
            </template>
          </template>

          <template v-else-if="state === 'running'">
            <div class="timer" aria-live="off">{{ timer }}</div>
            <p class="muted small center">{{ deadlineText }}</p>
            <template v-if="session.method === 'marks'">
              <button
                v-if="!waterStarted"
                class="big"
                :disabled="busy"
                @click="mark(0)"
              >
                <AppIcon name="droplet" />{{ t("calib.water_started") }}
              </button>
              <button
                v-if="nextTarget !== null"
                class="primary huge"
                @click="mark(nextTarget)"
              >
                {{ t("calib.reached", { volume: ml(nextTarget) }) }}
              </button>
              <p class="muted small center">{{ t("calib.press_hint") }}</p>
            </template>
            <p v-else class="center">{{ t("calib.timed_running", { n: currentRun?.planned_s ?? 0 }) }}</p>
            <button class="danger solid big" @click="stop">
              <AppIcon name="stop" />{{ t("card.stop") }}
            </button>
          </template>

          <template v-else-if="state === 'awaiting_volume'">
            <template v-if="runCompleted">
              <h2>{{ t("calib.volume_title") }}</h2>
              <p>{{ t("calib.volume_hint") }}</p>
              <div class="fields">
                <NumField v-model="volume" :label="t('calib.volume')" :unit="t('unit.ml')" :min="0" />
              </div>
              <button class="primary big" :disabled="busy" @click="submitVolume">
                <AppIcon name="check" />{{ t("calib.volume_done") }}
              </button>
            </template>
            <template v-else>
              <h2>{{ t("calib.aborted", { reason: stopText(currentRun?.stop_reason ?? null) }) }}</h2>
              <p>{{ t("calib.aborted_hint") }}</p>
              <div class="fields">
                <NumField v-model="volume" :label="t('calib.volume')" :unit="t('unit.ml')" :min="0" />
              </div>
              <div class="row">
                <button :disabled="busy" @click="submitVolume">{{ t("calib.draw") }}</button>
                <button :disabled="busy" @click="skipVolume">{{ t("calib.skip") }}</button>
              </div>
            </template>
          </template>

          <div v-if="error" class="error">{{ error }}</div>
        </section>

        <!-- Прогоны -->
        <section v-if="session.runs.length" class="card step">
          <h2>{{ t("calib.runs") }}</h2>
          <ul class="runs">
            <li v-for="run in session.runs" :key="run.index" :class="{ excluded: run.excluded }">
              <div class="run-head">
                <strong>#{{ run.index }}</strong>
                <span v-if="run.stopped_after_s !== null" class="muted small">
                  {{ seconds(run.stopped_after_s) }}
                </span>
                <span v-if="run.volume_ml !== null" class="muted small">{{ ml(run.volume_ml) }}</span>
                <span class="spacer" />
                <label v-if="run.completed" class="check small">
                  <input type="checkbox" :checked="!run.excluded" @change="toggleRun(run)" />
                  {{ t("calib.use_run") }}
                </label>
                <span
                  v-else-if="run.stop_reason && !['last_mark', 'timer'].includes(run.stop_reason)"
                  class="chip warn"
                >{{ stopText(run.stop_reason) }}</span>
              </div>
              <p v-if="run.result" class="small">
                {{ flowText(run.result) }} · {{ t("calib.prime") }} {{ seconds(run.result.prime_s) }}
                <template v-if="session.method === 'marks'">
                  · {{ t("calib.afterflow") }} {{ ml(run.result.afterflow_ml) }}
                </template>
              </p>
              <p v-if="run.error" class="error small">{{ run.error }}</p>
            </li>
          </ul>
        </section>

        <!-- Итог -->
        <section v-if="session.result" class="card step">
          <h2>{{ t("calib.result") }}</h2>
          <table class="kv">
            <tbody>
              <tr>
                <td>{{ t("calib.flow") }}</td>
                <td>{{ flowText(session.result) }}</td>
              </tr>
              <tr>
                <td>{{ t("calib.prime") }}</td>
                <td>{{ seconds(session.result.prime_s) }}</td>
              </tr>
              <tr v-if="session.method === 'marks'">
                <td>{{ t("calib.afterflow") }}</td>
                <td>{{ ml(session.result.afterflow_ml) }}</td>
              </tr>
              <tr v-if="session.result.spread_pct !== null">
                <td>{{ t("calib.spread") }}</td>
                <td>{{ session.result.spread_pct.toFixed(1) }} %</td>
              </tr>
              <tr v-if="session.reference_volume_ml !== null">
                <td>{{ t("calib.tank_volume") }}</td>
                <td>{{ ml(session.reference_volume_ml) }}</td>
              </tr>
            </tbody>
          </table>
          <ul v-if="session.result.warnings.length" class="warnings small">
            <li v-for="w in session.result.warnings" :key="w">
              <AppIcon name="alert" :size="14" /> {{ warningText(w) }}
            </li>
          </ul>

          <fieldset v-if="session.has_calibration" class="save-mode">
            <legend>{{ t("calib.save_mode") }}</legend>
            <label class="check">
              <input v-model="saveMode" type="radio" value="replace" />
              {{ t("calib.save_replace") }}
            </label>
            <label class="check">
              <input
                v-model="saveMode"
                type="radio"
                value="second_level"
                :disabled="!session.second_level_possible"
              />
              {{ t("calib.save_second") }}
            </label>
            <p class="muted small">
              {{ session.second_level_possible ? t("calib.second_hint") : t("calib.second_unavailable") }}
            </p>
          </fieldset>
          <label v-if="hasCollector && !isBase" class="check">
            <input v-model="makeBase" type="checkbox" />
            {{ t("calib.make_base") }}
          </label>
          <p v-if="hasCollector" class="muted small">{{ t("calib.inherit_hint") }}</p>

          <div class="row">
            <button class="primary big" :disabled="busy || state !== 'ready'" @click="save">
              <AppIcon name="check" />{{ t("calib.save") }}
            </button>
          </div>
        </section>
        <p v-else-if="session.runs.some((r) => r.completed) && session.result_error" class="muted small">
          {{ session.result_error }}
        </p>

        <div class="row">
          <button class="danger" :disabled="busy" @click="cancel">
            <AppIcon name="trash" />{{ t("calib.cancel") }}
          </button>
        </div>
      </template>
    </template>
    <div v-else-if="error" class="error">{{ error }}</div>
  </div>
</template>

<style scoped>
.calib {
  max-width: 640px;
}

.step {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.step h2 {
  margin: 0;
}

.methods {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}

.method {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
}

.method.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}

.method input {
  align-self: flex-start;
}

.check {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.tips {
  margin: 0;
  padding-left: 18px;
  color: var(--muted);
}

.chip {
  margin-right: 4px;
}

.run {
  align-items: stretch;
}

button.big {
  min-height: 52px;
  font-size: 17px;
  justify-content: center;
}

button.huge {
  min-height: 120px;
  font-size: 26px;
  font-weight: 700;
  justify-content: center;
}

.timer {
  font-size: 56px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  text-align: center;
  line-height: 1.1;
}

.center {
  text-align: center;
  margin: 0;
}

.runs {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.runs li {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
}

.runs li.excluded {
  opacity: 0.55;
}

.runs p {
  margin: 4px 0 0;
}

.run-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.spacer {
  flex: 1;
}

.warnings {
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--warn);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.save-mode {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.save-mode p {
  margin: 0;
}
</style>
