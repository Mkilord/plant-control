<script setup lang="ts">
// Расписание одного растения: по дням недели или с интервалом в днях.
import { computed, ref, watch } from "vue";
import { api, errorText, type Machine, type Rule, type ScheduleConfig } from "../api";
import { time } from "../format";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import FormField from "./FormField.vue";
import ModalDialog from "./ModalDialog.vue";
import NumField from "./NumField.vue";

const props = defineProps<{ machine: Machine }>();
const emit = defineEmits<{ close: []; changed: [] }>();

// Ключи подписей дней: так проверка типов видит, что такие ключи в словаре есть.
const WEEKDAYS = [
  { day: 0, label: "weekday.0" },
  { day: 1, label: "weekday.1" },
  { day: 2, label: "weekday.2" },
  { day: 3, label: "weekday.3" },
  { day: 4, label: "weekday.4" },
  { day: 5, label: "weekday.5" },
  { day: 6, label: "weekday.6" },
] as const;

const routeId = ref(props.machine.config.routes[0].id);
const kind = ref<"weekly" | "interval">("weekly");
const enabled = ref(true);
const days = ref<number[]>([0, 3]);
const everyDays = ref(3);
const startDate = ref("");
const times = ref<string[]>(["08:00"]);
const dose = ref<number | null>(null);
const seasonFactor = ref(1);
const catchUpH = ref(3);
const minGapH = ref(6);
const error = ref("");
const busy = ref(false);

const route = computed(
  () => props.machine.config.routes.find((r) => r.id === routeId.value) ?? props.machine.config.routes[0],
);
const status = computed(() =>
  props.machine.status.schedules.find((s) => s.route_id === routeId.value),
);

// Переключили растение - показываем его расписание.
watch(routeId, () => load(), { immediate: true });

function load() {
  const saved = route.value.schedule;
  if (!saved) {
    kind.value = "weekly";
    enabled.value = true;
    days.value = [0, 3];
    times.value = ["08:00"];
    dose.value = null;
    seasonFactor.value = 1;
    catchUpH.value = 3;
    minGapH.value = 6;
    startDate.value = "";
    return;
  }
  enabled.value = saved.enabled;
  dose.value = saved.dose_ml;
  seasonFactor.value = saved.season_factor;
  catchUpH.value = saved.catch_up_h;
  minGapH.value = saved.min_gap_h;
  times.value = saved.rule.times.map(short);
  if (saved.rule.type === "weekly") {
    kind.value = "weekly";
    days.value = [...saved.rule.days];
  } else {
    kind.value = "interval";
    everyDays.value = saved.rule.every_days;
    startDate.value = saved.rule.start_date ?? "";
  }
}

// Бэкенд отдаёт "08:00:00", в поле времени нужно "08:00".
function short(value: string): string {
  return value.slice(0, 5);
}

function toggleDay(day: number) {
  days.value = days.value.includes(day)
    ? days.value.filter((d) => d !== day)
    : [...days.value, day].sort();
}

function rule(): Rule {
  const list = times.value.filter(Boolean);
  return kind.value === "weekly"
    ? { type: "weekly", days: [...days.value].sort(), times: list }
    : {
        type: "interval",
        every_days: everyDays.value,
        times: list,
        start_date: startDate.value || null,
      };
}

async function save() {
  if (!times.value.filter(Boolean).length) {
    error.value = t("schedule.need_time");
    return;
  }
  if (kind.value === "weekly" && !days.value.length) {
    error.value = t("schedule.need_day");
    return;
  }
  const config: ScheduleConfig = {
    enabled: enabled.value,
    rule: rule(),
    dose_ml: dose.value,
    season_factor: seasonFactor.value,
    catch_up_h: catchUpH.value,
    min_gap_h: minGapH.value,
  };
  await run(() => api.setSchedule(props.machine.id, routeId.value, config));
}

async function remove() {
  await run(() => api.clearSchedule(props.machine.id, routeId.value));
}

