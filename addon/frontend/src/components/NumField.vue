<script setup lang="ts">
// Числовое поле с единицами справа и подсказкой в иконке "i".
import FormField from "./FormField.vue";

withDefaults(
  defineProps<{
    label: string;
    unit?: string;
    hint?: string;
    min?: number;
    max?: number;
    required?: boolean;
  }>(),
  { unit: "", hint: "", min: undefined, max: undefined, required: true },
);
const model = defineModel<number>({ required: true });

function onInput(event: Event) {
  const value = (event.target as HTMLInputElement).valueAsNumber;
  if (!Number.isNaN(value)) model.value = value;
}
</script>

<template>
  <FormField v-slot="{ id }" :label="label" :hint="hint">
    <span class="num">
      <!-- step="any": без него браузер пропускает только значения, кратные шагу от минимума -->
      <input
        :id="id"
        type="number"
        step="any"
        :value="model"
        :min="min"
        :max="max"
        :required="required"
        @input="onInput"
      />
      <span v-if="unit" class="unit">{{ unit }}</span>
    </span>
  </FormField>
</template>
