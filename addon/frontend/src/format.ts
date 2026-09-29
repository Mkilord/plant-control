import { locale, t } from "./i18n";

export function ml(value: number): string {
  return `${Math.round(value)} ${t("unit.ml")}`;
}

export function seconds(value: number): string {
  const number = value < 10 ? value.toFixed(1) : String(Math.round(value));
  return `${number} ${t("unit.s")}`;
}

export function time(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(locale.value === "ru" ? "ru-RU" : "en-GB", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

// "Сегодня", "Завтра", "Вчера" или "пн, 5 окт." - заголовок дня в списках.
export function dayLabel(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  for (const [shift, key] of [
    [0, "day.today"],
    [1, "day.tomorrow"],
    [-1, "day.yesterday"],
  ] as const) {
    const day = new Date(now);
    day.setDate(now.getDate() + shift);
    if (sameDay(date, day)) return t(key);
  }
  return date.toLocaleDateString(locale.value === "ru" ? "ru-RU" : "en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

// "14:05"
export function clock(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString(locale.value === "ru" ? "ru-RU" : "en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Длительность: "45 с", "3:05", "1 ч 20 мин".
export function span(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s} ${t("unit.s")}`;
  if (s < 3600) return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const minutes = Math.round(s / 60);
  return minutes % 60
    ? t("unit.h_min", { h: Math.floor(minutes / 60), m: minutes % 60 })
    : t("unit.h", { h: minutes / 60 });
}

// "через 2 ч 15 мин", "через 5 мин", "сейчас".
export function untilText(iso: string, now: Date = new Date()): string {
  const minutes = Math.round((new Date(iso).getTime() - now.getTime()) / 60000);
  if (minutes <= 0) return t("time.now");
  if (minutes < 60) return t("time.in_min", { m: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return minutes % 60 ? t("time.in_h_min", { h: hours, m: minutes % 60 }) : t("time.in_h", { h: hours });
  }
  return t("time.in_days", { d: Math.round(hours / 24) });
}

// Группировка по дням с сохранением порядка.
export function byDay<T>(items: T[], at: (item: T) => string): { label: string; items: T[] }[] {
  const groups: { label: string; items: T[] }[] = [];
  for (const item of items) {
    const label = dayLabel(at(item));
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}
