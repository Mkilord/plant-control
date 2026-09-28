<script setup lang="ts">
// Набор простых линейных иконок 24x24. Рисуются обводкой текущего цвета текста.
export type IconName =
  | "droplet"
  | "tank"
  | "pump"
  | "tube"
  | "plant"
  | "collector"
  | "settings"
  | "info"
  | "play"
  | "stop"
  | "back"
  | "plus"
  | "trash"
  | "sun"
  | "moon"
  | "monitor"
  | "globe"
  | "clock"
  | "sliders"
  | "check"
  | "alert"
  | "calculator"
  | "refill"
  | "edit";

const PATHS: Record<IconName, string[]> = {
  droplet: ["M12 3.5c3.2 4.2 6 7.6 6 10.9a6 6 0 0 1-12 0c0-3.3 2.8-6.7 6-10.9z"],
  tank: ["M6 4h12v16a0 0 0 0 1 0 0H6z", "M6 12.5c2-1.2 4-1.2 6 0s4 1.2 6 0"],
  pump: [
    "M12 12m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0",
    "M12 12c0-3 1.5-5 4-5",
    "M12 12c3 0 5 1.5 5 4",
    "M12 12c0 3-1.5 5-4 5",
    "M12 12c-3 0-5-1.5-5-4",
  ],
  tube: ["M3 7h8a6 6 0 0 1 6 6v8", "M3 11h8a2 2 0 0 1 2 2v8"],
  plant: [
    "M12 21v-9",
    "M12 12c0-4.4 3-7.5 8-7.5 0 5-3.2 8-8 7.5z",
    "M12 15c0-3.3-2.3-5.5-6.5-5.5 0 4 2.3 6 6.5 5.5z",
  ],
  collector: ["M12 3v5", "M5 8h14", "M5 8v6", "M12 8v6", "M19 8v6", "M4 17h2M11 17h2M18 17h2"],
  settings: [
    "M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0-6 0",
    "M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1",
  ],
  info: ["M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0-18 0", "M12 11v6", "M12 7.5v.5"],
  play: ["M8 5.5l10 6.5-10 6.5z"],
  stop: ["M7 7h10v10H7z"],
  back: ["M15 5l-7 7 7 7"],
  plus: ["M12 5v14", "M5 12h14"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13", "M10 11v6M14 11v6"],
  sun: [
    "M12 12m-4 0a4 4 0 1 0 8 0a4 4 0 1 0-8 0",
    "M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  ],
  moon: ["M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"],
  monitor: ["M3 5h18v11H3z", "M8 20h8", "M12 16v4"],
  globe: [
    "M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0-18 0",
    "M3 12h18",
    "M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z",
  ],
  clock: ["M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0-18 0", "M12 7v5l3 2"],
  sliders: [
    "M4 7h9M17 7h3",
    "M15 7m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0",
    "M4 17h3M11 17h9",
    "M9 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0",
  ],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  alert: ["M12 4l9 16H3z", "M12 10v4", "M12 17v.5"],
  calculator: ["M6 3h12v18H6z", "M9 7h6", "M9 12h.01M12 12h.01M15 12h.01M9 16h.01M12 16h.01M15 16h.01"],
  edit: ["M4 20h4L19 9l-4-4L4 16z", "M13.5 6.5l4 4"],
  refill: ["M12 3.5c2.6 3.4 5 6.2 5 9a5 5 0 0 1-10 0c0-2.8 2.4-5.6 5-9z", "M12 11v5", "M9.5 13.5h5"],
};

withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 18 });
</script>

<template>
  <svg
    class="icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="(d, i) in PATHS[name]" :key="i" :d="d" />
  </svg>
</template>

<style scoped>
.icon {
  flex: none;
  vertical-align: middle;
}
</style>
