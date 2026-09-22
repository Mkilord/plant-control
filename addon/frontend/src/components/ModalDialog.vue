<script setup lang="ts">
defineProps<{ title: string }>();
const emit = defineEmits<{ close: [] }>();
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="dialog card" role="dialog" :aria-label="title">
      <div class="row head">
        <h2>{{ title }}</h2>
        <button class="close" aria-label="Закрыть" @click="emit('close')">×</button>
      </div>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  background: rgb(0 0 0 / 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  z-index: 10;
}

.dialog {
  width: 100%;
  max-width: 440px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.head {
  justify-content: space-between;
}

.close {
  border: none;
  font-size: 22px;
  padding: 0 6px;
}
</style>
