<script setup lang="ts">
// Поля записи справочника любого вида: выбирает нужный набор полей по kind.
import { computed } from "vue";
import type {
  CatalogItems,
  CatalogKind,
  CollectorType,
  PowerGroup,
  PumpModel,
  ScheduleTemplate,
  TankType,
} from "../../api";
import CollectorTypeFields from "./CollectorTypeFields.vue";
import PowerGroupFields from "./PowerGroupFields.vue";
import PumpModelFields from "./PumpModelFields.vue";
import ScheduleTemplateFields from "./ScheduleTemplateFields.vue";
import TankTypeFields from "./TankTypeFields.vue";

const props = defineProps<{ kind: CatalogKind }>();
const item = defineModel<CatalogItems[CatalogKind]>({ required: true });

// Прокси с нужным типом: шаблону так проще, чем приводить тип в каждом v-model.
function proxy<T>() {
  return computed({
    get: () => item.value as T,
    set: (value: T) => {
      item.value = value as CatalogItems[CatalogKind];
    },
  });
}

const tank = proxy<TankType>();
const pump = proxy<PumpModel>();
const collector = proxy<CollectorType>();
const schedule = proxy<ScheduleTemplate>();
const power = proxy<PowerGroup>();
</script>

<template>
  <TankTypeFields v-if="props.kind === 'tank'" v-model="tank" />
  <PumpModelFields v-else-if="props.kind === 'pump'" v-model="pump" />
  <CollectorTypeFields v-else-if="props.kind === 'collector'" v-model="collector" />
  <ScheduleTemplateFields v-else-if="props.kind === 'schedule'" v-model="schedule" />
  <PowerGroupFields v-else v-model="power" />
</template>
