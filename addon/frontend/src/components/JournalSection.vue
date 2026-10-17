<script setup lang="ts">
// Раздел настроек журналов: сколько хранить записи поливов, калибровок и проблем.
import { computed, onMounted, ref } from "vue";
import { api, errorText, type JournalSettings } from "../api";
import { t } from "../i18n";
import FormField from "./FormField.vue";
import FormSection from "./FormSection.vue";

const OPTIONS: (number | null)[] = [30, 90, 365, null];

const form = ref<JournalSettings | null>(null);
const snapshot = ref("");
const error = ref("");

function accept(value: JournalSettings) {
  form.value = { ...value };
  snapshot.value = JSON.stringify(form.value);
}

onMounted(async () => {
  try {
    accept(await api.journalSettings());
  } catch (e) {
    error.value = errorText(e);
  }
});

const dirty = computed(() => form.value !== null && JSON.stringify(form.value) !== snapshot.value);

// select не умеет null: "" значит "не ограничивать".
const keep = computed({
  get: () => (form.value?.keep_days == null ? "" : String(form.value.keep_days)),
  set: (value: string) => {
    if (form.value) form.value.keep_days = value ? Number(value) : null;
  },
});

function label(days: number | null): string {
  return days === null ? t("journal.keep_forever") : t("journal.keep_days", { days });
}

async function save(): Promise<void> {
  if (!form.value || !dirty.value) return;
  accept(await api.saveJournalSettings(form.value));
}

defineExpose({ save, dirty });
</script>

<template>
  <FormSection
    :title="t('journal.settings_title')"
    icon="history"
    accent="var(--accent-extra)"
    :description="t('journal.settings_desc')"
  >
    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="form" class="fields">
      <FormField v-slot="{ id }" :label="t('journal.keep')" :hint="t('journal.keep_hint')">
        <select :id="id" v-model="keep">
          <option v-for="days in OPTIONS" :key="String(days)" :value="days === null ? '' : String(days)">
            {{ label(days) }}
          </option>
        </select>
      </FormField>
    </div>
  </FormSection>
</template>
