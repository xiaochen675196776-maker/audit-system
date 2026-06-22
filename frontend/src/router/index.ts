import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
    },
    {
      path: '/data/import',
      name: 'data-import',
      component: () => import('@/views/DataImportView.vue'),
    },
    {
      path: '/data/companies',
      name: 'companies',
      component: () => import('@/views/CompaniesView.vue'),
    },
    {
      path: '/data/templates',
      name: 'templates',
      component: () => import('@/views/ImportTemplatesView.vue'),
    },
  ],
})

export default router
