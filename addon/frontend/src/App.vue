<script setup lang="ts">
import AppIcon, { type IconName } from "./components/AppIcon.vue";
import { LOCALES, locale, t, theme, type Theme } from "./i18n";

const version = __APP_VERSION__;
const themes: { value: Theme; icon: IconName }[] = [
  { value: "auto", icon: "monitor" },
  { value: "light", icon: "sun" },
  { value: "dark", icon: "moon" },
];
</script>

<template>
  <div class="layout">
    <main class="content">
      <RouterView />
    </main>

    <footer class="footer">
      <div class="footer-inner">
        <span class="brand">
          <span class="logo"><AppIcon name="droplet" :size="14" /></span>
          PlantControl
        </span>
        <span class="muted">{{ t("app.version", { version }) }}</span>
        <span class="muted">{{ t("app.author") }}</span>
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

.brand {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  color: #fff;
  background: linear-gradient(135deg, var(--accent-tank), var(--accent-plant));
}

.spacer {
  flex: 1;
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
</style>
