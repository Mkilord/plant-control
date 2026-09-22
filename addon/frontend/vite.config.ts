import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  // Относительные пути: внутри Home Assistant интерфейс открывается
  // по адресу вида /api/hassio_ingress/<токен>/, заранее он неизвестен.
  base: "./",
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // В разработке запросы к API уходят на бэкенд, запущенный отдельно.
    proxy: { "/api": "http://localhost:8099" },
  },
});
