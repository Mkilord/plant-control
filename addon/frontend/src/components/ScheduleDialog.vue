<script setup lang="ts">
// Расписание одного растения: из справочника (общее для многих растений) или своё.
import { computed, onMounted, ref, watch } from "vue";
import { api, errorText, type Machine, type Rule, type ScheduleConfig } from "../api";
import { clone, entriesOf, findEntry, loadCatalog, summary } from "../catalog";
import { ml, time } from "../format";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import FormField from "./FormField.vue";
import ModalDialog from "./ModalDialog.vue";
import NumField from "./NumField.vue";
import RuleFields from "./RuleFields.vue";

const props = defineProps<{ machine: Machine }>();
const emit = defineEmits<{ close: []; changed: [] }>();

const routeId = ref(props.machine.config.routes[0].id);
const mode = ref<"template" | "own">("template");
const template = ref("");
const enabled = ref(true);
const rule = ref<Rule>({ type: "weekly", days: [0, 3], times: ["08:00"] });
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
const templates = computed(() => entriesOf("schedule"));
const chosen = computed(() => findEntry("schedule", template.value));
const hasSchedule = computed(() => Boolean(route.value.schedule || route.value.schedule_link));

onMounted(async () => {
  await loadCatalog();
  if (!template.value) template.value = templates.value[0]?.id ?? "";
  if (!route.value.schedule && !route.value.schedule_link && !templates.value.length) mode.value = "own";
});

// Переключили растение - показываем его расписание.
watch(routeId, () => load(), { immediate: true });

function load() {
  const link = route.value.schedule_link;
  const saved = route.value.schedule;
  template.value = link?.template ?? templates.value[0]?.id ?? "";
  enabled.value = link?.enabled ?? saved?.enabled ?? true;
  mode.value = saved ? "own" : "template";
  rule.value = saved
    ? clone(saved.rule)
    : { type: "weekly", days: [0, 3], times: ["08:00"] };
  dose.value = saved?.dose_ml ?? null;
  seasonFactor.value = saved?.season_factor ?? 1;
  catchUpH.value = saved?.catch_up_h ?? 3;
  minGapH.value = saved?.min_gap_h ?? 6;
}

function setDose(event: Event) {
  const input = event.target as HTMLInputElement;
  dose.value = input.value === "" ? null : input.valueAsNumber;
}

async function save() {
  if (mode.value === "template") {
    if (!template.value) {
      error.value = t("schedule.need_template");
      return;
    }
    await run(() =>
      api.linkSchedule(props.machine.id, routeId.value, { template: template.value, enabled: enabled.value }),
    );
    return;
  }
  const times = rule.value.times.filter(Boolean);
  if (!times.length) {
    error.value = t("schedule.need_time");
    return;
  }
  if (rule.value.type === "weekly" && !rule.value.days.length) {
    error.value = t("schedule.need_day");
    return;
  }
  const config: ScheduleConfig = {
    enabled: enabled.value,
    rule: { ...rule.value, times },
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

    <div class="modes">
      <button type="button" :class="{ active: mode === 'template' }" @click="mode = 'template'">
        {{ t("schedule.mode_template") }}
      </button>
      <button type="button" :class="{ active: mode === 'own' }" @click="mode = 'own'">
        {{ t("schedule.mode_own") }}
      </button>
    </div>

    <template v-if="mode === 'template'">
      <FormField v-slot="{ id }" :label="t('schedule.template')">
        <select :id="id" v-model="template">
          <option value="" disabled>{{ templates.length ? t("picker.choose") : t("picker.empty") }}</option>
          <option v-for="entry in templates" :key="entry.id" :value="entry.id">{{ entry.item.name }}</option>
        </select>
      </FormField>
      <p v-if="chosen" class="muted small">
        {{ summary("schedule", chosen.item) }}.
        {{
          chosen.item.dose_ml
            ? t("schedule.template_dose", { dose: ml(chosen.item.dose_ml) })
            : t("schedule.plant_dose", { dose: ml(route.default_dose_ml) })
        }}
      </p>
      <RouterLink class="small" to="/catalog/schedule">{{ t("schedule.manage_templates") }}</RouterLink>
    </template>

    <template v-else>
    <RuleFields v-model="rule" />

    <FormField v-slot="{ id }" :label="t('schedule.dose')" :hint="t('schedule.dose_desc')">
      <span class="num">
        <input
          :id="id"
          type="number"
          step="any"
          min="1"
          :value="dose ?? ''"
          :placeholder="String(Math.round(route.default_dose_ml))"
          @input="setDose"
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
    </template>

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
      <button v-if="hasSchedule" class="danger" :disabled="busy" @click="remove">
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

.modes {
  display: flex;
  gap: 6px;
}

.modes button {
  flex: 1;
}

.modes button.active {
  background: var(--accent-tank);
  border-color: var(--accent-tank);
  color: #fff;
}
</style>
