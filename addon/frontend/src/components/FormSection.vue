<script setup lang="ts">
// Раздел формы: цветной значок, заголовок, описание раздела и поля.
import AppIcon, { type IconName } from "./AppIcon.vue";

withDefaults(
  defineProps<{ title: string; icon: IconName; accent?: string; description?: string }>(),
  { accent: "var(--primary)", description: "" },
);
</script>

<template>
  <section class="card section" :style="{ '--accent': accent }">
    <header class="section-head">
      <span class="badge"><AppIcon :name="icon" :size="20" /></span>
      <div>
        <h2>{{ title }}</h2>
        <p v-if="description" class="section-desc">{{ description }}</p>
      </div>
    </header>
    <slot />
  </section>
</template>

<style scoped>
.section {
  margin-bottom: 16px;
  border-top: 3px solid var(--accent);
}

.section-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  flex: none;
}

.section-desc {
  margin: 2px 0 0;
  color: var(--muted);
  font-size: 13px;
}
</style>
