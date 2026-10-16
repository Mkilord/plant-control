<script setup lang="ts">
// Справочники: баки, насосы, коллекторы, расписания, группы питания.
// Запись заводится один раз и используется многими машинами.
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { CATALOG_KINDS, api, errorText, type CatalogKind } from "../api";
import { clone, KIND_ICON, KIND_TITLE, catalog, catalogError, loadCatalog, summary } from "../catalog";
import { t, type MessageKey } from "../i18n";
import AppIcon from "../components/AppIcon.vue";
import CatalogEditDialog from "../components/CatalogEditDialog.vue";

const props = defineProps<{ kind?: string }>();
const route = useRoute();
const router = useRouter();

const kind = computed<CatalogKind>(() =>
  CATALOG_KINDS.includes(props.kind as CatalogKind) ? (props.kind as CatalogKind) : "tank",
);
const entries = computed(() => catalog.value[kind.value]);
const editing = ref<{ id: string | null; wizard: boolean } | null>(null);
const error = ref("");

const DESC: Record<CatalogKind, MessageKey> = {
  tank: "catalog.desc.tank",
  pump: "catalog.desc.pump",
  collector: "catalog.desc.collector",
  schedule: "catalog.desc.schedule",
  power: "catalog.desc.power",
};

onMounted(loadCatalog);

function select(value: CatalogKind) {
  void router.replace(`/catalog/${value}`);
}

async function remove(id: string, name: string) {
  if (!confirm(t("catalog.delete_confirm", { name }))) return;
  error.value = "";
  try {
    await api.deleteItem(kind.value, id);
    await loadCatalog();
  } catch (e) {
    error.value = errorText(e);
  }
}

async function duplicate(id: string) {
  const entry = entries.value.find((item) => item.id === id);
  if (!entry) return;
  error.value = "";
  try {
    const copy = clone(entry.item);
    copy.name = t("catalog.copy_name", { name: copy.name });
    await api.createItem(kind.value, copy);
    await loadCatalog();
  } catch (e) {
    error.value = errorText(e);
  }
}

function usersText(users: { name: string; routes: string[] }[]): string {
  return users
    .map((user) => (user.routes.length ? `${user.name} (${user.routes.join(", ")})` : user.name))
    .join(", ");
}
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <div>
        <h1>{{ t("catalog.title") }}</h1>
        <p class="muted small subtitle">{{ t("catalog.desc") }}</p>
      </div>
    </div>

    <nav class="kinds" :aria-label="t('catalog.title')">
      <button
        v-for="item in CATALOG_KINDS"
        :key="item"
        type="button"
        class="kind"
        :class="{ active: kind === item }"
        :aria-pressed="kind === item"
        @click="select(item)"
      >
        <AppIcon :name="KIND_ICON[item]" :size="16" />
        {{ t(KIND_TITLE[item]) }}
        <span class="count">{{ catalog[item].length }}</span>
      </button>
    </nav>

    <p class="muted">{{ t(DESC[kind]) }}</p>

    <div v-if="catalogError || error" class="error">{{ error || catalogError }}</div>

    <div class="row add">
      <button class="primary" @click="editing = { id: null, wizard: kind === 'tank' }">
        <AppIcon name="plus" />{{ t("catalog.add") }}
      </button>
    </div>

    <p v-if="!entries.length" class="card muted empty">{{ t("catalog.empty") }}</p>

    <div class="grid">
      <article v-for="entry in entries" :key="entry.id" class="card item">
        <header class="head">
          <AppIcon :name="KIND_ICON[kind]" :size="18" />
          <h2>{{ entry.item.name }}</h2>
        </header>
        <p class="small">{{ summary(kind, entry.item) }}</p>
        <p class="muted small">
          <template v-if="entry.users.length">
            {{ t("catalog.used_by", { machines: usersText(entry.users) }) }}
          </template>
          <template v-else>{{ t("catalog.unused") }}</template>
        </p>
        <footer class="row actions">
          <button @click="editing = { id: entry.id, wizard: false }">
            <AppIcon name="edit" />{{ t("catalog.edit") }}
          </button>
          <button @click="duplicate(entry.id)">{{ t("catalog.duplicate") }}</button>
          <span class="spacer" />
          <button
            class="danger"
            :disabled="entry.users.length > 0"
            :title="entry.users.length ? t('catalog.in_use') : undefined"
            @click="remove(entry.id, entry.item.name)"
          >
            <AppIcon name="trash" />
          </button>
        </footer>
      </article>
    </div>

    <CatalogEditDialog
      v-if="editing"
      :key="`${kind}-${editing.id}-${route.fullPath}`"
      :kind="kind"
      :item-id="editing.id"
      :start-with-wizard="editing.wizard"
      @close="editing = null"
    />
  </div>
</template>

<style scoped>
.subtitle {
  margin: 2px 0 0;
}

.kinds {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0 12px;
}

.kind {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
}

.kind.active {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--primary-text);
}

.count {
  font-size: 12px;
  opacity: 0.8;
}

.add {
  margin-bottom: 12px;
}

.item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.item p {
  margin: 0;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--accent-tank);
}

.head h2 {
  color: var(--text);
  font-size: 16px;
  margin: 0;
}

.actions {
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  flex-wrap: wrap;
}

.spacer {
  flex: 1;
}

.empty {
  text-align: center;
}
</style>
