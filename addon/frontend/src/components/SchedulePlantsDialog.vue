<script setup lang="ts">
// Какие растения поливаются по общему расписанию: галочки по всем машинам сразу.
import { computed, ref } from "vue";
import { api, errorText, type Machine } from "../api";
import { itemName } from "../catalog";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import ModalDialog from "./ModalDialog.vue";

const props = defineProps<{ templateId: string; name: string; machines: Machine[] }>();
const emit = defineEmits<{ close: []; changed: [] }>();

interface Plant {
  key: string;
  machineId: string;
  routeId: string;
  machine: string;
  plant: string;
  // Что сейчас стоит у растения, если не это расписание.
  current: string;
  linked: boolean;
}

const plants = computed<Plant[]>(() =>
  props.machines.flatMap((machine) =>
    machine.config.routes.map((route) => {
      const link = route.schedule_link;
      const linked = link?.template === props.templateId;
      let current = "";
      if (route.schedule) current = t("shared.has_own");
      else if (link && !linked) current = t("shared.has_other", { name: itemName("schedule", link.template) });
      return {
        key: `${machine.id}/${route.id}`,
        machineId: machine.id,
        routeId: route.id,
        machine: machine.config.name,
        plant: route.name || route.id,
        current,
        linked,
      };
    }),
  ),
);

const checked = ref(new Set(plants.value.filter((p) => p.linked).map((p) => p.key)));
const busy = ref(false);
const error = ref("");

function toggle(key: string) {
  const next = new Set(checked.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  checked.value = next;
}

async function save() {
  error.value = "";
  busy.value = true;
  try {
    for (const plant of plants.value) {
      const want = checked.value.has(plant.key);
      if (want && !plant.linked) {
        await api.linkSchedule(plant.machineId, plant.routeId, { template: props.templateId, enabled: true });
      } else if (!want && plant.linked) {
        await api.clearSchedule(plant.machineId, plant.routeId);
      }
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
  <ModalDialog :title="t('shared.plants_title', { name })" @close="emit('close')">
    <p class="muted small">{{ t("shared.plants_hint") }}</p>
    <p v-if="!plants.length" class="muted">{{ t("list.empty") }}</p>
    <ul class="plants">
      <li v-for="plant in plants" :key="plant.key">
        <label class="check">
          <input type="checkbox" :checked="checked.has(plant.key)" @change="toggle(plant.key)" />
          <span class="text">
            <strong>{{ plant.plant }}</strong>
            <span class="muted small">
              {{ plant.machine }}<template v-if="plant.current"> · {{ plant.current }}</template>
            </span>
          </span>
        </label>
      </li>
    </ul>
    <div v-if="error" class="error">{{ error }}</div>
    <div class="row">
      <button class="primary" :disabled="busy" @click="save"><AppIcon name="check" />{{ t("shared.save") }}</button>
      <button class="ghost" @click="emit('close')">{{ t("form.cancel") }}</button>
    </div>
  </ModalDialog>
</template>

<style scoped>
.plants {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 50vh;
  overflow-y: auto;
}

.check {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
}

.check:hover {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.check input {
  width: auto;
  flex: none;
}

.text {
  display: flex;
  flex-direction: column;
}
</style>
