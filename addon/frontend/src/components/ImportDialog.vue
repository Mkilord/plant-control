<script setup lang="ts">
// Импорт машин из файла экспорта: выбрать файл, посмотреть, что будет, отметить машины.
import { computed, ref } from "vue";
import { api, errorText, type ExportBundle, type ImportPlan } from "../api";
import { loadCatalog } from "../catalog";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import ModalDialog from "./ModalDialog.vue";

const emit = defineEmits<{ close: []; changed: [] }>();

const bundle = ref<ExportBundle | null>(null);
const plan = ref<ImportPlan | null>(null);
const chosen = ref(new Set<string>());
const busy = ref(false);
const error = ref("");

const importable = computed(() => plan.value?.machines.filter((m) => !Object.keys(m.taken).length) ?? []);

async function onFile(event: Event) {
  error.value = "";
  plan.value = null;
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  busy.value = true;
  try {
    const data = JSON.parse(await file.text()) as ExportBundle;
    plan.value = await api.previewImport(data);
    bundle.value = data;
    chosen.value = new Set(importable.value.map((m) => m.id));
  } catch (e) {
    error.value = e instanceof SyntaxError ? t("transfer.bad_file") : errorText(e);
  } finally {
    busy.value = false;
  }
}

function toggle(id: string) {
  const next = new Set(chosen.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  chosen.value = next;
}

function takenText(taken: Record<string, string>): string {
  return Object.entries(taken)
    .map(([entity, machine]) => t("transfer.taken", { entity, machine }))
    .join("; ");
}

async function run() {
  if (!bundle.value || !chosen.value.size) return;
  error.value = "";
  busy.value = true;
  try {
    await api.importMachines(bundle.value, [...chosen.value]);
    await loadCatalog();
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
  <ModalDialog :title="t('transfer.import_title')" @close="emit('close')">
    <p class="muted small">{{ t("transfer.import_hint") }}</p>
    <input type="file" accept="application/json,.json" :disabled="busy" @change="onFile" />

    <template v-if="plan">
      <ul class="machines">
        <li v-for="item in plan.machines" :key="item.id">
          <label class="check" :class="{ blocked: Object.keys(item.taken).length }">
            <input
              type="checkbox"
              :checked="chosen.has(item.id)"
              :disabled="Object.keys(item.taken).length > 0"
              @change="toggle(item.id)"
            />
            <span class="text">
              <strong>{{ item.name }}</strong>
              <span class="muted small">{{ t("transfer.plants", { n: item.plants }) }}</span>
              <span v-if="Object.keys(item.taken).length" class="error-text small">
                {{ takenText(item.taken) }}
              </span>
            </span>
          </label>
        </li>
      </ul>
      <p class="muted small">
        {{ t("transfer.items", { created: plan.new_items, reused: plan.reused_items }) }}
      </p>
    </template>

    <div v-if="error" class="error">{{ error }}</div>
    <div class="row">
      <button class="primary" :disabled="busy || !chosen.size" @click="run">
        <AppIcon name="check" />{{ t("transfer.import_n", { n: chosen.size }) }}
      </button>
      <button class="ghost" @click="emit('close')">{{ t("form.cancel") }}</button>
    </div>
  </ModalDialog>
</template>

<style scoped>
.machines {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 45vh;
  overflow-y: auto;
}

.check {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
}

.check.blocked {
  cursor: default;
  opacity: 0.8;
}

.check input {
  width: auto;
  flex: none;
  margin-top: 3px;
}

.text {
  display: flex;
  flex-direction: column;
}

.error-text {
  color: var(--danger);
}
</style>
