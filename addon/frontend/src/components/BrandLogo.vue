<script setup lang="ts">
// Знак PlantControl: капля с ростком. Тот же рисунок, что у favicon и иконки add-on'а.
import { useId } from "vue";

withDefaults(defineProps<{ size?: number }>(), { size: 28 });
// У каждого знака свой градиент: одинаковые id на странице мешали бы друг другу.
const gradient = `brand-${useId()}`;
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 64 64" aria-hidden="true" class="brand-logo">
    <defs>
      <linearGradient :id="gradient" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#0b84c6" />
        <stop offset="1" stop-color="#43a047" />
      </linearGradient>
    </defs>
    <rect width="64" height="64" rx="14" :fill="`url(#${gradient})`" />
    <path d="M32 9c9 11.5 16 20.5 16 29a16 16 0 0 1-32 0c0-8.5 7-17.5 16-29z" fill="#fff" />
    <path d="M32 50V36" stroke="#2e7d32" stroke-width="3.2" stroke-linecap="round" fill="none" />
    <path d="M32 38c0-6 3.5-10 10-10 0 6.5-4 10.3-10 10z" fill="#43a047" />
    <path d="M32 42c0-4.5-3-7.5-8-7.5 0 5 3 7.8 8 7.5z" fill="#66bb6a" />
  </svg>
</template>

<style scoped>
.brand-logo {
  flex: none;
  display: block;
}
</style>
