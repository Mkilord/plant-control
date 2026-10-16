<script setup lang="ts">
// Правка записи справочника. Перед сохранением показывает, какие машины она затронет
// и у каких устареет калибровка. "Сохранить как новый" не трогает старую запись.
import { computed, ref } from "vue";
import {
  api,
  errorText,
  type CatalogImpact,
  type CatalogItems,
  type CatalogKind,
  type TankType,
} from "../api";
import { clone, KIND_TITLE, defaultItem, findEntry, loadCatalog } from "../catalog";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import ModalDialog from "./ModalDialog.vue";
import TankWizard from "./TankWizard.vue";
import ItemFields from "./fields/ItemFields.vue";

const props = defineProps<{
  kind: CatalogKind;
  // null - новая запись.
  itemId: string | null;
  // Новую запись бака можно завести мастером.
  startWithWizard?: boolean;
}>();
const emit = defineEmits<{ close: []; saved: [id: string]; savedAsNew: [id: string] }>();

const entry = computed(() => findEntry(props.kind, props.itemId));
const draft = ref<CatalogItems[CatalogKind]>(
  entry.value ? clone(entry.value.item) : defaultItem(props.kind),
);
const wizard = ref(Boolean(props.startWithWizard && props.kind === "tank" && !props.itemId));
const impact = ref<CatalogImpact[] | null>(null);
const busy = ref(false);
const error = ref("");

const title = computed(() =>
  props.itemId
    ? t("catalog.edit_title", { name: entry.value?.item.name ?? "" })
    : t("catalog.new_title", { kind: t(KIND_TITLE[props.kind]) }),
);
const staleImpact = computed(() => (impact.value ?? []).filter((item) => item.stale_routes.length));

async function save() {
  error.value = "";
  busy.value = true;
  try {
    if (!props.itemId) {
      const created = await api.createItem(props.kind, draft.value);
      await loadCatalog();
      emit("saved", created.id);
      emit("close");
      return;
    }
    // Запись используют машины: сначала показать, что изменится.
    if (impact.value === null && entry.value?.users.length) {
      impact.value = await api.previewItem(props.kind, props.itemId, draft.value);
      return;
    }
    await api.updateItem(props.kind, props.itemId, draft.value);
    await loadCatalog();
    emit("saved", props.itemId);
    emit("close");
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}

async function saveAsNew() {
  error.value = "";
  busy.value = true;
  try {
    const copy = clone(draft.value);
    if (copy.name === entry.value?.item.name) copy.name = t("catalog.copy_name", { name: copy.name });
    const created = await api.createItem(props.kind, copy);
    await loadCatalog();
    emit("savedAsNew", created.id);
    emit("close");
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}

function fromWizard(item: TankType) {
  draft.value = item;
  wizard.value = false;
}
</script>

<template>
  <ModalDialog :title="title" class="wide-dialog" @close="emit('close')">
    <TankWizard v-if="wizard" @done="fromWizard" @cancel="wizard = false" />

    <form v-else class="stack" @submit.prevent="save">
      <p v-if="kind === 'tank' && !itemId" class="muted small">
        <button type="button" class="ghost" @click="wizard = true">
          <AppIcon name="sliders" />{{ t("picker.wizard") }}
        </button>
      </p>

      <template v-if="impact === null">
        <ItemFields v-model="draft" :kind="kind" />
        <p v-if="entry?.users.length" class="note">
          <AppIcon name="info" />
          <span>{{ t("catalog.shared_note", { n: entry.users.length }) }}</span>
        </p>
      </template>

      <!-- Подтверждение: что затронет изменение. -->
      <div v-else class="impact">
        <p>{{ t("catalog.impact_intro", { n: impact.length }) }}</p>
        <ul class="small">
          <li v-for="item in impact" :key="item.machine_id">
            {{ item.name }}
            <span v-if="item.stale_routes.length" class="chip warn">
              {{ t("catalog.impact_stale", { routes: item.stale_routes.join(", ") }) }}
            </span>
          </li>
        </ul>
        <p v-if="staleImpact.length" class="note warn-note">
          <AppIcon name="alert" />
          <span>{{ t("catalog.impact_stale_hint") }}</span>
        </p>
      </div>

      <div v-if="error" class="error">{{ error }}</div>

      <div class="row buttons">
        <button type="submit" class="primary" :disabled="busy">
          <AppIcon name="check" />
          {{ impact === null ? t("form.save") : t("catalog.impact_confirm") }}
        </button>
        <button v-if="impact !== null" type="button" @click="impact = null">{{ t("wizard.back") }}</button>
        <span class="spacer" />
        <button v-if="itemId" type="button" :disabled="busy" @click="saveAsNew">
          {{ t("catalog.save_as_new") }}
        </button>
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

.impact ul {
  margin: 8px 0;
  padding-left: 20px;
}

.impact li {
  margin-bottom: 4px;
}

.warn-note {
  --accent: var(--warn);
}

.buttons {
  flex-wrap: wrap;
}

.spacer {
  flex: 1;
}

:deep(.dialog) {
  max-width: 640px;
  max-height: calc(100vh - 32px);
  overflow-y: auto;
}
</style>
