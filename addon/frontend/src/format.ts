export function ml(value: number): string {
  return `${Math.round(value)} мл`;
}

export function seconds(value: number): string {
  return value < 10 ? `${value.toFixed(1)} с` : `${Math.round(value)} с`;
}

export function time(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
