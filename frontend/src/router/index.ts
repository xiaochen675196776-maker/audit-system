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
      path: '/data/standard-accounts',
      name: 'standard-accounts',
      component: () => import('@/views/StandardAccountsView.vue'),
    },
    {
      path: '/data/view',
      name: 'data-view',
      component: () => import('@/views/DataView.vue'),
    },
  ],
})

export default router
