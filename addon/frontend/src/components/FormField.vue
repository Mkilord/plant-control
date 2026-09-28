<script setup lang="ts">
// Обёртка поля: подпись, иконка с подсказкой, слот для самого поля.
// Подпись связана с полем через id, а не вложением: внутри <label> кнопка подсказки
// перехватила бы клик по подписи.
import { useId } from "vue";
import InfoTip from "./InfoTip.vue";

withDefaults(defineProps<{ label: string; hint?: string }>(), { hint: "" });
const id = useId();
</script>

<template>
  <div class="field">
    <span class="label-row">
      <label :for="id">{{ label }}</label>
      <InfoTip v-if="hint" :text="hint" />
    </span>
    <slot :id="id" />
  </div>
</template>

<style scoped>
.label-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text);
  font-size: 13px;
}
</style>
