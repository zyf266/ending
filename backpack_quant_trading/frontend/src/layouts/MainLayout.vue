<template>
  <div class="main-layout">
    <aside class="sidebar">
      <div class="logo">
        <div class="logo-icon">◈</div>
        <h3>沐龙量化</h3>
        <p>{{ userStore.user?.role === 'superuser' ? 'Admin' : 'User' }} · v1.0</p>
      </div>
      <nav class="nav">
        <router-link to="/trading" class="nav-link" active-class="active">
          <span class="nav-icon">⚡</span> 实盘交易
        </router-link>
        <router-link to="/dashboard" class="nav-link" active-class="active">
          <span class="nav-icon">📊</span> 数据大屏
        </router-link>
        <router-link to="/ai-lab" class="nav-link" active-class="active">
          <span class="nav-icon">🤖</span> AI 实验室
        </router-link>
        <router-link to="/grid-trading" class="nav-link" active-class="active">
          <span class="nav-icon">🎯</span> 合约网格
        </router-link>
        <router-link to="/currency-monitor" class="nav-link" active-class="active">
          <span class="nav-icon">🔔</span> 币种监视
        </router-link>
      </nav>
    </aside>
    <div class="content">
      <header class="header">
        <span class="user-info">
          <span class="dot"></span>
          {{ userStore.user?.username }}
        </span>
        <el-button type="danger" size="small" @click="handleLogout">退出系统</el-button>
      </header>
      <main class="page-content">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </main>
    </div>
    <Teleport to="body">
      <ChatBot />
    </Teleport>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import ChatBot from '../components/ChatBot.vue'

const router = useRouter()
const userStore = useUserStore()

onMounted(() => {
  if (userStore.token && !userStore.user) {
    userStore.fetchUser()
  }
})

function handleLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.main-layout { display: flex; min-height: 100vh; }
.sidebar {
  width: 240px;
  background: var(--color-sidebar);
  border-right: 1px solid var(--color-border);
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 12px rgba(0,0,0,0.02);
}
.logo {
  text-align: center;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 24px;
}
.logo-icon {
  font-size: 24px;
  color: var(--color-primary);
  margin-bottom: 8px;
  letter-spacing: 1px;
}
.logo h3 {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-primary);
  margin: 0;
  letter-spacing: -0.02em;
}
.logo p {
  font-size: 11px;
  color: var(--color-text-muted);
  margin: 4px 0 0 0;
}
.nav { flex: 1; }
.nav-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  color: var(--color-text-secondary);
  text-decoration: none;
  border-radius: var(--radius-md);
  margin-bottom: 4px;
  font-weight: 500;
  transition: all 0.2s;
}
.nav-link:hover {
  background: var(--color-sidebar-hover);
  color: var(--color-text);
}
.nav-link.active {
  background: var(--color-sidebar-active);
  color: var(--color-sidebar-active-text);
  font-weight: 600;
}
.nav-icon { font-size: 16px; }
.content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.header {
  height: 60px;
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border);
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  box-shadow: var(--shadow-sm);
}
.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
}
.dot {
  width: 8px;
  height: 8px;
  background: var(--color-success);
  border-radius: 50%;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.3);
}
.page-content {
  flex: 1;
  overflow-y: auto;
  padding: 28px;
  background: var(--color-bg);
}
</style>
