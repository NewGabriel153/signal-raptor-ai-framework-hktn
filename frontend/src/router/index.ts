import { createRouter, createWebHistory } from 'vue-router';
import DashboardView from '../views/Dashboard.vue';

const routes = [
  {
    path: '/',
    name: 'dashboard',
    component: DashboardView,
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;