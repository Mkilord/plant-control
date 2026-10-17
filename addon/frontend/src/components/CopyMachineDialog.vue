<script setup lang="ts">
// Копия машины: те же справочники, трубки, растения и калибровка, но свои реле.
// Можно сделать несколько копий за раз.
import { computed, onMounted, ref, watch } from "vue";
import { api, errorText, type HaEntity, type Machine } from "../api";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import EntitySelect from "./EntitySelect.vue";
import FormField from "./FormField.vue";
import ModalDialog from "./ModalDialog.vue";
import NumField from "./NumField.vue";

const props = defineProps<{ machine: Machine }>();
const emit = defineEmits<{ close: []; changed: [] }>();

interface Draft {
  name: string;
  pump: string;
  valves: Record<string, string>;
  done: boolean;
}

const count = ref(1);
const drafts = ref<Draft[]>([]);
const entities = ref<HaEntity[]>([]);
// Реле существующих машин: entity_id -> имя машины.
const existing = ref<Map<string, string>>(new Map());
const busy = ref(false);
const error = ref("");

const valveRoutes = computed(() => props.machine.config.routes.filter((route) => route.valve_entity_id));

function draft(index: number): Draft {
  return {
    name: `${props.machine.config.name} ${index + 2}`,
    pump: "",
    valves: Object.fromEntries(valveRoutes.value.map((route) => [route.id, ""])),
    done: false,
  };
}

watch(
  count,
  (value) => {
    const n = Math.max(1, Math.min(20, Math.round(value || 1)));
    while (drafts.value.length < n) drafts.value.push(draft(drafts.value.length));
    drafts.value.splice(n);
  },
  { immediate: true },
);

onMounted(() => {
  api
    .haEntities()
    .then((list) => (entities.value = list))
    .catch(() => undefined);
  api
    .listMachines()
    .then((machines) => {
      const taken = new Map<string, string>();
      for (const machine of machines) {
        taken.set(machine.config.pump.entity_id, machine.config.name);
        for (const route of machine.config.routes) {
          if (route.valve_entity_id) taken.set(route.valve_entity_id, machine.config.name);
        }
      }
      existing.value = taken;
    })
    .catch(() => undefined);
});

// Занятые реле для поля копии: чужие машины и реле, уже выбранные в других копиях.
function takenFor(index: number): Map<string, string> {
  const taken = new Map(existing.value);
  drafts.value.forEach((item, other) => {
    if (other === index) return;
    for (const entity of [item.pump, ...Object.values(item.valves)]) {
      if (entity) taken.set(entity, item.name);
    }
  });
  return taken;
}

async function copy() {
  error.value = "";
  busy.value = true;
  try {
    for (const item of drafts.value) {
      if (item.done) continue;
      await api.copyMachine(props.machine.id, item.name, item.pump, item.valves);
      item.done = true;
    }
    emit("changed");
    emit("close");
  } catch (e) {
    error.value = errorText(e);
    emit("changed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <ModalDialog :title="t('copy.title', { name: machine.config.name })" @close="emit('close')">
    <form class="stack" @submit.prevent="copy">
      <p class="note">
        <AppIcon name="info" />
        <span>{{ t("copy.hint") }}</span>
      </p>
      <NumField v-model="count" :label="t('copy.count')" :min="1" :max="20" />

      <fieldset v-for="(item, index) in drafts" :key="index" class="copy" :disabled="item.done">
        <legend>
          {{ t("copy.n", { n: index + 1 }) }}
          <span v-if="item.done" class="chip on">{{ t("copy.done") }}</span>
        </legend>
        <FormField v-slot="{ id }" :label="t('general.name')">
          <input :id="id" v-model="item.name" required maxlength="100" />
        </FormField>
        <FormField v-slot="{ id }" :label="t('pump.entity')">
          <EntitySelect
            :id="id"
            v-model="item.pump"
            :entities="entities"
            :taken="takenFor(index)"
            required
            placeholder="switch.pump_2"
          />
        </FormField>
        <FormField v-for="route in valveRoutes" :key="route.id" v-slot="{ id }" :label="t('copy.valve', { plant: route.name || route.id })">
          <EntitySelect
            :id="id"
            v-model="item.valves[route.id]"
            :entities="entities"
            :taken="takenFor(index)"
            required
            placeholder="switch.valve_1"
          />
        </FormField>
      </fieldset>

      <div v-if="error" class="error">{{ error }}</div>
      <div class="row">
        <button type="submit" class="primary" :disabled="busy">
          <AppIcon name="plus" />{{ t("copy.submit", { n: drafts.length }) }}
        </button>
        <button type="button" class="ghost" @click="emit('close')">{{ t("form.cancel") }}</button>
      </div>
    </form>
  </ModalDialog>
</template>

<style scoped>
.stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.copy {
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  margin: 0;
  min-width: 0;
}

legend {
  font-weight: 600;
  padding: 0 4px;
}

:deep(.dialog) {
  max-height: calc(100vh - 32px);
  overflow-y: auto;
}
</style>
