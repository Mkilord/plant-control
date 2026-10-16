<script setup lang="ts">
// Правило расписания: по дням недели или каждые N дней, плюс время полива.
// Общее для своего расписания растения и для расписания из справочника.
import { computed } from "vue";
import type { Rule } from "../api";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import FormField from "./FormField.vue";
import NumField from "./NumField.vue";

const rule = defineModel<Rule>({ required: true });

const WEEKDAYS = [
  { day: 0, label: "weekday.0" },
  { day: 1, label: "weekday.1" },
  { day: 2, label: "weekday.2" },
  { day: 3, label: "weekday.3" },
  { day: 4, label: "weekday.4" },
  { day: 5, label: "weekday.5" },
  { day: 6, label: "weekday.6" },
] as const;

const kind = computed({
  get: () => rule.value.type,
  set: (value: Rule["type"]) => {
    const times = rule.value.times;
    rule.value =
      value === "weekly"
        ? { type: "weekly", days: [0, 3], times }
        : { type: "interval", every_days: 3, times, start_date: null };
  },
});

const days = computed(() => (rule.value.type === "weekly" ? rule.value.days : []));

function toggleDay(day: number) {
  const current = rule.value;
  if (current.type !== "weekly") return;
  current.days = current.days.includes(day)
    ? current.days.filter((d) => d !== day)
    : [...current.days, day].sort();
}

const everyDays = computed({
  get: () => (rule.value.type === "interval" ? rule.value.every_days : 1),
  set: (value: number) => {
    if (rule.value.type === "interval") rule.value.every_days = Math.max(1, Math.round(value));
  },
});

const startDate = computed({
  get: () => (rule.value.type === "interval" ? (rule.value.start_date ?? "") : ""),
  set: (value: string) => {
    if (rule.value.type === "interval") rule.value.start_date = value || null;
  },
});

// Бэкенд отдаёт "08:00:00", в поле времени нужно "08:00".
function setTime(index: number, value: string) {
  rule.value.times[index] = value;
}
</script>

<template>
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
      <span v-for="(value, index) in rule.times" :key="index" class="time-row">
        <input
          :value="value.slice(0, 5)"
          type="time"
          @input="setTime(index, ($event.target as HTMLInputElement).value)"
        />
        <button
          v-if="rule.times.length > 1"
          type="button"
          class="icon-button"
          :aria-label="t('queue.cancel')"
          @click="rule.times.splice(index, 1)"
        >
          <AppIcon name="trash" :size="16" />
        </button>
      </span>
      <button type="button" class="ghost" @click="rule.times.push('20:00')">
        <AppIcon name="plus" :size="14" />{{ t("schedule.add_time") }}
      </button>
    </div>
  </FormField>
</template>

<style scoped>
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
