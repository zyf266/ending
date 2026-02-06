import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { guest: true } },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/trading' },
      { path: 'trading', name: 'Trading', component: () => import('../views/Trading.vue') },
      { path: 'dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'ai-lab', name: 'AiLab', component: () => import('../views/AiLab.vue') },
      { path: 'grid-trading', name: 'GridTrading', component: () => import('../views/GridTrading.vue') },
      { path: 'currency-monitor', name: 'CurrencyMonitor', component: () => import('../views/CurrencyMonitor.vue') },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else if (to.meta.guest && token) {
    next('/')
  } else {
    next()
  }
})

export default router
