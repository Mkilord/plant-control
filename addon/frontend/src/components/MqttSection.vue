<script setup lang="ts">
// Раздел настроек MQTT: через него машины появляются в Home Assistant как устройства.
// Сохраняется вместе со всей страницей, но только если что-то поменялось:
// каждое сохранение переподключает мост к брокеру.
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, errorText, type MqttSettingsIn, type MqttStatus } from "../api";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import FormField from "./FormField.vue";
import FormSection from "./FormSection.vue";
import InfoTip from "./InfoTip.vue";

defineProps<{ advanced: boolean }>();

const form = ref<MqttSettingsIn | null>(null);
const hasPassword = ref(false);
const snapshot = ref("");
const status = ref<MqttStatus | null>(null);
const error = ref("");
let timer: number | undefined;

function accept(value: MqttSettingsIn & { has_password?: boolean }) {
  hasPassword.value = Boolean(value.has_password);
  const { has_password: _, ...rest } = value;
  form.value = { ...rest, password: null };
  snapshot.value = JSON.stringify(form.value);
}

async function refreshStatus() {
  try {
    status.value = await api.mqttStatus();
  } catch {
    // Состояние - подсказка, а не главное на странице.
  }
}

onMounted(async () => {
  try {
    const current = await api.mqttSettings();
    accept({ ...current, password: null });
  } catch (e) {
    error.value = errorText(e);
  }
  await refreshStatus();
  timer = window.setInterval(() => {
    if (!document.hidden) void refreshStatus();
  }, 3000);
});
onUnmounted(() => window.clearInterval(timer));

const dirty = computed(() => form.value !== null && JSON.stringify(form.value) !== snapshot.value);

// Пустое поле пароля - "не менять", а не "стереть".
const password = computed({
  get: () => form.value?.password ?? "",
  set: (value: string) => {
    if (form.value) form.value.password = value === "" ? null : value;
  },
});

async function save(): Promise<void> {
  if (!form.value || !dirty.value) return;
  const saved = await api.saveMqttSettings(form.value);
  accept({ ...saved, password: null });
  // Мост переподключается: состояние поменяется через мгновение.
  window.setTimeout(refreshStatus, 400);
  window.setTimeout(refreshStatus, 1500);
}

defineExpose({ save, dirty });

const STATUS_TONE: Record<MqttStatus["state"], string> = {
  off: "",
  no_broker: "warn",
  connecting: "",
  connected: "on",
  error: "danger",
};
</script>

<template>
  <FormSection
    :title="t('mqtt.title')"
    icon="collector"
    accent="var(--accent-pump)"
    :description="t('mqtt.desc')"
  >
    <div v-if="error" class="error">{{ error }}</div>

    <template v-if="form">
      <div class="head-row">
        <label class="check">
          <input v-model="form.enabled" type="checkbox" />
          {{ t("mqtt.enabled") }}
        </label>
        <span class="spacer" />
        <span
          v-if="status"
          class="chip status"
          :class="STATUS_TONE[status.state]"
          :title="status.error ?? ''"
        >
          <span class="dot" />
          {{ t(`mqtt.state_${status.state}`) }}
        </span>
      </div>

      <p v-if="status?.broker" class="muted small broker">
        {{ t("mqtt.broker_now", { broker: status.broker }) }}
        <template v-if="status.source">· {{ t(`mqtt.source_${status.source}`) }}</template>
      </p>
      <p v-if="status?.state === 'error' && status.error" class="error small-error">
        {{ status.error }}
      </p>
      <p v-if="status?.state === 'no_broker' && form.enabled" class="note warn-note">
        <AppIcon name="alert" />
        <span>{{ form.mode === "auto" ? t("mqtt.no_broker_auto") : t("mqtt.no_broker_manual") }}</span>
      </p>

      <fieldset class="group" :disabled="!form.enabled">
        <div class="modes" role="radiogroup">
          <label class="mode" :class="{ active: form.mode === 'auto' }">
            <input v-model="form.mode" type="radio" value="auto" />
            <span>
              <b>{{ t("mqtt.mode_auto") }}</b>
              <span class="muted small">{{ t("mqtt.mode_auto_desc") }}</span>
            </span>
          </label>
          <label class="mode" :class="{ active: form.mode === 'manual' }">
            <input v-model="form.mode" type="radio" value="manual" />
            <span>
              <b>{{ t("mqtt.mode_manual") }}</b>
              <span class="muted small">{{ t("mqtt.mode_manual_desc") }}</span>
            </span>
          </label>
        </div>

        <div v-if="form.mode === 'manual'" class="fields">
          <FormField v-slot="{ id }" class="wide" :label="t('mqtt.host')">
            <input :id="id" v-model.trim="form.host" required placeholder="192.168.1.10" />
          </FormField>
          <FormField v-slot="{ id }" :label="t('mqtt.port')">
            <input :id="id" v-model.number="form.port" type="number" min="1" max="65535" />
          </FormField>
          <FormField v-slot="{ id }" :label="t('mqtt.username')">
            <input :id="id" v-model="form.username" autocomplete="off" />
          </FormField>
          <FormField v-slot="{ id }" :label="t('mqtt.password')" :hint="t('mqtt.password_hint')">
            <input
              :id="id"
              v-model="password"
              type="password"
              autocomplete="new-password"
              :placeholder="hasPassword ? t('mqtt.password_keep') : ''"
            />
          </FormField>
        </div>

        <div v-if="advanced" class="fields">
          <FormField
            v-slot="{ id }"
            :label="t('mqtt.prefix')"
            :hint="t('mqtt.prefix_hint')"
          >
            <input :id="id" v-model.trim="form.discovery_prefix" required pattern="[\w/-]+" />
          </FormField>
        </div>
        <p v-else class="muted small">
          {{ t("mqtt.what") }}
          <InfoTip :text="t('mqtt.what_hint')" />
        </p>
      </fieldset>
    </template>
  </FormSection>
</template>

<style scoped>
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.check input,
.mode input {
  width: auto;
  flex: none;
}

.head-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.spacer {
  flex: 1;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.broker {
  margin: 6px 0 0;
}

.small-error {
  font-size: 13px;
}

.warn-note {
  --accent: var(--warn);
}

.group {
  border: none;
  padding: 0;
  margin: 14px 0 0;
  background: none;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.group:disabled {
  opacity: 0.55;
}

.modes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
}

.mode {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
}

.mode input {
  margin-top: 3px;
}

.mode > span {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mode.active {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 7%, transparent);
}
</style>
