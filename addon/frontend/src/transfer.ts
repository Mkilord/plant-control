// Сохранение экспорта машин в файл.
import { api } from "./api";

export async function downloadMachines(ids?: string[], name = "plant-control-machines"): Promise<void> {
  const bundle = await api.exportMachines(ids);
  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
  const date = new Date().toISOString().slice(0, 10);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${name}-${date}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}
