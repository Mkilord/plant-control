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
