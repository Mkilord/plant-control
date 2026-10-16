<script setup lang="ts">
// Кнопка "ещё": редкие действия прячутся в выпадающий список.
// Закрывается по клику вне меню, по Escape и после выбора пункта.
import { onBeforeUnmount, ref, watch } from "vue";
import AppIcon from "./AppIcon.vue";

// down - меню раскрывается вниз (кнопка вверху страницы), иначе вверх (низ карточки).
withDefaults(defineProps<{ label: string; down?: boolean }>(), { down: false });

const open = ref(false);
const root = ref<HTMLElement | null>(null);

function onDocument(event: Event) {
  if (root.value && !root.value.contains(event.target as Node)) open.value = false;
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") open.value = false;
}

watch(open, (value) => {
  if (value) {
    document.addEventListener("click", onDocument);
    document.addEventListener("keydown", onKey);
  } else {
    document.removeEventListener("click", onDocument);
    document.removeEventListener("keydown", onKey);
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
    <div v-if="open" class="menu card" :class="{ down }" role="menu" @click="open = false">
      <slot />
    </div>
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
  position: absolute;
  right: 0;
  bottom: calc(100% + 6px);
  z-index: 5;
  min-width: 200px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  box-shadow: 0 8px 24px rgb(0 0 0 / 0.16);
}

.menu.down {
  bottom: auto;
  top: calc(100% + 6px);
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
