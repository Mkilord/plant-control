<script setup lang="ts">
// Поля расписания из справочника. Доза задана - она важнее дозы растения.
import type { ScheduleTemplate } from "../../api";
import { t } from "../../i18n";
import FormField from "../FormField.vue";
import NumField from "../NumField.vue";
import RuleFields from "../RuleFields.vue";

const schedule = defineModel<ScheduleTemplate>({ required: true });

function setDose(event: Event) {
  const input = event.target as HTMLInputElement;
  schedule.value.dose_ml = input.value === "" ? null : input.valueAsNumber;
}
</script>

<template>
  <div class="stack">
    <FormField v-slot="{ id }" :label="t('catalog.name')">
      <input
        :id="id"
        v-model="schedule.name"
        required
        maxlength="100"
        :placeholder="t('catalog.schedule_placeholder')"
      />
    </FormField>
    <RuleFields v-model="schedule.rule" />
    <FormField v-slot="{ id }" :label="t('schedule.dose')" :hint="t('catalog.schedule_dose_hint')">
      <span class="num">
        <input
          :id="id"
          type="number"
          step="any"
          min="1"
          :value="schedule.dose_ml ?? ''"
          :placeholder="t('catalog.schedule_dose_placeholder')"
          @input="setDose"
        />
        <span class="unit">{{ t("unit.ml") }}</span>
      </span>
    </FormField>
    <NumField v-model="schedule.season_factor" :label="t('schedule.season')" :hint="t('schedule.season_desc')" :min="0.1" />
    <NumField
      v-model="schedule.catch_up_h"
      :label="t('schedule.catch_up')"
      :hint="t('schedule.catch_up_desc')"
      :unit="t('schedule.unit_h')"
      :min="0"
    />
    <NumField
      v-model="schedule.min_gap_h"
      :label="t('schedule.min_gap')"
      :hint="t('schedule.min_gap_desc')"
      :unit="t('schedule.unit_h')"
      :min="0"
    />
  </div>
</template>

<style scoped>
.stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
</style>
