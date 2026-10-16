<script setup lang="ts">
// Поля типа бака: имя, форма и размеры, запас под насосом.
// В API форма и ориентация - одно поле shape. Здесь они разделены:
// способ задания (по замеру или по форме), форма, ориентация (только для цилиндра).
import { computed } from "vue";
import type { TankType } from "../../api";
import { capacityMl } from "../../catalog";
import { ml } from "../../format";
import { t } from "../../i18n";
import AppIcon from "../AppIcon.vue";
import FormField from "../FormField.vue";
import NumField from "../NumField.vue";

const tank = defineModel<TankType>({ required: true });

type TankMode = "measured" | "shape";
type TankShape = "cylinder" | "rectangular";
type Orientation = "vertical" | "horizontal";

const mode = computed<TankMode>({
  get: () => (tank.value.geometry.shape === "measured" ? "measured" : "shape"),
  set: (value) => {
    tank.value.geometry =
      value === "measured"
        ? { shape: "measured", volume_ml: 2000, height_mm: 150 }
        : { shape: "vertical_cylinder", diameter_mm: 130, height_mm: 150 };
  },
});

const shape = computed<TankShape>({
  get: () => (tank.value.geometry.shape === "rectangular" ? "rectangular" : "cylinder"),
  set: (value) => {
    tank.value.geometry =
      value === "rectangular"
        ? { shape: "rectangular", width_mm: 150, depth_mm: 100, height_mm: 150 }
        : { shape: "vertical_cylinder", diameter_mm: 130, height_mm: 150 };
  },
});

const orientation = computed<Orientation>({
  get: () => (tank.value.geometry.shape === "horizontal_cylinder" ? "horizontal" : "vertical"),
  set: (value) => {
    const geometry = tank.value.geometry;
    const diameter = "diameter_mm" in geometry ? geometry.diameter_mm : 130;
    tank.value.geometry =
      value === "horizontal"
        ? { shape: "horizontal_cylinder", diameter_mm: diameter, length_mm: 300 }
        : { shape: "vertical_cylinder", diameter_mm: diameter, height_mm: 150 };
  },
});

// Объём бака вводится в литрах, хранится в мл.
const volumeL = computed({
  get: () => {
    const geometry = tank.value.geometry;
    return geometry.shape === "measured" ? geometry.volume_ml / 1000 : 0;
  },
  set: (liters: number) => {
    const geometry = tank.value.geometry;
    if (geometry.shape === "measured") geometry.volume_ml = Math.round(liters * 1000);
  },
});

const capacity = computed(() => capacityMl(tank.value.geometry));
</script>

<template>
  <div class="fields">
    <FormField v-slot="{ id }" class="wide" :label="t('catalog.name')">
      <input :id="id" v-model="tank.name" required maxlength="100" :placeholder="t('catalog.tank_placeholder')" />
    </FormField>
    <FormField v-slot="{ id }" class="wide" :label="t('tank.mode')">
      <select :id="id" v-model="mode">
        <option value="measured">{{ t("tank.mode.measured") }}</option>
        <option value="shape">{{ t("tank.mode.shape") }}</option>
      </select>
    </FormField>
    <template v-if="mode === 'shape'">
      <FormField v-slot="{ id }" :label="t('tank.shape')">
        <select :id="id" v-model="shape">
          <option value="cylinder">{{ t("tank.shape.cylinder") }}</option>
          <option value="rectangular">{{ t("tank.shape.rectangular") }}</option>
        </select>
      </FormField>
      <FormField v-if="shape === 'cylinder'" v-slot="{ id }" :label="t('tank.orientation')">
        <select :id="id" v-model="orientation">
          <option value="vertical">{{ t("tank.orientation.vertical") }}</option>
          <option value="horizontal">{{ t("tank.orientation.horizontal") }}</option>
        </select>
      </FormField>
    </template>
  </div>
  <p class="note">
    <AppIcon name="info" />
    <span>{{ mode === "measured" ? t("tank.mode_hint_measured") : t("tank.mode_hint_shape") }}</span>
  </p>

  <div class="fields sub">
    <template v-if="tank.geometry.shape === 'measured'">
      <NumField
        v-model="volumeL"
        :label="t('tank.volume')"
        :unit="t('unit.l')"
        :hint="t('tank.volume_hint')"
        :min="0.01"
      />
      <NumField
        v-model="tank.geometry.height_mm"
        :label="t('tank.height')"
        :unit="t('unit.mm')"
        :hint="t('tank.height_hint')"
        :min="1"
      />
    </template>
    <template v-else-if="tank.geometry.shape === 'vertical_cylinder'">
      <NumField
        v-model="tank.geometry.diameter_mm"
        :label="t('tank.diameter')"
        :unit="t('unit.mm')"
        :hint="t('tank.diameter_hint')"
        :min="1"
      />
      <NumField
        v-model="tank.geometry.height_mm"
        :label="t('tank.cyl_height')"
        :unit="t('unit.mm')"
        :hint="t('tank.cyl_height_hint')"
        :min="1"
      />
    </template>
    <template v-else-if="tank.geometry.shape === 'horizontal_cylinder'">
      <NumField
        v-model="tank.geometry.diameter_mm"
        :label="t('tank.diameter')"
        :unit="t('unit.mm')"
        :hint="t('tank.diameter_hint')"
        :min="1"
      />
      <NumField v-model="tank.geometry.length_mm" :label="t('tank.length')" :unit="t('unit.mm')" :min="1" />
    </template>
    <template v-else-if="tank.geometry.shape === 'rectangular'">
      <NumField v-model="tank.geometry.width_mm" :label="t('tank.width')" :unit="t('unit.mm')" :min="1" />
      <NumField v-model="tank.geometry.depth_mm" :label="t('tank.depth')" :unit="t('unit.mm')" :min="1" />
      <NumField
        v-model="tank.geometry.height_mm"
        :label="t('tank.rect_height')"
        :unit="t('unit.mm')"
        :hint="t('tank.cyl_height_hint')"
        :min="1"
      />
    </template>
    <NumField
      v-model="tank.reserve_ml"
      :label="t('tank.reserve')"
      :unit="t('unit.ml')"
      :hint="t('tank.reserve_hint')"
      :min="0"
    />
  </div>
  <p class="muted small">{{ t("wizard.tank.result", { volume: ml(capacity), usable: ml(Math.max(0, capacity - tank.reserve_ml)) }) }}</p>
</template>

<style scoped>
.sub {
  margin-top: 14px;
}
</style>
