import { createRouter, createWebHashHistory } from "vue-router";
import CalibrationView from "./views/CalibrationView.vue";
import MachineForm from "./views/MachineForm.vue";
import MachinesView from "./views/MachinesView.vue";
import ProblemsView from "./views/ProblemsView.vue";
import SettingsView from "./views/SettingsView.vue";
import WateringsView from "./views/WateringsView.vue";

// Hash-роутинг (#/machines/new): адрес страницы внутри Ingress не меняется,
// и HA не нужно знать о маршрутах интерфейса.
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", component: MachinesView },
    { path: "/machines/new", component: MachineForm },
    { path: "/machines/:id/calibrate", component: CalibrationView, props: true },
    { path: "/machines/:id", component: MachineForm, props: true },
    { path: "/waterings", component: WateringsView },
    // Старый адрес вкладки: закладки не должны ломаться.
    { path: "/queue", redirect: "/waterings" },
    { path: "/problems", component: ProblemsView },
    { path: "/settings", component: SettingsView },
  ],
});
