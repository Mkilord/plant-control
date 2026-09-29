<script setup lang="ts">
// Настройки add-on'а. Пока здесь уведомления: кому слать, о чём, тихие часы,
// а с флажком "Расширенные настройки" - свои тексты и адрес по нажатию.
import { computed, onMounted, ref, watch } from "vue";
import {
  api,
  errorText,
  EVENT_KINDS,
  type EventKind,
  type EventText,
  type NotificationSettings,
  type NotificationTemplate,
  type PushDevices,
} from "../api";
import AppIcon from "../components/AppIcon.vue";
import FormField from "../components/FormField.vue";
import FormSection from "../components/FormSection.vue";
import InfoTip from "../components/InfoTip.vue";
import { hasMessage, t } from "../i18n";

const settings = ref<NotificationSettings | null>(null);
const devices = ref<PushDevices | null>(null);
const devicesError = ref("");
const templates = ref<Partial<Record<EventKind, NotificationTemplate>>>({});
const previews = ref<Partial<Record<EventKind, EventText>>>({});

const loading = ref(true);
const saving = ref(false);
// Что лежит на сервере: по нему видно, есть ли несохранённые правки.
const snapshot = ref("");
const savedOnce = ref(false);
const saved = computed(
  () => savedOnce.value && JSON.stringify(settings.value) === snapshot.value,
);
const error = ref("");
const testing = ref(false);
const testResult = ref("");

