import vue from "@vitejs/plugin-vue";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8")) as {
  version: string;
};

export default defineConfig({
  plugins: [vue()],
  // Версия приложения подставляется при сборке. В образе её передаёт Dockerfile
  // из config.yaml (APP_VERSION), при разработке берётся из package.json.
  define: { __APP_VERSION__: JSON.stringify(process.env.APP_VERSION || pkg.version) },
  // Относительные пути: внутри Home Assistant интерфейс открывается
  // по адресу вида /api/hassio_ingress/<токен>/, заранее он неизвестен.
  base: "./",
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // В разработке запросы к API уходят на бэкенд, запущенный отдельно.
    proxy: { "/api": "http://localhost:8099" },
  },
});
