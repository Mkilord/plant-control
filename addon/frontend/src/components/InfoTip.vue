<script setup lang="ts">
// Иконка "i" с подсказкой. На компьютере открывается при наведении,
// на телефоне по нажатию (кнопка получает фокус), закрывается нажатием в другом месте.
// Если справа не хватает места, подсказка открывается влево.
import { ref } from "vue";
import AppIcon from "./AppIcon.vue";

defineProps<{ text: string }>();

const POP_WIDTH = 290;
const root = ref<HTMLElement | null>(null);
const alignRight = ref(false);

function place() {
  const rect = root.value?.getBoundingClientRect();
  if (rect) alignRight.value = rect.left + POP_WIDTH > window.innerWidth;
}
</script>

<template>
  <span ref="root" class="tip" @mouseenter="place" @focusin="place">
    <button type="button" class="tip-button" :aria-label="text">
      <AppIcon name="info" :size="15" />
    </button>
    <span class="tip-pop" :class="{ right: alignRight }" role="tooltip">{{ text }}</span>
  </span>
</template>

<style scoped>
.tip {
  position: relative;
  display: inline-flex;
}

.tip-button {
  border: none;
  background: none;
  padding: 0;
  color: var(--muted);
  cursor: help;
  border-radius: 50%;
}

.tip-button:hover,
.tip-button:focus-visible {
  color: var(--primary);
}

.tip-pop {
  display: none;
  position: absolute;
  z-index: 20;
  top: calc(100% + 6px);
  left: -10px;
  width: max-content;
  max-width: min(280px, 78vw);
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--tip-bg);
  color: var(--tip-text);
  font-size: 12.5px;
  line-height: 1.4;
  box-shadow: 0 6px 20px rgb(0 0 0 / 0.18);
  white-space: normal;
}

.tip-pop.right {
  left: auto;
  right: -10px;
}

.tip:hover .tip-pop,
.tip:focus-within .tip-pop {
  display: block;
}
</style>