async function run(action: () => Promise<unknown>) {
  error.value = "";
  busy.value = true;
  try {
    await action();
    emit("changed");
    emit("close");
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <ModalDialog :title="t('schedule.title', { name: machine.config.name })" @close="emit('close')">
    <FormField v-if="machine.config.routes.length > 1" v-slot="{ id }" :label="t('schedule.plant')">
      <select :id="id" v-model="routeId">
        <option v-for="r in machine.config.routes" :key="r.id" :value="r.id">
          {{ r.name || r.id }}
        </option>
      </select>
    </FormField>

    <label class="check">
      <input v-model="enabled" type="checkbox" />
      {{ t("schedule.enabled") }}
    </label>

    <FormField v-slot="{ id }" :label="t('schedule.kind')">
      <select :id="id" v-model="kind">
        <option value="weekly">{{ t("schedule.weekly") }}</option>
        <option value="interval">{{ t("schedule.interval") }}</option>
      </select>
    </FormField>

    <FormField v-if="kind === 'weekly'" :label="t('schedule.days')">
      <div class="days">
        <button
          v-for="item in WEEKDAYS"
          :key="item.day"
          type="button"
          class="day"
          :class="{ active: days.includes(item.day) }"
          :aria-pressed="days.includes(item.day)"
          @click="toggleDay(item.day)"
        >
          {{ t(item.label) }}
        </button>
      </div>
    </FormField>

    <template v-else>
      <NumField
        v-model="everyDays"
        :label="t('schedule.every_days')"
        :unit="t('schedule.every_days_unit')"
        :min="1"
      />
      <FormField v-slot="{ id }" :label="t('schedule.start_date')" :hint="t('schedule.start_date_desc')">
        <input :id="id" v-model="startDate" type="date" />
      </FormField>
    </template>

    <FormField :label="t('schedule.times')" :hint="t('schedule.times_desc')">
      <div class="times">
        <span v-for="(_, index) in times" :key="index" class="time-row">
          <input v-model="times[index]" type="time" />
          <button
            v-if="times.length > 1"
            type="button"
            class="icon-button"
            :aria-label="t('queue.cancel')"
            @click="times.splice(index, 1)"
          >
            <AppIcon name="trash" :size="16" />
          </button>
        </span>
        <button type="button" class="ghost" @click="times.push('20:00')">
          <AppIcon name="plus" :size="14" />{{ t("schedule.add_time") }}
        </button>
      </div>
    </FormField>

    <FormField v-slot="{ id }" :label="t('schedule.dose')" :hint="t('schedule.dose_desc')">
      <span class="num">
        <input
          :id="id"
          type="number"
          step="any"
          min="1"
          :value="dose ?? ''"
          :placeholder="String(Math.round(route.default_dose_ml))"
          @input="dose = ($event.target as HTMLInputElement).value === '' ? null : ($event.target as HTMLInputElement).valueAsNumber"
        />
        <span class="unit">{{ t("unit.ml") }}</span>
      </span>
    </FormField>

    <NumField
      v-model="seasonFactor"
      :label="t('schedule.season')"
      :hint="t('schedule.season_desc')"
      :min="0.1"
    />
    <NumField
      v-model="catchUpH"
      :label="t('schedule.catch_up')"
      :hint="t('schedule.catch_up_desc')"
      :unit="t('schedule.unit_h')"
      :min="0"
    />
    <NumField
      v-model="minGapH"
      :label="t('schedule.min_gap')"
      :hint="t('schedule.min_gap_desc')"
      :unit="t('schedule.unit_h')"
      :min="0"
    />

    <p v-if="status" class="muted small">
      <AppIcon name="clock" :size="14" />
      {{ t("schedule.next") }}: {{ status.next_run_at ? time(status.next_run_at) : t("schedule.off") }}
    </p>

    <div v-if="error" class="error">{{ error }}</div>

    <div class="row">
      <button class="primary" :disabled="busy" @click="save">
        <AppIcon name="clock" />{{ t("schedule.save") }}
      </button>
      <span class="spacer" />
      <button v-if="route.schedule" class="danger" :disabled="busy" @click="remove">
        {{ t("schedule.remove") }}
      </button>
    </div>
  </ModalDialog>
</template>

<style scoped>
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

/* Общее правило растягивает поля на всю ширину, флажку это ни к чему. */
.check input {
  width: auto;
  flex: none;
}

.days {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.day {
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 13px;
}

.day.active {
  background: var(--accent-tank);
  border-color: var(--accent-tank);
  color: #fff;
}

.times {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.time-row {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>