onMounted(async () => {
  try {
    const [current, list] = await Promise.all([
      api.notificationSettings(),
      api.notificationTemplates(),
    ]);
    accept(current);
    templates.value = Object.fromEntries(list.map((item) => [item.kind, item]));
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
  await loadDevices();
});

// У каждого вида событий есть запись текста: поля формы привязаны к ней напрямую.
function accept(value: NotificationSettings) {
  for (const kind of EVENT_KINDS) {
    value.texts[kind] ??= { title: "", message: "" };
  }
  settings.value = value;
  snapshot.value = JSON.stringify(value);
}

async function loadDevices() {
  devicesError.value = "";
  try {
    devices.value = await api.pushDevices();
  } catch (e) {
    devicesError.value = t("settings.devices_error", { error: errorText(e) });
  }
}

// Телефоны для выбора: те, что есть в HA, и выбранные раньше, но пропавшие.
const phoneList = computed(() => {
  const available = devices.value?.available ?? [];
  const chosen = settings.value?.devices ?? [];
  const names = [...available, ...chosen.filter((name) => !available.includes(name))];
  return names.map((name) => ({ name, label: phoneLabel(name), missing: !available.includes(name) }));
});

function phoneLabel(service: string): string {
  return service.replace(/^mobile_app_/, "").replaceAll("_", " ");
}

function toggleList<T>(list: T[], value: T, on: boolean): T[] {
  return on ? [...list.filter((item) => item !== value), value] : list.filter((item) => item !== value);
}

function setDevice(name: string, on: boolean) {
  if (settings.value) settings.value.devices = toggleList(settings.value.devices, name, on);
}

function setEvent(kind: EventKind, on: boolean) {
  if (settings.value) settings.value.events = toggleList(settings.value.events, kind, on);
}

// --- Тексты ---

function text(kind: EventKind): EventText {
  return settings.value!.texts[kind]!;
}

function insert(kind: EventKind, name: string) {
  const item = text(kind);
  // Пустое поле - это текст по умолчанию: подстановка дописывается к нему.
  const base = item.message || templates.value[kind]?.message || "";
  item.message = `${base}${base && !base.endsWith(" ") ? " " : ""}{${name}}`;
}

function customized(kind: EventKind): boolean {
  const item = settings.value?.texts[kind];
  return Boolean(item && (item.title.trim() || item.message.trim()));
}

function reset(kind: EventKind) {
  settings.value!.texts[kind] = { title: "", message: "" };
}

// Внутри шаблона "}}" закрыло бы подстановку Vue, поэтому скобки собираются здесь.
function token(name: string): string {
  return "{" + name + "}";
}

function placeholderLabel(name: string): string {
  const key = `placeholder.${name}`;
  return hasMessage(key) ? t(key) : name;
}

// Пример уведомления пересчитывается сервером, чтобы совпасть с настоящим до буквы.
let previewTimer: number | undefined;
watch(
  () => (settings.value?.advanced ? JSON.stringify(settings.value.texts) : ""),
  (value) => {
    if (!value) return;
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(refreshPreviews, 300);
  },
  { immediate: true },
);

async function refreshPreviews() {
  const current = settings.value;
  if (!current) return;
  const entries = await Promise.all(
    EVENT_KINDS.map(async (kind) => {
      try {
        const item = current.texts[kind] ?? { title: "", message: "" };
        return [kind, await api.previewNotification(kind, item)] as const;
      } catch {
        // Неизвестная подстановка: пример не показываем, ошибку покажет сохранение.
        return [kind, null] as const;
      }
    }),
  );
  previews.value = Object.fromEntries(entries.filter(([, value]) => value !== null));
}

// --- Действия ---

async function save() {
  if (!settings.value) return;
  error.value = "";
  saving.value = true;
  try {
    accept(await api.saveNotificationSettings(settings.value));
    savedOnce.value = true;
    await loadDevices();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    saving.value = false;
  }
}

async function testPush() {
  testResult.value = "";
  error.value = "";
  testing.value = true;
  try {
    // Проверяем то, что на экране: сначала сохранить.
    await save();
    if (error.value) return;
    const result = await api.testPush();
    testResult.value = t("settings.test_sent", { devices: result.devices.map(phoneLabel).join(", ") });
  } catch (e) {
    error.value = errorText(e);
  } finally {
    testing.value = false;
  }
}
</script>

<template>
  <div class="page settings">
    <div class="toolbar">
      <h1><AppIcon name="settings" :size="22" /> {{ t("settings.title") }}</h1>
    </div>

    <p v-if="loading" class="muted">{{ t("settings.loading") }}</p>
    <div v-else-if="!settings" class="error">{{ error }}</div>

    <form v-else @submit.prevent="save">
      <!-- Пуши -->
      <FormSection
        :title="t('settings.push_title')"
        icon="droplet"
        accent="var(--accent-tank)"
        :description="t('settings.push_desc')"
      >
        <label class="check">
          <input v-model="settings.enabled" type="checkbox" />
          {{ t("settings.enabled") }}
        </label>

        <fieldset class="group" :disabled="!settings.enabled">
          <div class="label-row">
            {{ t("settings.devices") }}
            <InfoTip :text="t('settings.devices_hint')" />
          </div>
          <div v-if="devicesError" class="error">{{ devicesError }}</div>
          <p v-else-if="devices && !phoneList.length" class="note">
            <AppIcon name="alert" />
            <span>{{ t("settings.devices_none") }}</span>
          </p>
          <div class="phones">
            <label v-for="phone in phoneList" :key="phone.name" class="check phone">
              <input
                type="checkbox"
                :checked="settings.devices.includes(phone.name)"
                @change="setDevice(phone.name, ($event.target as HTMLInputElement).checked)"
              />
              <span>
                {{ phone.label }}
                <span class="muted small">notify.{{ phone.name }}</span>
                <span v-if="phone.missing" class="chip danger">{{ t("settings.device_missing") }}</span>
              </span>
            </label>
          </div>
          <p v-if="!settings.devices.length && devices?.available.length" class="muted small">
            {{ t("settings.devices_all", { count: devices.available.length }) }}
          </p>

          <label class="check">
            <input v-model="settings.critical" type="checkbox" />
            {{ t("settings.critical") }}
            <InfoTip :text="t('settings.critical_hint')" />
          </label>

          <div class="row">
            <button type="button" :disabled="testing || saving" @click="testPush">
              <AppIcon name="play" />{{ t("settings.test") }}
            </button>
            <span v-if="testResult" class="chip on">{{ testResult }}</span>
          </div>
        </fieldset>
      </FormSection>

      <!-- События и тихие часы -->
      <FormSection
        :title="t('settings.events_title')"
        icon="alert"
        accent="var(--accent-general)"
        :description="t('settings.events_desc')"
      >
        <fieldset class="group" :disabled="!settings.enabled">
          <div class="events">
            <label v-for="kind in EVENT_KINDS" :key="kind" class="check">
              <input
                type="checkbox"
                :checked="settings.events.includes(kind)"
                @change="setEvent(kind, ($event.target as HTMLInputElement).checked)"
              />
              {{ t(`event.${kind}`) }}
            </label>
          </div>
          <div class="fields">
            <FormField v-slot="{ id }" :label="t('settings.quiet_from')" :hint="t('settings.quiet_hint')">
              <input :id="id" v-model="settings.quiet_from" type="time" />
            </FormField>
            <FormField v-slot="{ id }" :label="t('settings.quiet_to')">
              <input :id="id" v-model="settings.quiet_to" type="time" />
            </FormField>
          </div>
        </fieldset>
      </FormSection>

      <!-- Расширенные -->
      <div class="card advanced-toggle">
        <label class="check">
          <input v-model="settings.advanced" type="checkbox" />
          <AppIcon name="sliders" />
          <b>{{ t("settings.advanced") }}</b>
          <InfoTip :text="t('settings.advanced_hint')" />
        </label>
      </div>

      <FormSection
        v-if="settings.advanced"
        :title="t('settings.texts_title')"
        icon="edit"
        accent="var(--accent-extra)"
        :description="t('settings.texts_desc')"
      >
        <div class="fields url">
          <FormField v-slot="{ id }" class="wide" :label="t('settings.open_url')" :hint="t('settings.open_url_hint')">
            <input :id="id" v-model="settings.open_url" placeholder="/hassio/ingress/…" />
          </FormField>
        </div>

        <!-- Каждый вид события свёрнут: видно только название и пример. -->
        <details v-for="kind in EVENT_KINDS" :key="kind" class="text-block">
          <summary class="text-head">
            <AppIcon name="back" :size="14" class="chevron" />
            <b>{{ t(`event.${kind}`) }}</b>
            <span v-if="customized(kind)" class="chip on">{{ t("settings.text_custom") }}</span>
            <span class="summary-preview muted small">{{ previews[kind]?.title }}</span>
          </summary>
          <div class="text-actions">
            <button
              type="button"
              class="small-button"
              :disabled="!customized(kind)"
              @click="reset(kind)"
            >
              {{ t("settings.text_reset") }}
            </button>
          </div>
          <div class="fields">
            <FormField v-slot="{ id }" class="wide" :label="t('settings.text_title')">
              <input
                :id="id"
                v-model="text(kind).title"
                maxlength="120"
                :placeholder="templates[kind]?.title"
              />
            </FormField>
            <FormField v-slot="{ id }" class="wide" :label="t('settings.text_message')">
              <textarea
                :id="id"
                v-model="text(kind).message"
                rows="2"
                maxlength="500"
                :placeholder="templates[kind]?.message"
              />
            </FormField>
          </div>
          <div class="placeholders">
            <button
              v-for="name in templates[kind]?.placeholders ?? []"
              :key="name"
              type="button"
              class="chip placeholder"
              :title="placeholderLabel(name)"
              @click="insert(kind, name)"
            >
              {{ token(name) }} <span class="muted">{{ placeholderLabel(name) }}</span>
            </button>
          </div>
          <div v-if="previews[kind]" class="preview">
            <span class="muted small">{{ t("settings.preview") }}</span>
            <div class="bubble">
              <b>{{ previews[kind]?.title }}</b>
              <span>{{ previews[kind]?.message }}</span>
            </div>
          </div>
        </details>
      </FormSection>

      <div v-if="error" class="error">{{ error }}</div>

      <div class="row buttons">
        <button type="submit" class="primary" :disabled="saving">
          <AppIcon name="check" />{{ t("settings.save") }}
        </button>
        <span v-if="saved" class="chip on">{{ t("settings.saved") }}</span>
      </div>
    </form>
  </div>
</template>

<style scoped>
.settings {
  max-width: 880px;
}

h1 {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

/* Общее правило растягивает поля на всю ширину, флажку это ни к чему. */
.check input {
  width: auto;
  flex: none;
}

.group {
  border: none;
  padding: 0;
  margin: 14px 0 0;
  background: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.group:disabled {
  opacity: 0.55;
}

.label-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.phones,
.events {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.phone .chip {
  margin-left: 6px;
}

.advanced-toggle {
  margin-bottom: 16px;
}

.url {
  margin-bottom: 16px;
}

.text-block {
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
}

.text-head {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  list-style: none;
}

.text-head::-webkit-details-marker {
  display: none;
}

.chevron {
  transform: rotate(180deg);
  transition: transform 0.15s;
  color: var(--muted);
}

details[open] .chevron {
  transform: rotate(270deg);
}

.summary-preview {
  margin-left: auto;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 45%;
}

.text-actions {
  display: flex;
  justify-content: flex-end;
  margin: 10px 0;
}

.spacer {
  flex: 1;
}

.small-button {
  padding: 3px 10px;
  font-size: 13px;
}

textarea {
  resize: vertical;
}

.placeholders {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.chip.placeholder {
  cursor: pointer;
  font-family: ui-monospace, monospace;
  background: none;
  gap: 4px;
}

.chip.placeholder .muted {
  font-family: inherit;
}

.preview {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.bubble {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  font-size: 14px;
}

.buttons {
  margin-top: 8px;
}
</style>
