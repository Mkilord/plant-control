<script setup lang="ts">
// Кнопка "ещё": редкие действия прячутся в выпадающий список.
// Закрывается по клику вне меню, по Escape и после выбора пункта.
// Меню рисуется поверх страницы и всегда целиком в пределах экрана.
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { claimPopup, releasePopup } from "../narrow";
import AppIcon from "./AppIcon.vue";

// down - меню раскрывается вниз (кнопка вверху страницы), иначе вверх (низ карточки).
// Если в эту сторону места нет, меню откроется в другую.
const props = withDefaults(defineProps<{ label: string; down?: boolean }>(), { down: false });

const MARGIN = 8;
const GAP = 6;
const open = ref(false);
const root = ref<HTMLElement | null>(null);
const menu = ref<HTMLElement | null>(null);
const style = ref<Record<string, string>>({ visibility: "hidden" });

function close() {
  open.value = false;
}

function onDocument(event: Event) {
  const target = event.target as Node;
  if (root.value?.contains(target) || menu.value?.contains(target)) return;
  open.value = false;
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") open.value = false;
}

function place() {
  const anchor = root.value?.getBoundingClientRect();
  const el = menu.value;
  if (!anchor || !el) return;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = el.offsetWidth;
  const height = el.offsetHeight;
  // Правый край меню у правого края кнопки, но не за пределами экрана.
  const left = Math.max(MARGIN, Math.min(anchor.right - width, vw - width - MARGIN));
  const below = vh - anchor.bottom - GAP - MARGIN;
  const above = anchor.top - GAP - MARGIN;
  const downward = props.down ? height <= below || below >= above : !(height <= above || above >= below);
  const top = downward ? anchor.bottom + GAP : Math.max(MARGIN, anchor.top - GAP - height);
  const room = downward ? below : above;
  style.value = { left: `${left}px`, top: `${top}px`, maxHeight: `${Math.max(120, room)}px` };
}

watch(open, async (value) => {
  if (value) {
    claimPopup(close);
    style.value = { visibility: "hidden" };
    document.addEventListener("click", onDocument);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    await nextTick();
    place();
  } else {
    releasePopup(close);
    document.removeEventListener("click", onDocument);
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", place);
    window.removeEventListener("scroll", place, true);
  }
});

onBeforeUnmount(() => (open.value = false));
</script>

<template>
  <div ref="root" class="more">
    <button
      type="button"
      class="icon-button trigger"
      :title="label"
      :aria-label="label"
      :aria-expanded="open"
      @click="open = !open"
    >
      <AppIcon name="dots" :size="18" />
    </button>
    <Teleport to="body">
      <div v-if="open" ref="menu" class="menu card" role="menu" :style="style" @click="open = false">
        <slot />
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.more {
  position: relative;
}

.trigger {
  border: 1px solid var(--border);
}

.menu {
  position: fixed;
  z-index: 1000;
  min-width: 200px;
  max-width: calc(100vw - 16px);
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  box-shadow: 0 8px 24px rgb(0 0 0 / 0.16);
}

.menu :deep(button),
.menu :deep(a) {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  justify-content: flex-start;
  border: none;
  background: none;
  padding: 9px 10px;
  border-radius: 8px;
  color: var(--text);
  text-decoration: none;
  font-size: 14px;
}

.menu :deep(button:hover),
.menu :deep(a:hover) {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
}
</style>
