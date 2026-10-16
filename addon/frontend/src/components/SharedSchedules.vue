<script setup lang="ts">
// Общие расписания на вкладке "Поливы": одно расписание на много растений.
import { computed, onMounted, ref } from "vue";
import { api, errorText, type Machine } from "../api";
import { catalog, loadCatalog, summary } from "../catalog";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import CatalogEditDialog from "./CatalogEditDialog.vue";
import SchedulePlantsDialog from "./SchedulePlantsDialog.vue";

const props = defineProps<{ machines: Machine[] }>();
const emit = defineEmits<{ changed: [] }>();

const entries = computed(() => catalog.value.schedule);
const editing = ref<{ id: string | null } | null>(null);
const attaching = ref<{ id: string; name: string } | null>(null);
const error = ref("");

onMounted(loadCatalog);

// Растения расписания по свежему списку машин: он обновляется чаще справочника.
function plantsOf(id: string): string[] {
  return props.machines.flatMap((machine) =>
    machine.config.routes
      .filter((route) => route.schedule_link?.template === id)
      .map((route) => `${route.name || route.id} (${machine.config.name})`),
  );
}

async function remove(id: string, name: string) {
  if (!confirm(t("catalog.delete_confirm", { name }))) return;
  error.value = "";
  try {
    await api.deleteItem("schedule", id);
    await loadCatalog();
  } catch (e) {
    error.value = errorText(e);
  }
}

async function changed() {
  await loadCatalog();
  emit("changed");
}
</script>

<template>
  <section class="card">
    <div class="section-head">
      <h2 class="section-title"><AppIcon name="clock" :size="18" />{{ t("shared.title") }}</h2>
      <span class="spacer" />
      <button class="small-button" @click="editing = { id: null }">
        <AppIcon name="plus" :size="16" />{{ t("shared.add") }}
      </button>
    </div>
    <p class="muted small desc">{{ t("shared.desc") }}</p>
    <div v-if="error" class="error">{{ error }}</div>
    <p v-if="!entries.length" class="muted small">{{ t("shared.empty") }}</p>

    <ul class="items">
      <li v-for="entry in entries" :key="entry.id" class="item">
        <div class="main">
          <strong>{{ entry.item.name }}</strong>
          <span class="muted small">{{ summary("schedule", entry.item) }}</span>
          <span class="small plants">
            <template v-if="plantsOf(entry.id).length">{{ plantsOf(entry.id).join(", ") }}</template>
            <span v-else class="muted">{{ t("shared.no_plants") }}</span>
          </span>
        </div>
        <div class="buttons">
          <button class="small-button" @click="attaching = { id: entry.id, name: entry.item.name }">
            <AppIcon name="plant" :size="16" />{{ t("shared.plants") }}
          </button>
          <button
            class="icon-button"
            :title="t('catalog.edit')"
            :aria-label="t('catalog.edit')"
            @click="editing = { id: entry.id }"
          >
            <AppIcon name="edit" :size="17" />
          </button>
          <button
            class="icon-button danger-icon"
            :disabled="plantsOf(entry.id).length > 0"
            :title="plantsOf(entry.id).length ? t('catalog.in_use') : t('form.delete')"
            :aria-label="t('form.delete')"
            @click="remove(entry.id, entry.item.name)"
          >
            <AppIcon name="trash" :size="17" />
          </button>
        </div>
      </li>
    </ul>

    <CatalogEditDialog
      v-if="editing"
      kind="schedule"
      :item-id="editing.id"
      @close="editing = null"
      @saved="changed"
    />
    <SchedulePlantsDialog
      v-if="attaching"
      :template-id="attaching.id"
      :name="attaching.name"
      :machines="machines"
      @close="attaching = null"
      @changed="changed"
    />
  </section>
</template>

<style scoped>
.section-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  margin: 0;
}

.spacer {
  flex: 1;
}

.desc {
  margin: 4px 0 10px;
}

.items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-top: 1px solid var(--border);
  flex-wrap: wrap;
}

.main {
  flex: 1 1 220px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.plants {
  overflow-wrap: anywhere;
}

.buttons {
  display: flex;
  align-items: center;
  gap: 6px;
}

.small-button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 13px;
}

.danger-icon {
  color: var(--danger);
}

.danger-icon:disabled {
  color: var(--muted);
  opacity: 0.5;
}
</style>
