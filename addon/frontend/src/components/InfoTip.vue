<script setup lang="ts">
// Иконка "i" с подсказкой.
// Компьютер: открывается при наведении и по нажатию, рисуется поверх страницы
// и всегда целиком в пределах экрана (окна с прокруткой её не обрезают).
// Телефон: нажатие открывает панель снизу во всю ширину.
import { nextTick, onBeforeUnmount, ref } from "vue";
import { t } from "../i18n";
import { claimPopup, placeNear, releasePopup, useNarrow } from "../narrow";
import AppIcon from "./AppIcon.vue";
import BottomSheet from "./BottomSheet.vue";

defineProps<{ text: string }>();

const narrow = useNarrow();
const button = ref<HTMLButtonElement | null>(null);
const pop = ref<HTMLElement | null>(null);
const open = ref(false);
// Открыта нажатием: не закрывать, когда мышь уходит.
const pinned = ref(false);
const style = ref<Record<string, string>>({});
let hoverTimer: ReturnType<typeof setTimeout> | undefined;

async function show(pin: boolean) {
  clearTimeout(hoverTimer);
  claimPopup(close);
  pinned.value = pinned.value || pin;
  open.value = true;
  if (narrow.value) return;
  await nextTick();
  place();
  window.addEventListener("scroll", place, true);
  window.addEventListener("resize", place);
  document.addEventListener("pointerdown", onOutside, true);
  document.addEventListener("keydown", onKey);
}

function place() {
  const anchor = button.value?.getBoundingClientRect();
  const el = pop.value;
  if (!anchor || !el) return;
  const at = placeNear(anchor, el.offsetWidth, el.offsetHeight);
  style.value = { left: `${at.left - 10}px`, top: `${at.top}px`, maxHeight: `${at.maxHeight}px` };
  // Сдвиг на 10px влево выше выравнивает стрелку по иконке, но не за край экрана.
  if (at.left - 10 < 8) style.value.left = `${at.left}px`;
}

function close() {
  clearTimeout(hoverTimer);
  open.value = false;
  pinned.value = false;
  releasePopup(close);
  window.removeEventListener("scroll", place, true);
  window.removeEventListener("resize", place);
  document.removeEventListener("pointerdown", onOutside, true);
  document.removeEventListener("keydown", onKey);
}

function toggle() {
  if (open.value && pinned.value) close();
  else void show(true);
}

function onOutside(event: PointerEvent) {
  const target = event.target as Node;
  if (button.value?.contains(target) || pop.value?.contains(target)) return;
  close();
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") close();
}

function onEnter(event: PointerEvent) {
  if (event.pointerType === "mouse" && !narrow.value) void show(false);
}

function onLeave(event: PointerEvent) {
  if (event.pointerType !== "mouse" || pinned.value) return;
  hoverTimer = setTimeout(close, 150);
}

onBeforeUnmount(close);
</script>

<template>
  <span class="tip" @pointerenter="onEnter" @pointerleave="onLeave">
    <button
      ref="button"
      type="button"
      class="tip-button"
      :aria-label="text"
      :aria-expanded="open"
      @click.stop.prevent="toggle"
    >
      <AppIcon name="info" :size="15" />
    </button>
    <BottomSheet v-if="open && narrow" @close="close">
      <p class="tip-sheet-text">{{ text }}</p>
      <button type="button" class="primary" @click="close">{{ t("tip.ok") }}</button>
    </BottomSheet>
    <Teleport v-else-if="open" to="body">
      <span
        ref="pop"
        class="tip-pop"
        role="tooltip"
        :style="style"
        @pointerenter="onEnter"
        @pointerleave="onLeave"
        >{{ text }}</span
      >
    </Teleport>
  </span>
</template>

<style scoped>
.tip {
  display: inline-flex;
}

.tip-button {
  border: none;
  background: none;
  padding: 2px;
  margin: -2px;
  color: var(--muted);
  cursor: help;
  border-radius: 50%;
}

.tip-button:hover,
.tip-button:focus-visible,
.tip-button[aria-expanded="true"] {
  color: var(--primary);
}

.tip-pop {
  position: fixed;
  z-index: 1000;
  left: 0;
  top: 0;
  width: max-content;
  max-width: min(300px, calc(100vw - 16px));
  overflow-y: auto;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--tip-bg);
  color: var(--tip-text);
  font-size: 12.5px;
  line-height: 1.4;
  box-shadow: 0 6px 20px rgb(0 0 0 / 0.18);
  white-space: pre-line;
}

.tip-sheet-text {
  margin: 0;
  font-size: 15px;
  line-height: 1.5;
  white-space: pre-line;
}
</style>
