<script setup lang="ts">
// Поля группы питания: политика совместной работы насосов на одном блоке.
import { computed } from "vue";
import type { PowerGroup } from "../../api";
import { t } from "../../i18n";
import FormField from "../FormField.vue";
import NumField from "../NumField.vue";

const group = defineModel<PowerGroup>({ required: true });

const limitWait = computed({
  get: () => group.value.max_wait_min !== null,
  set: (on: boolean) => {
    group.value.max_wait_min = on ? 60 : null;
  },
});

const wait = computed({
  get: () => group.value.max_wait_min ?? 60,
  set: (value: number) => {
    group.value.max_wait_min = value;
  },
});
</script>

<template>
  <div class="fields">
    <FormField v-slot="{ id }" class="wide" :label="t('catalog.name')">
      <input :id="id" v-model="group.name" required maxlength="100" :placeholder="t('power.group_placeholder')" />
    </FormField>
    <NumField v-model="group.max_concurrent" :label="t('power.limit')" :hint="t('power.limit_desc')" :min="1" />
    <NumField
      v-model="group.min_start_gap_s"
      :label="t('power.gap')"
      :hint="t('power.gap_desc')"
      :unit="t('unit.s')"
      :min="0"
    />
  </div>
  <label class="check">
    <input v-model="limitWait" type="checkbox" />
    <span>{{ t("power.wait_on") }}</span>
  </label>
  <div v-if="limitWait" class="fields">
    <NumField
      v-model="wait"
      :label="t('power.wait')"
      :hint="t('power.wait_desc')"
      :unit="t('power.unit_min')"
      :min="1"
    />
  </div>
</template>

<style scoped>
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0;
  cursor: pointer;
}

.check input {
  width: auto;
  flex: none;
}
</style>
