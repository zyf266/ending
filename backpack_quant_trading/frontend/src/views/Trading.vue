<template>
  <div class="page trading-page">
    <div class="header-row">
      <h2>实盘控制中心</h2>
      <el-button type="primary" @click="showModal = true">+ 增加新策略</el-button>
    </div>

    <el-card class="instances-card">
      <template #header>运行中的策略实例 (ACTIVE INSTANCES)</template>
      <div v-if="instances.length === 0" class="empty">暂无运行中的策略，请增加新策略</div>
      <div v-else class="instance-grid">
        <div v-for="inst in instances" :key="inst.id" class="instance-card">
          <div class="inst-info">
            <div class="tags">
              <el-tag size="small" :type="inst.platform === 'ostium' ? 'warning' : ''">{{ inst.platform?.toUpperCase() }}</el-tag>
              <span :class="['status', inst.status === 'registering' ? 'reg' : 'run']">
                {{ inst.status === 'registering' ? '● REGISTERING' : '● RUNNING' }}
              </span>
            </div>
            <h3>{{ inst.strategy_name }}</h3>
            <p>💹 {{ inst.symbol }}</p>
            <p class="meta">🕒 {{ inst.start_time }} | PID: {{ inst.pid }}</p>
          </div>
          <div class="inst-actions">
            <div class="balance">
              <p>💰 账户余额</p>
              <h2>{{ inst.balance }} USD</h2>
            </div>
            <el-button type="danger" size="small" @click="stopOne(inst.id)">停止</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <el-card class="log-card">
      <template #header>终端实时输出日志 (SYSTEM LOGS)</template>
      <pre class="log-content">{{ logs }}</pre>
    </el-card>

    <!-- 增加策略弹窗 -->
    <el-dialog v-model="showModal" title="配置并启动实盘策略" width="700px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="交易平台">
          <el-select v-model="form.platform" style="width: 100%">
            <el-option label="Backpack" value="backpack" />
            <el-option label="Deepcoin" value="deepcoin" />
            <el-option label="Ostium" value="ostium" />
            <el-option label="Hyperliquid" value="hyperliquid" />
          </el-select>
        </el-form-item>
        <el-form-item label="交易策略">
          <el-select v-model="form.strategy" style="width: 100%">
            <el-option v-for="s in strategies" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <template v-if="['backpack', 'deepcoin'].includes(form.platform)">
          <el-form-item label="API Key">
            <el-input v-model="form.api_key" type="password" show-password placeholder="输入 API Key" />
          </el-form-item>
          <el-form-item label="API Secret">
            <el-input v-model="form.api_secret" type="password" show-password placeholder="输入 API Secret" />
          </el-form-item>
          <el-form-item v-if="form.platform === 'deepcoin'" label="Passphrase">
            <el-input v-model="form.passphrase" type="password" placeholder="输入 Passphrase" />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="Private Key">
            <el-input v-model="form.private_key" type="password" show-password placeholder="输入 0x 开头的私钥" />
          </el-form-item>
        </template>
        <el-form-item label="交易对">
          <el-input v-model="form.symbol" placeholder="ETH/USDC" />
        </el-form-item>
        <el-form-item label="下单保证金">
          <el-input-number v-model="form.size" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="杠杆倍数">
          <el-input-number v-model="form.leverage" :min="1" :max="100" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="isDualFreq ? '止盈(保证金收益%)' : '止盈比例 (%)'">
          <el-input-number v-model="form.take_profit" :min="0" :max="isDualFreq ? 300 : 100" :precision="1" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="isDualFreq ? '止损(保证金收益%)' : '止损比例 (%)'">
          <el-input-number v-model="form.stop_loss" :min="0" :max="isDualFreq ? 200 : 100" :precision="1" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button type="danger" @click="showModal = false">取消</el-button>
          <el-button type="primary" :loading="launching" @click="handleLaunch">确认启动实盘进程</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getStrategies, getInstances, launchStrategy, stopInstance, getLogs } from '../api/trading'

const showModal = ref(false)
const instances = ref([])
const logs = ref('等待日志输出...')
const strategies = ref([])
const launching = ref(false)

