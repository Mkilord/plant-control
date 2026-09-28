import { createRouter, createWebHashHistory } from "vue-router";
import MachineForm from "./views/MachineForm.vue";
import MachinesView from "./views/MachinesView.vue";
import ProblemsView from "./views/ProblemsView.vue";
import QueueView from "./views/QueueView.vue";

// Hash-роутинг (#/machines/new): адрес страницы внутри Ingress не меняется,
// и HA не нужно знать о маршрутах интерфейса.
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", component: MachinesView },
    { path: "/machines/new", component: MachineForm },
    { path: "/machines/:id", component: MachineForm, props: true },
    { path: "/queue", component: QueueView },
    { path: "/problems", component: ProblemsView },
  ],
});
