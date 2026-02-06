<template>
  <div class="login-page">
    <div class="login-bg"></div>
    <div class="login-card">
      <div class="login-brand">
        <div class="brand-icon">◈</div>
        <h1>沐龙量化</h1>
        <p>Quantitative Trading Platform</p>
      </div>
      <el-tabs v-model="activeTab" class="login-tabs">
        <el-tab-pane label="登录" name="login">
          <el-form :model="form" label-width="0" @submit.prevent="handleLogin">
            <el-form-item>
              <el-input v-model="form.username" placeholder="用户名" size="large" />
            </el-form-item>
            <el-form-item>
              <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password @keyup.enter="handleLogin" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="handleLogin">登录</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="注册" name="register">
          <el-form :model="form" label-width="0" @submit.prevent="handleRegister">
            <el-form-item>
              <el-input v-model="form.username" placeholder="用户名" size="large" />
            </el-form-item>
            <el-form-item>
              <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="success" size="large" style="width: 100%" :loading="loading" @click="handleRegister">注册</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
      <el-alert v-if="message" :title="message" :type="messageType" show-icon style="margin-top: 12px" />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, register } from '../api/auth'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const activeTab = ref('login')
const loading = ref(false)
const message = ref('')
const messageType = ref('success')
const form = reactive({ username: '', password: '' })

async function handleLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  message.value = ''
  try {
    const res = await login(form)
    userStore.setAuth(res.access_token, res.user)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (e) {
    message.value = e.response?.data?.detail || '登录失败'
    messageType.value = 'error'
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  message.value = ''
  try {
    const res = await register(form)
    userStore.setAuth(res.access_token, res.user)
    ElMessage.success('注册成功')
    router.push('/')
  } catch (e) {
    message.value = e.response?.data?.detail || '注册失败'
    messageType.value = 'error'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  background: linear-gradient(165deg, #f4f6f9 0%, #e8eef4 50%, #dbeafe 100%);
}
.login-bg {
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(circle at 20% 30%, rgba(13, 148, 136, 0.06) 0%, transparent 50%),
    radial-gradient(circle at 80% 70%, rgba(8, 145, 178, 0.06) 0%, transparent 50%),
    linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.8) 100%);
  pointer-events: none;
}
.login-card {
  width: 420px;
  padding: 48px 44px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06), 0 0 0 1px rgba(255,255,255,0.8);
  position: relative;
  backdrop-filter: blur(12px);
}
.login-brand {
  text-align: center;
  margin-bottom: 32px;
}
.brand-icon {
  font-size: 32px;
  color: var(--color-primary);
  margin-bottom: 12px;
  letter-spacing: 2px;
}
.login-brand h1 {
  font-size: 22px;
  font-weight: 700;
  color: #1a2332;
  margin: 0 0 4px 0;
  letter-spacing: -0.02em;
}
.login-brand p {
  font-size: 13px;
  color: #8b99a8;
  margin: 0;
}
.login-tabs :deep(.el-tabs__header) { margin-bottom: 24px; }
.login-tabs :deep(.el-tabs__nav-wrap::after) { display: none; }
.login-tabs :deep(.el-tabs__item) { font-weight: 600; }
.login-tabs :deep(.el-tabs__indicator) { height: 3px; border-radius: 2px; }
.login-tabs :deep(.el-form-item) { margin-bottom: 20px; }
.login-tabs :deep(.el-input__wrapper) { padding: 12px 16px; border-radius: 10px; }
.login-tabs :deep(.el-button--primary) { height: 48px; font-weight: 600; border-radius: 10px; }
.login-tabs :deep(.el-button--success) { height: 48px; font-weight: 600; border-radius: 10px; }
</style>
