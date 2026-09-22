<script setup lang="ts">
import { ref } from "vue";
import { api, errorText, type Machine } from "../api";
import { ml } from "../format";
import ModalDialog from "./ModalDialog.vue";

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
  <ModalDialog :title="`Бак: ${machine.config.name}`" @close="emit('close')">
    <p class="muted small">
      Сейчас по расчёту {{ ml(machine.status.tank.volume_ml) }} из
      {{ ml(machine.status.tank.capacity_ml) }}.
    </p>
    <button class="primary" :disabled="busy" @click="run(() => api.refill(machine.id, null))">
      Залил до полного
    </button>
    <label class="field">
      <span>Или укажите, сколько воды в баке сейчас, мл</span>
      <input v-model.number="volume" type="number" min="0" step="50" />
    </label>
    <div v-if="error" class="error">{{ error }}</div>
    <div class="row">
      <button :disabled="busy" @click="run(() => api.setVolume(machine.id, volume))">
        Сохранить объём
      </button>
    </div>
  </ModalDialog>
</template>
