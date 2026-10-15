<script setup lang="ts">
// Раздел настроек калибровки: напоминание о повторной калибровке и автоподстройка.
// Пороги мастера видны только в расширенных настройках.
import { computed, onMounted, ref } from "vue";
import { api, errorText, type CalibrationSettings } from "../api";
import { t } from "../i18n";
import FormSection from "./FormSection.vue";
import NumField from "./NumField.vue";

defineProps<{ advanced: boolean }>();

const form = ref<CalibrationSettings | null>(null);
const snapshot = ref("");
const error = ref("");

function accept(value: CalibrationSettings) {
  form.value = { ...value };
  snapshot.value = JSON.stringify(form.value);
}

onMounted(async () => {
  try {
    accept(await api.calibrationSettings());
  } catch (e) {
    error.value = errorText(e);
  }
});

const dirty = computed(() => form.value !== null && JSON.stringify(form.value) !== snapshot.value);

const reminder = computed({
  get: () => form.value?.reminder_weeks !== null && form.value?.reminder_weeks !== undefined,
  set: (on: boolean) => {
    if (form.value) form.value.reminder_weeks = on ? 8 : null;
  },
});

const weeks = computed({
  get: () => form.value?.reminder_weeks ?? 8,
  set: (value: number) => {
    if (form.value) form.value.reminder_weeks = Math.max(1, Math.round(value));
  },
});

async function save(): Promise<void> {
  if (!form.value || !dirty.value) return;
  accept(await api.saveCalibrationSettings(form.value));
}

defineExpose({ save, dirty });
</script>

<template>
  <FormSection
    :title="t('calib.settings_title')"
    icon="pump"
    accent="var(--accent-pump)"
    :description="t('calib.settings_desc')"
  >
    <div v-if="error" class="error">{{ error }}</div>
    <template v-if="form">
      <label class="check">
        <input v-model="reminder" type="checkbox" />
        {{ t("calib.reminder") }}
      </label>
      <div class="fields sub">
        <NumField
          v-if="reminder"
          v-model="weeks"
          :label="t('calib.reminder_weeks')"
          :hint="t('calib.reminder_hint')"
          :min="1"
        />
        <NumField
          v-model="form.tune_deviation_pct"
          :label="t('calib.tune_deviation')"
          :unit="t('unit.percent')"
          :hint="t('calib.tune_deviation_hint')"
          :min="1"
        />
        <NumField
          v-model="form.tune_min_waterings"
          :label="t('calib.tune_min')"
          :hint="t('calib.tune_min_hint')"
          :min="1"
        />
        <template v-if="advanced">
          <NumField
            v-model="form.min_duration_s"
            :label="t('calib.min_duration')"
            :unit="t('unit.s')"
            :hint="t('calib.min_duration_hint')"
            :min="0"
          />
          <NumField
            v-model="form.max_spread_pct"
            :label="t('calib.max_spread')"
            :unit="t('unit.percent')"
            :min="0.1"
          />
          <NumField
            v-model="form.overtime_factor"
            :label="t('calib.overtime')"
            :hint="t('calib.overtime_hint')"
            :min="1.1"
          />
          <NumField
            v-model="form.heartbeat_timeout_s"
            :label="t('calib.heartbeat')"
            :unit="t('unit.s')"
            :hint="t('calib.heartbeat_hint')"
            :min="1"
          />
          <NumField
            v-model="form.second_level_min_pct"
            :label="t('calib.second_min')"
            :unit="t('unit.percent')"
            :hint="t('calib.second_min_hint')"
            :min="1"
            :max="100"
          />
        </template>
      </div>
    </template>
  </FormSection>
</template>

<style scoped>
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.sub {
  margin-top: 12px;
}
</style>
