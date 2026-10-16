<script setup lang="ts">
import { t } from "../i18n";
import { computed } from "vue";
import type { MachineStatus } from "../api";
import { ml } from "../format";

// compact - тонкая полоска и только доступный объём: для свёрнутой карточки.
const props = withDefaults(defineProps<{ tank: MachineStatus["tank"]; compact?: boolean }>(), {
  compact: false,
});

const percent = (value: number) =>
  props.tank.capacity_ml > 0 ? Math.max(0, Math.min(100, (value / props.tank.capacity_ml) * 100)) : 0;

const waterPercent = computed(() => percent(props.tank.volume_ml));
const reservePercent = computed(() => percent(props.tank.reserve_ml));
const low = computed(() => props.tank.usable_ml < props.tank.capacity_ml * 0.15);
</script>

<template>
  <div class="gauge" :class="{ compact }" :title="t('gauge.level', { level: Math.round(tank.level_mm) })">
    <div class="bar">
      <div class="water" :class="{ low }" :style="{ width: waterPercent + '%' }" />
      <div class="reserve" :style="{ width: reservePercent + '%' }" />
    </div>
    <div class="row small">
      <span>
        {{ t("gauge.available") }} <b>{{ ml(tank.usable_ml) }}</b>
      </span>
      <slot />
      <span v-if="!compact" class="muted">{{
        t("gauge.of", { capacity: ml(tank.capacity_ml), reserve: ml(tank.reserve_ml) })
      }}</span>
    </div>
  </div>
</template>

<style scoped>
.gauge {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bar {
  position: relative;
  height: 14px;
  border-radius: 7px;
  background: var(--water-soft);
  overflow: hidden;
}

.compact .bar {
  height: 8px;
  border-radius: 4px;
}

.water {
  position: absolute;
  inset: 0 auto 0 0;
  background: var(--water);
  transition: width 0.4s;
}

.water.low {
  background: var(--warn);
}

.reserve {
  position: absolute;
  inset: 0 auto 0 0;
  background: repeating-linear-gradient(
    45deg,
    var(--reserve),
    var(--reserve) 4px,
    transparent 4px,
    transparent 8px
  );
}
</style>
