<script setup lang="ts">
// Выбор записи справочника: взять готовую, пройти мастер (для бака) или ввести вручную.
// Новая запись сразу попадает в справочник и выбирается.
import { computed, ref, watch } from "vue";
import { api, errorText, type CatalogItems, type CatalogKind, type TankType } from "../api";
import { defaultItem, entriesOf, findEntry, loadCatalog, summary } from "../catalog";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import FormField from "./FormField.vue";
import ItemFields from "./fields/ItemFields.vue";
import TankWizard from "./TankWizard.vue";

const props = withDefaults(
  defineProps<{
    kind: CatalogKind;
    label: string;
    hint?: string;
    // Можно ничего не выбирать: например, машина без группы питания.
    noneLabel?: string;
    // Показать кнопку мастера (есть только у бака).
    wizard?: boolean;
  }>(),
  { hint: "", noneLabel: "", wizard: false },
);
const selected = defineModel<string | null>({ required: true });
// Открыт ввод новой записи: форма вокруг прячет свои кнопки, чтобы не путать.
const emit = defineEmits<{ editing: [on: boolean] }>();

type Mode = "pick" | "manual" | "wizard";
const mode = ref<Mode>("pick");
const draft = ref<CatalogItems[CatalogKind]>(defaultItem(props.kind));
const saving = ref(false);
const error = ref("");
watch(mode, (value) => emit("editing", value !== "pick"));

const entries = computed(() => entriesOf(props.kind));
const current = computed(() => findEntry(props.kind, selected.value));

// Пока справочник пуст, сразу предлагаем завести запись.
const empty = computed(() => !entries.value.length);

function startManual() {
  draft.value = defaultItem(props.kind);
  mode.value = "manual";
}

async function create(item: CatalogItems[CatalogKind]) {
  error.value = "";
  saving.value = true;
  try {
    const entry = await api.createItem(props.kind, item);
    await loadCatalog();
    selected.value = entry.id;
    mode.value = "pick";
  } catch (e) {
    error.value = errorText(e);
  } finally {
    saving.value = false;
  }
}

function onWizard(item: TankType) {
  void create(item);
}

function onSelect(event: Event) {
  selected.value = (event.target as HTMLSelectElement).value || null;
}
</script>

<template>
  <div class="picker">
    <template v-if="mode === 'pick'">
      <FormField v-slot="{ id }" :label="label" :hint="hint">
        <select :id="id" :value="selected ?? ''" :required="!noneLabel" @change="onSelect">
          <option v-if="noneLabel" value="">{{ noneLabel }}</option>
          <option v-else value="" disabled>{{ empty ? t("picker.empty") : t("picker.choose") }}</option>
          <option v-for="entry in entries" :key="entry.id" :value="entry.id">
            {{ entry.item.name }} · {{ summary(kind, entry.item) }}
          </option>
        </select>
      </FormField>
      <p v-if="current" class="muted small used">
        {{ t("picker.used_by", { n: current.users.length }) }}
      </p>
      <div class="row actions">
        <button v-if="wizard" type="button" @click="mode = 'wizard'">
          <AppIcon name="sliders" />{{ t("picker.wizard") }}
        </button>
        <button type="button" @click="startManual"><AppIcon name="plus" />{{ t("picker.manual") }}</button>
      </div>
    </template>

    <div v-else-if="mode === 'manual'" class="draft">
      <ItemFields v-model="draft" :kind="kind" />
      <div v-if="error" class="error">{{ error }}</div>
      <div class="row">
        <button type="button" class="primary" :disabled="saving" @click="create(draft)">
          <AppIcon name="check" />{{ t("picker.save_new") }}
        </button>
        <button type="button" class="ghost" @click="mode = 'pick'">{{ t("form.cancel") }}</button>
      </div>
    </div>

    <div v-else class="draft">
      <TankWizard @done="onWizard" @cancel="mode = 'pick'" />
      <div v-if="error" class="error">{{ error }}</div>
    </div>
  </div>
</template>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.used {
  margin: 0;
}

.actions {
  flex-wrap: wrap;
}

.draft {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px dashed var(--border);
  border-radius: 10px;
}
</style>
