<script setup lang="ts">
// Меню "..." у журнала: удалить записи старше N дней или все.
// Перед удалением спрашивает подтверждение своим окном: системный confirm()
// в приложении Home Assistant работает не везде.
import { ref } from "vue";
import { errorText } from "../api";
import { t } from "../i18n";
import AppIcon from "./AppIcon.vue";
import ModalDialog from "./ModalDialog.vue";
import MoreMenu from "./MoreMenu.vue";

const props = defineProps<{
  // Что чистим, для текста подтверждения: "журнал поливов".
  what: string;
  // Сколько записей попадёт под очистку: days null - все.
  count: (days: number | null) => number;
  clear: (days: number | null) => Promise<number>;
  // Уточнение под вопросом, например "только записи с ошибками".
  note?: string;
}>();
const emit = defineEmits<{ done: [deleted: number] }>();

const PERIODS = [7, 30, 90];
const asking = ref<{ days: number | null } | null>(null);
const busy = ref(false);
const error = ref("");

function ask(days: number | null) {
  error.value = "";
  asking.value = { days };
}

async function confirm() {
  if (!asking.value) return;
  busy.value = true;
  error.value = "";
  try {
    const deleted = await props.clear(asking.value.days);
    asking.value = null;
    emit("done", deleted);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <MoreMenu :label="t('journal.menu')" down>
    <button v-for="days in PERIODS" :key="days" type="button" @click="ask(days)">
      <AppIcon name="history" />{{ t("journal.older", { days }) }}
    </button>
    <button type="button" class="danger-item" @click="ask(null)">
      <AppIcon name="trash" />{{ t("journal.clear_all") }}
    </button>
  </MoreMenu>

  <ModalDialog v-if="asking" :title="t('journal.confirm_title')" @close="asking = null">
    <p class="question">
      {{
        asking.days === null
          ? t("journal.confirm_all", { what, count: count(null) })
          : t("journal.confirm_older", { what, days: asking.days, count: count(asking.days) })
      }}
    </p>
    <p v-if="note" class="muted small">{{ note }}</p>
    <p class="muted small">{{ t("journal.irreversible") }}</p>
    <div v-if="error" class="error">{{ error }}</div>
    <div class="row">
      <button type="button" class="danger solid" :disabled="busy" @click="confirm">
        <AppIcon name="trash" />{{ t("journal.delete") }}
      </button>
      <button type="button" class="ghost" @click="asking = null">{{ t("form.cancel") }}</button>
    </div>
  </ModalDialog>
</template>

<style scoped>
.question {
  margin: 0;
}

.danger-item {
  color: var(--danger);
}
</style>
