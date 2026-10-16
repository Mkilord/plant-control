<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api, type Health, type Problem } from "./api";
import AppIcon, { type IconName } from "./components/AppIcon.vue";
import BrandLogo from "./components/BrandLogo.vue";
import { LOCALES, locale, t, theme, type Theme, type MessageKey } from "./i18n";

const version = __APP_VERSION__;
const REPO_URL = "https://github.com/Mkilord/plant-control";
const route = useRoute();

// Шапка следит за тем, что важно всегда: есть ли связь с HA и открытые проблемы.
const problems = ref<Problem[]>([]);
const health = ref<Health | null>(null);
let timer: number | undefined;

async function poll() {
  try {
    const [list, status] = await Promise.all([api.problems(), api.health()]);
    problems.value = list.filter((p) => !p.muted_until);
    health.value = status;
  } catch {
    // Молча: шапка не должна мешать работе с интерфейсом.
  }
}

onMounted(async () => {
  await poll();
  timer = window.setInterval(() => {
    if (!document.hidden) void poll();
  }, 5000);
});
onUnmounted(() => window.clearInterval(timer));

// Красный счётчик - полив где-то невозможен, жёлтый - есть на что посмотреть.
const problemTone = computed(() => (problems.value.some((p) => p.blocking) ? "danger" : "warn"));

const haOk = computed(() => health.value?.home_assistant === "connected");
const haTitle = computed(() =>
  !health.value
    ? ""
    : haOk.value
      ? t("list.ha_connected")
      : t("list.ha_status", { status: health.value.home_assistant }),
);

interface Tab {
  to: string;
  label: MessageKey;
  icon: IconName;
  // Какие адреса относятся к вкладке: форма машины - это раздел "Машины".
  match: (path: string) => boolean;
}

const tabs: Tab[] = [
  { to: "/", label: "nav.machines", icon: "can", match: (p) => p === "/" || p.startsWith("/machines") },
  { to: "/waterings", label: "nav.waterings", icon: "calendar", match: (p) => p.startsWith("/waterings") },
  { to: "/catalog", label: "nav.catalog", icon: "tank", match: (p) => p.startsWith("/catalog") },
  { to: "/problems", label: "nav.problems", icon: "alert", match: (p) => p.startsWith("/problems") },
];

const themes: { value: Theme; icon: IconName }[] = [
  { value: "auto", icon: "monitor" },
  { value: "light", icon: "sun" },
  { value: "dark", icon: "moon" },
];
</script>

<template>
  <div class="layout">
    <header class="header">
      <div class="header-inner">
        <RouterLink to="/" class="brand" :aria-label="t('app.title')">
          <BrandLogo :size="28" />
          <span class="brand-name">Plant<b>Control</b></span>
        </RouterLink>

        <nav class="tabs">
          <RouterLink
            v-for="tab in tabs"
            :key="tab.to"
            :to="tab.to"
            class="tab"
            :class="{ active: tab.match(route.path) }"
            :aria-current="tab.match(route.path) ? 'page' : undefined"
          >
            <AppIcon :name="tab.icon" :size="19" />
            <span class="tab-label">{{ t(tab.label) }}</span>
            <span
              v-if="tab.to === '/problems' && problems.length"
              class="count"
              :class="problemTone"
            >
              {{ problems.length }}
            </span>
          </RouterLink>
        </nav>

        <span class="spacer" />

        <span
          v-if="health"
          class="ha"
          :class="haOk ? 'ok' : 'bad'"
          :title="haTitle"
          :aria-label="haTitle"
        >
          <span class="ha-dot" />
          <span class="ha-label">HA</span>
        </span>

        <RouterLink
          to="/settings"
          class="tab icon-only"
          :class="{ active: route.path.startsWith('/settings') }"
          :title="t('nav.settings')"
          :aria-label="t('nav.settings')"
        >
          <AppIcon name="settings" :size="20" />
        </RouterLink>
      </div>
    </header>

    <main class="content">
      <RouterView />
    </main>

    <footer class="footer">
      <div class="footer-inner">
        <span class="muted">{{ t("app.version", { version }) }}</span>
        <a class="muted source" :href="REPO_URL" target="_blank" rel="noopener noreferrer">
          {{ t("app.source") }}
        </a>
        <span class="spacer" />
        <label class="lang">
          <AppIcon name="globe" :size="16" />
          <select v-model="locale" :aria-label="t('app.language')">
            <option v-for="l in LOCALES" :key="l.code" :value="l.code">{{ l.label }}</option>
          </select>
        </label>
        <div class="segmented" role="group" :aria-label="t('app.theme')">
          <button
            v-for="option in themes"
            :key="option.value"
            type="button"
            :class="{ active: theme === option.value }"
            :aria-pressed="theme === option.value"
            :title="t(`theme.${option.value}`)"
            :aria-label="t(`theme.${option.value}`)"
            @click="theme = option.value"
          >
            <AppIcon :name="option.icon" :size="16" />
          </button>
        </div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  position: sticky;
  top: 0;
  z-index: 10;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--card) 92%, transparent);
  backdrop-filter: blur(8px);
}

.header-inner {
  max-width: 1100px;
  margin: 0 auto;
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  margin-right: 14px;
  color: var(--text);
  text-decoration: none;
  font-size: 16px;
  letter-spacing: -0.01em;
}

.brand-name b {
  color: var(--accent-plant);
}

.tabs {
  display: flex;
  gap: 2px;
}

.tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  color: var(--muted);
  text-decoration: none;
  transition:
    background 0.15s,
    color 0.15s;
}

.tab:hover {
  color: var(--text);
  background: var(--bg);
}

.tab.active {
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
}

.tab.icon-only {
  padding: 8px;
}

.count {
  min-width: 19px;
  height: 19px;
  padding: 0 5px;
  border-radius: 10px;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  line-height: 19px;
  text-align: center;
}

.count.danger {
  background: var(--danger);
}

.count.warn {
  background: var(--warn);
}

.spacer {
  flex: 1;
}

.ha {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.ha-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 25%, transparent);
}

.ha.bad {
  color: var(--danger);
  border-color: var(--danger);
}

.ha.bad .ha-dot {
  background: var(--danger);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 25%, transparent);
  animation: blink 1.4s ease-in-out infinite;
}

@keyframes blink {
  50% {
    opacity: 0.35;
  }
}

.content {
  flex: 1;
}

.footer {
  border-top: 1px solid var(--border);
  background: var(--card);
  font-size: 13px;
}

.footer-inner {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  max-width: 1100px;
  margin: 0 auto;
  padding: 12px 16px;
}

.source {
  text-decoration: none;
}

.source:hover {
  text-decoration: underline;
}

.lang {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--muted);
}

.lang select {
  width: auto;
  padding: 4px 6px;
  font-size: 13px;
}

.segmented {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.segmented button {
  border: none;
  border-radius: 0;
  padding: 5px 8px;
}

.segmented button + button {
  border-left: 1px solid var(--border);
}

.segmented button.active {
  background: var(--primary);
  color: var(--primary-text);
}

/* Узкий экран: сначала уходит название, потом подписи неактивных вкладок. */
@media (max-width: 720px) {
  .brand-name {
    display: none;
  }

  .brand {
    margin-right: 4px;
  }
}

@media (max-width: 520px) {
  .header-inner {
    padding: 8px 10px;
    gap: 4px;
  }

  .tab {
    padding: 8px 9px;
  }

  .tab:not(.active) .tab-label {
    display: none;
  }

  .ha-label {
    display: none;
  }

  .ha {
    padding: 6px;
  }
}
</style>
