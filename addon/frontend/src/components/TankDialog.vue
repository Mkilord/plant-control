<script setup lang="ts">
import { t } from "../i18n";
import { ref } from "vue";
import { api, errorText, type Machine } from "../api";
import { ml } from "../format";
import AppIcon from "./AppIcon.vue";
import ModalDialog from "./ModalDialog.vue";
import NumField from "./NumField.vue";

const props = defineProps<{ machine: Machine }>();
const emit = defineEmits<{ close: []; changed: [] }>();

const volume = ref(Math.round(props.machine.status.tank.volume_ml));
const error = ref("");
const busy = ref(false);

async function run(action: () => Promise<unknown>) {
  error.value = "";
  busy.value = true;
  try {
    await action();
    emit("changed");
    emit("close");
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <ModalDialog :title="t('tank.title', { name: machine.config.name })" @close="emit('close')">
    <p class="muted small">
      {{
        t("tank.now", {
          volume: ml(machine.status.tank.volume_ml),
          capacity: ml(machine.status.tank.capacity_ml),
        })
      }}
    </p>
    <button class="primary" :disabled="busy" @click="run(() => api.refill(machine.id, null))">
      <AppIcon name="refill" />{{ t("tank.full") }}
    </button>
    <NumField v-model="volume" :label="t('tank.set')" :unit="t('unit.ml')" :min="0" />
    <div v-if="error" class="error">{{ error }}</div>
    <div class="row">
      <button :disabled="busy" @click="run(() => api.setVolume(machine.id, volume))">
        {{ t("tank.save") }}
      </button>
    </div>
  </ModalDialog>
</template>
