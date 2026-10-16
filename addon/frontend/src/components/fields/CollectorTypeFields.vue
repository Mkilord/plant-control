<script setup lang="ts">
// Поля типа коллектора: число выходов и паузы клапана вокруг работы насоса.
import type { CollectorType } from "../../api";
import { t } from "../../i18n";
import FormField from "../FormField.vue";
import NumField from "../NumField.vue";

const collector = defineModel<CollectorType>({ required: true });
</script>

<template>
  <div class="fields">
    <FormField v-slot="{ id }" class="wide" :label="t('catalog.name')">
      <input
        :id="id"
        v-model="collector.name"
        required
        maxlength="100"
        :placeholder="t('catalog.collector_placeholder')"
      />
    </FormField>
    <NumField
      v-model="collector.outlets"
      :label="t('collector.outlets')"
      :hint="t('collector.outlets_hint')"
      :min="2"
      :max="32"
    />
    <NumField
      v-model="collector.valve_lead_s"
      :label="t('tube.lead')"
      :unit="t('unit.s')"
      :hint="t('tube.lead_hint')"
      :min="0"
    />
    <NumField
      v-model="collector.valve_lag_s"
      :label="t('tube.lag')"
      :unit="t('unit.s')"
      :hint="t('tube.lag_hint')"
      :min="0"
    />
  </div>
</template>