const form = reactive({
  platform: 'backpack',
  strategy: 'mean_reversion',
  symbol: 'ETH/USDC',
  size: 20,
  leverage: 50,
  take_profit: 2.0,
  stop_loss: 1.5,
  api_key: '',
  api_secret: '',
  passphrase: '',
  private_key: '',
})

const isDualFreq = computed(() => form.strategy === 'dual_freq_trend')

// dual_freq_trend：止盈/止损按 Pine 语义（保证金收益%）
watch(
  () => form.strategy,
  (v, prev) => {
    if (v === 'dual_freq_trend' && prev !== 'dual_freq_trend') {
      form.leverage = 100
      form.size = 10
      form.take_profit = 150.0
      form.stop_loss = 50.0
    }
  }
)

const intervalIds = []
onUnmounted(() => {
  intervalIds.forEach(clearInterval)
})
onMounted(async () => {
  try {
    const res = await getStrategies()
    strategies.value = res.strategies || []
  } catch {}
  await refresh()
  intervalIds.push(setInterval(refresh, 5000), setInterval(refreshLogs, 10000))
})

async function refresh() {
  try {
    const res = await getInstances()
    instances.value = res.instances || []
  } catch {}
}

async function refreshLogs() {
  try {
    const res = await getLogs()
    logs.value = res.logs || '等待日志输出...'
  } catch {}
}

async function handleLaunch() {
  if (['backpack', 'deepcoin'].includes(form.platform)) {
    if (!form.api_key || !form.api_secret) {
      ElMessage.warning('请输入 API Key 和 Secret')
      return
    }
  } else {
    if (!form.private_key) {
      ElMessage.warning('请输入私钥')
      return
    }
  }
  launching.value = true
  try {
    const res = await launchStrategy({
      platform: form.platform,
      strategy: form.strategy,
      symbol: form.symbol,
      size: form.size,
      leverage: form.leverage,
      take_profit: form.take_profit,
      stop_loss: form.stop_loss,
      api_key: form.api_key || undefined,
      api_secret: form.api_secret || undefined,
      passphrase: form.passphrase || undefined,
      private_key: form.private_key || undefined,
    })
    ElMessage.success(res.message || '启动成功')
    showModal.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '启动失败')
  } finally {
    launching.value = false
  }
}

async function stopOne(id) {
  try {
    await stopInstance(id)
    ElMessage.success('已停止')
    await refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '停止失败')
  }
}
</script>

<style scoped>
.header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.header-row h2 { margin: 0; font-size: 24px; color: var(--color-text); font-weight: 700; letter-spacing: -0.02em; }
.instances-card, .log-card { margin-bottom: 24px; }
.instances-card :deep(.el-card__body), .log-card :deep(.el-card__body) { padding: 20px; }
.instance-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
.instance-card {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px; border: 1px solid var(--color-border); border-radius: var(--radius-md);
  background: var(--color-bg-card); box-shadow: var(--shadow-sm); transition: box-shadow 0.2s;
}
.instance-card:hover { box-shadow: var(--shadow-md); }
.inst-info h3 { margin: 0 0 8px 0; font-size: 15px; font-weight: 600; color: var(--color-text); }
.inst-info p { margin: 0 0 4px 0; font-size: 13px; color: var(--color-text-secondary); }
.inst-info .meta { font-size: 11px; color: var(--color-text-muted); }
.tags { margin-bottom: 10px; }
.status.run { color: var(--color-success); font-size: 11px; font-weight: 600; margin-left: 8px; }
.status.reg { color: var(--color-warning); font-size: 11px; font-weight: 600; margin-left: 8px; }
.inst-actions { min-width: 120px; text-align: right; }
.balance p { margin: 0; font-size: 11px; color: var(--color-text-muted); }
.balance h2 { margin: 6px 0 12px 0; font-size: 17px; color: var(--color-primary); font-weight: 700; }
.empty { text-align: center; padding: 48px; color: var(--color-text-muted); font-size: 14px; }
.log-content {
  background: #1e293b; color: #e2e8f0; padding: 20px; border-radius: var(--radius-md);
  height: 400px; overflow-y: auto; font-size: 12px; font-family: var(--font-mono);
  white-space: pre-wrap; margin: 0; line-height: 1.7;
}
.dialog-footer {
  display: flex;
  justify-content: center;
  gap: 24px;
}
</style>
