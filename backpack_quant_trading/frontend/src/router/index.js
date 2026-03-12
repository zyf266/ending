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
      { path: 'stock-ai', name: 'StockAi', component: () => import('../views/StockAi.vue') },
      // 暂时切换为新的概览布局（倒三角卡片），便于对比效果
      { path: 'strategies', name: 'StrategyMatrix', component: () => import('../views/StrategyMatrixAlt.vue') },
      { path: 'strategies/eth-trend', name: 'EthTrendStrategy', component: () => import('../views/EthTrendStrategy.vue') },
      { path: 'strategies/paxg-trend', name: 'PaxgTrendStrategy', component: () => import('../views/PaxgTrendStrategy.vue') },
      { path: 'strategies/nas100-trend', name: 'Nas100TrendStrategy', component: () => import('../views/Nas100TrendStrategy.vue') },
      { path: 'okx-agent', name: 'OkxAgent', component: () => import('../views/OkxAgent.vue') },
      { path: 'okx-console', name: 'OkxConsole', component: () => import('../views/OkxConsole.vue') },
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
