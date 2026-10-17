<script setup lang="ts">
// Выбор сущности Home Assistant (реле насоса или клапана).
// Стандартный <datalist> в приложении HA на Android не показывает список,
// поэтому список свой: поиск по имени и id, состояние, занятые другими машинами.
// Компьютер: список под полем, можно печатать и выбирать стрелками.
// Телефон: нажатие на поле открывает панель снизу с поиском.
// Id можно вписать и руками, если сущность ещё не появилась в HA.
import { computed, nextTick, onBeforeUnmount, ref } from "vue";
import type { HaEntity } from "../api";
import { t } from "../i18n";
import { claimPopup, placeNear, releasePopup, useNarrow } from "../narrow";
import BottomSheet from "./BottomSheet.vue";

const props = withDefaults(
  defineProps<{
    id?: string;
    entities: HaEntity[];
    // entity_id -> имя машины, которой реле уже принадлежит.
    taken?: Map<string, string>;
    placeholder?: string;
    required?: boolean;
  }>(),
  { id: undefined, taken: () => new Map(), placeholder: "", required: false },
);
const model = defineModel<string>({ default: "" });

const LIMIT = 150;
const narrow = useNarrow();
const input = ref<HTMLInputElement | null>(null);
const listEl = ref<HTMLElement | null>(null);
const search = ref<HTMLInputElement | null>(null);
const open = ref(false);
const query = ref("");
const active = ref(0);
const style = ref<Record<string, string>>({});
const listId = `${props.id ?? "entity"}-list`;

interface Option {
  entity: HaEntity;
  takenBy: string;
}

