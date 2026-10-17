<script setup lang="ts">
// Панель снизу экрана для телефона: подсказки и списки выбора.
// Закрывается нажатием мимо, крестиком, Esc и кнопкой "Назад" телефона.
import { onBeforeUnmount, onMounted } from "vue";

defineProps<{ title?: string }>();
const emit = defineEmits<{ close: [] }>();

// Кнопка "Назад": панель кладёт в историю свою запись, а "Назад" её снимает.
// Запись копирует текущее состояние роутера, поэтому роутер ничего не замечает.
let ownEntry = false;

function onPop() {
  ownEntry = false;
  emit("close");
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.stopPropagation();
    emit("close");
  }
}

onMounted(() => {
  try {
    history.pushState({ ...(history.state ?? {}), sheet: true }, "");
    ownEntry = true;
    window.addEventListener("popstate", onPop);
  } catch {
    ownEntry = false;
  }
  document.addEventListener("keydown", onKey, true);
});

onBeforeUnmount(() => {
  window.removeEventListener("popstate", onPop);
  document.removeEventListener("keydown", onKey, true);
  if (ownEntry && history.state?.sheet) history.back();
});
</script>

<template>
  <Teleport to="body">
    <div class="sheet-backdrop" @click.self="emit('close')">
      <div class="sheet" role="dialog" :aria-label="title">
        <div class="sheet-grip" aria-hidden="true" />
        <div v-if="title" class="sheet-head">
          <strong>{{ title }}</strong>
          <button type="button" class="sheet-close" aria-label="Close" @click="emit('close')">×</button>
        </div>
        <slot />
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgb(0 0 0 / 0.4);
  display: flex;
  align-items: flex-end;
}

.sheet {
  width: 100%;
  max-height: 85vh;
  max-height: 85dvh;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 6px 16px calc(16px + env(safe-area-inset-bottom));
  background: var(--card);
  color: var(--text);
  border-radius: 16px 16px 0 0;
  box-shadow: 0 -8px 30px rgb(0 0 0 / 0.25);
  animation: rise 0.16s ease-out;
}

.sheet-grip {
  align-self: center;
  width: 40px;
  height: 4px;
  border-radius: 2px;
  background: var(--border);
  margin-bottom: 4px;
}

.sheet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.sheet-close {
  border: none;
  background: none;
  font-size: 24px;
  line-height: 1;
  padding: 0 4px;
  color: var(--muted);
}

@keyframes rise {
  from {
    transform: translateY(24px);
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sheet {
    animation: none;
  }
}
</style>