const options = computed<Option[]>(() => {
  const words = query.value.toLowerCase().split(/\s+/).filter(Boolean);
  const found = props.entities
    .filter((e) => {
      const hay = `${e.entity_id} ${e.name}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    })
    .map((entity) => ({ entity, takenBy: props.taken.get(entity.entity_id) ?? "" }));
  // Свободные сверху, занятые в конце.
  found.sort(
    (a, b) =>
      Number(Boolean(a.takenBy)) - Number(Boolean(b.takenBy)) ||
      a.entity.name.localeCompare(b.entity.name) ||
      a.entity.entity_id.localeCompare(b.entity.entity_id),
  );
  return found.slice(0, LIMIT);
});

const selectable = computed(() => options.value.filter((o) => !o.takenBy));

// Вписанный руками id, которого нет в списке.
const typed = computed(() => {
  const value = query.value.trim();
  if (!/^[a-z_]+\.[a-z0-9_]+$/.test(value)) return "";
  return props.entities.some((e) => e.entity_id === value) ? "" : value;
});

const currentName = computed(() => props.entities.find((e) => e.entity_id === model.value)?.name ?? "");

async function openList(initial = "") {
  if (open.value) return;
  claimPopup(closeList);
  query.value = initial;
  active.value = 0;
  open.value = true;
  await nextTick();
  if (narrow.value) {
    search.value?.focus();
    return;
  }
  // Список открывается целиком, фильтр включается при наборе.
  place();
  window.addEventListener("scroll", place, true);
  window.addEventListener("resize", place);
  document.addEventListener("pointerdown", onOutside, true);
}

function closeList() {
  open.value = false;
  releasePopup(closeList);
  window.removeEventListener("scroll", place, true);
  window.removeEventListener("resize", place);
  document.removeEventListener("pointerdown", onOutside, true);
}

function place() {
  const anchor = input.value?.getBoundingClientRect();
  if (!anchor) return;
  const width = Math.min(Math.max(anchor.width, 280), window.innerWidth - 16);
  const at = placeNear(anchor, width, Math.min(320, listEl.value?.scrollHeight ?? 320));
  style.value = {
    left: `${at.left}px`,
    top: `${at.top}px`,
    width: `${width}px`,
    maxHeight: `${Math.min(320, at.maxHeight)}px`,
  };
}

function onOutside(event: PointerEvent) {
  const target = event.target as Node;
  if (input.value?.contains(target) || listEl.value?.contains(target)) return;
  closeList();
}

function choose(entityId: string) {
  model.value = entityId;
  closeList();
}

// --- Поле на компьютере ---

function onInput(event: Event) {
  const value = (event.target as HTMLInputElement).value;
  model.value = value;
  query.value = value;
  active.value = 0;
  if (!open.value) void openList(value);
  else void nextTick(place);
}

function onFieldClick() {
  if (narrow.value) {
    input.value?.blur();
    void openList();
  } else if (!open.value) void openList();
}

function onKey(event: KeyboardEvent) {
  const count = selectable.value.length;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (!open.value) {
      void openList();
      return;
    }
    if (!count) return;
    const step = event.key === "ArrowDown" ? 1 : -1;
    active.value = (active.value + step + count) % count;
    void nextTick(() => listEl.value?.querySelector(".opt.active")?.scrollIntoView({ block: "nearest" }));
  } else if (event.key === "Enter" && open.value) {
    const option = selectable.value[active.value];
    if (option) {
      event.preventDefault();
      choose(option.entity.entity_id);
    } else if (typed.value) {
      event.preventDefault();
      choose(typed.value);
    }
  } else if (event.key === "Escape" && open.value) {
    event.preventDefault();
    event.stopPropagation();
    closeList();
  } else if (event.key === "Tab") {
    closeList();
  }
}

function isActive(option: Option): boolean {
  return !option.takenBy && selectable.value[active.value] === option;
}

onBeforeUnmount(closeList);
</script>

<template>
  <div class="entity-select">
    <input
      :id="id"
      ref="input"
      :value="model"
      :placeholder="placeholder"
      :required="required"
      :inputmode="narrow ? 'none' : undefined"
      role="combobox"
      autocomplete="off"
      autocapitalize="off"
      spellcheck="false"
      :aria-expanded="open"
      :aria-controls="listId"
      @input="onInput"
      @click="onFieldClick"
      @keydown="onKey"
    />
    <span v-if="currentName && currentName !== model" class="entity-name muted small">{{ currentName }}</span>

    <BottomSheet v-if="open && narrow" :title="t('entity.pick')" @close="closeList">
      <input
        ref="search"
        v-model="query"
        type="search"
        class="sheet-search"
        :placeholder="t('entity.search')"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
      />
      <ul :id="listId" class="opts sheet-opts" role="listbox">
        <li v-if="typed" class="opt" role="option" @click="choose(typed)">
          <span class="opt-main">{{ t("entity.use_typed", { id: typed }) }}</span>
        </li>
        <li
          v-for="option in options"
          :key="option.entity.entity_id"
          class="opt"
          :class="{ taken: option.takenBy, current: option.entity.entity_id === model }"
          role="option"
          :aria-disabled="Boolean(option.takenBy)"
          :aria-selected="option.entity.entity_id === model"
          @click="!option.takenBy && choose(option.entity.entity_id)"
        >
          <span class="opt-main">
            <span class="opt-name">{{ option.entity.name }}</span>
            <span class="opt-id">{{ option.entity.entity_id }}</span>
            <span v-if="option.takenBy" class="opt-taken">{{ t("entity.taken", { machine: option.takenBy }) }}</span>
          </span>
          <span class="opt-state" :class="{ on: option.entity.state === 'on' }">{{ option.entity.state }}</span>
        </li>
        <li v-if="!options.length && !typed" class="opt-empty muted">
          {{ entities.length ? t("entity.nothing") : t("entity.none") }}
        </li>
      </ul>
    </BottomSheet>

    <Teleport v-else-if="open" to="body">
      <ul :id="listId" ref="listEl" class="opts pop-opts" role="listbox" :style="style">
        <li v-if="typed" class="opt" role="option" @pointerdown.prevent @click="choose(typed)">
          <span class="opt-main">{{ t("entity.use_typed", { id: typed }) }}</span>
        </li>
        <li
          v-for="option in options"
          :key="option.entity.entity_id"
          class="opt"
          :class="{ taken: option.takenBy, active: isActive(option), current: option.entity.entity_id === model }"
          role="option"
          :aria-disabled="Boolean(option.takenBy)"
          :aria-selected="option.entity.entity_id === model"
          @pointerdown.prevent
          @click="!option.takenBy && choose(option.entity.entity_id)"
        >
          <span class="opt-main">
            <span class="opt-name">{{ option.entity.name }}</span>
            <span class="opt-id">{{ option.entity.entity_id }}</span>
            <span v-if="option.takenBy" class="opt-taken">{{ t("entity.taken", { machine: option.takenBy }) }}</span>
          </span>
          <span class="opt-state" :class="{ on: option.entity.state === 'on' }">{{ option.entity.state }}</span>
        </li>
        <li v-if="!options.length && !typed" class="opt-empty muted">
          {{ entities.length ? t("entity.nothing") : t("entity.none") }}
        </li>
      </ul>
    </Teleport>
  </div>
</template>

<style scoped>
.entity-select {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.entity-select > input {
  width: 100%;
}

.entity-name {
  padding-left: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.opts {
  list-style: none;
  margin: 0;
  padding: 4px;
  overflow-y: auto;
}

.pop-opts {
  position: fixed;
  z-index: 1000;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 10px 28px rgb(0 0 0 / 0.18);
}

.sheet-opts {
  padding: 0;
  margin: 0 -4px;
  min-height: 120px;
}

.sheet-search {
  width: 100%;
  font-size: 16px;
}

.opt {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
}

.sheet-opts .opt {
  padding: 11px 10px;
  border-bottom: 1px solid var(--border);
  border-radius: 0;
}

.opt:hover,
.opt.active {
  background: var(--water-soft);
}

.opt.current .opt-name {
  color: var(--primary);
  font-weight: 600;
}

.opt.taken {
  cursor: default;
  opacity: 0.55;
}

.opt.taken:hover {
  background: none;
}

.opt-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.opt-name,
.opt-id {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.opt-id,
.opt-taken {
  font-size: 12px;
  color: var(--muted);
}

.opt-state {
  font-size: 12px;
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 1px 8px;
}

.opt-state.on {
  color: var(--ok);
  border-color: var(--ok);
}

.opt-empty {
  padding: 12px 10px;
  font-size: 13px;
}
</style>
