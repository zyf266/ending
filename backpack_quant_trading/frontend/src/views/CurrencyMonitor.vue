<template>
  <div class="page monitor-page">
    <div class="title-row">
      <h2>币种监视</h2>
    </div>

    <el-card>
      <template #header>监视配置</template>
      <el-form inline class="config-form">
        <el-form-item label="选择币种">
          <el-select
            v-model="selectedSymbols"
            multiple
            filterable
            :filter-method="handleSymbolFilter"
            placeholder="选择币种"
            class="symbol-select"
            @visible-change="handleSymbolDropdown"
          >
            <el-option v-for="s in filteredSymbols" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="K线级别(多选)">
          <el-checkbox-group v-model="selectedTimeframes" class="timeframe-group">
            <el-checkbox v-for="opt in timeframeOptions" :key="opt.value" :label="opt.value">
              {{ opt.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item class="btn-row">
          <el-button type="primary" :loading="loading" @click="handleStart">开始监视</el-button>
          <el-button type="danger" :disabled="!status.running" @click="handleStop">停止监视</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="minute-alert-card">
      <template #header>分钟预警配置</template>
      <el-form :model="minuteForm" label-position="top" class="minute-form">
        <div class="minute-form-grid">
        <el-form-item label="监控币种" class="minute-symbols">
          <el-select
            v-model="minuteForm.symbols"
            multiple
            filterable
            :filter-method="handleMinuteSymbolFilter"
            placeholder="选择币安合约交易对，如 ETHUSDT"
            class="symbol-select symbol-select-full"
            @visible-change="handleMinuteSymbolDropdown"
          >
            <el-option v-for="s in minuteFilteredSymbols" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>

        <el-form-item label="K线级别" class="minute-interval">
          <el-select v-model="minuteForm.interval" teleported class="w-120">
            <el-option v-for="opt in minuteIntervalOptions" :key="opt" :label="opt" :value="opt" />
          </el-select>
        </el-form-item>

        <el-form-item label="波动阈值(%)" class="minute-vol">
          <el-input-number v-model="minuteForm.vol_pct_threshold" :min="0" :step="0.5" :precision="2" class="w-160" />
        </el-form-item>
        <el-form-item label="量能倍数(x)" class="minute-volume">
          <el-input-number v-model="minuteForm.volume_mult_threshold" :min="1" :step="1" :precision="1" class="w-160" />
        </el-form-item>
        <el-form-item label="订单簿大单(名义USDT)" class="minute-ob">
          <div class="field-with-help">
            <el-input-number v-model="minuteForm.ob_notional_threshold" :min="0" :step="10000" :precision="0" class="w-220" />
            <div class="field-help">
              <template v-if="minuteStatus.running">
                运行中：{{ (minuteStatus.symbols || []).join(', ') }} ｜ interval={{ minuteStatus.interval }} ｜ 波动≥{{ minuteStatus.vol_pct_threshold }}% ｜ 量能≥{{ minuteStatus.volume_mult_threshold }}x ｜ 订单簿≥{{ minuteStatus.ob_notional_threshold }}
              </template>
              <template v-else>
                未启动。启动后每分钟拉取币安K线/订单簿并通过钉钉推送。
              </template>
            </div>
          </div>
        </el-form-item>

        <el-form-item label=" " class="minute-actions">
          <el-button type="primary" size="large" :loading="minuteLoading" @click="handleMinuteStart">启动预警</el-button>
          <el-button type="danger" size="large" :disabled="!minuteStatus.running" @click="handleMinuteStop">停止预警</el-button>
        </el-form-item>
        </div>
      </el-form>
    </el-card>

    <el-card class="pool-card">
      <template #header>监视中的币种 (异动时变红)</template>
      <p v-if="displayPairs.length" class="hint">已有监视时，选择更多币种/级别后点击「开始监视」可追加；点击 × 可移除该项</p>
      <div v-if="displayPairs.length === 0" class="empty">暂无监视，请选择币种和 K 线级别后点击「开始监视」</div>
      <div v-else :class="['pool', { 'pool-alerted': hasAnyAlerted }]">
        <div
          v-for="p in displayPairs"
          :key="`${p[0]}-${p[1]}`"
          :class="['pool-chip', { alerted: isAlerted(p) }]"
          @click.stop
        >
          <span class="chip-symbol">{{ p[0] }}</span>
          <span class="chip-timeframe">{{ p[1] }}</span>
          <button type="button" class="chip-close" aria-label="移除" @click="removePair(p[0], p[1])">×</button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getSymbols,
  getStatus,
  startMonitor,
  stopMonitor,
  removePair as apiRemovePair,
  getMinuteAlertStatus,
  startMinuteAlert,
  stopMinuteAlert,
} from '../api/currencyMonitor'

const symbolList = ref([])
const symbolKeyword = ref('')
const selectedSymbols = ref([])
const timeframeOptions = [
  { label: '1小时', value: '1小时' },
  { label: '2小时', value: '2小时' },
  { label: '4小时', value: '4小时' },
  { label: '天', value: '天' },
  { label: '周', value: '周' },
]
const selectedTimeframes = ref([])
const status = reactive({ running: false, pairs: [] })
const loading = ref(false)
const alertedPairs = ref(new Set())

// 1分钟预警
const minuteSymbolKeyword = ref('')
const minuteLoading = ref(false)
const minuteStatus = reactive({
  running: false,
  symbols: [],
  interval: '1m',
  vol_pct_threshold: 5.0,
  volume_mult_threshold: 20.0,
  ob_notional_threshold: 200000.0,
})
const minuteForm = reactive({
  symbols: [],
  interval: '1m',
  vol_pct_threshold: 5.0,
  volume_mult_threshold: 20.0,
  ob_notional_threshold: 200000.0,
})
const minuteIntervalOptions = ['1m', '3m', '5m', '15m']

onMounted(async () => {
  try {
    const res = await getSymbols()
    symbolList.value = res.symbols || []
  } catch {}
  await refreshStatus()
  await refreshMinuteStatus()
  const t = setInterval(refreshStatus, 5000)
  const t2 = setInterval(refreshMinuteStatus, 5000)
  onUnmounted(() => clearInterval(t))
  onUnmounted(() => clearInterval(t2))
})

async function refreshStatus() {
  try {
    const res = await getStatus()
    status.running = res.running
    status.pairs = Array.isArray(res.pairs) ? res.pairs : []
    alertedPairs.value = new Set(res.alerted || [])
  } catch {}
}

async function refreshMinuteStatus() {
  try {
    const res = await getMinuteAlertStatus()
    minuteStatus.running = !!res.running
    minuteStatus.symbols = Array.isArray(res.symbols) ? res.symbols : []
    minuteStatus.interval = res.interval || '1m'
    minuteStatus.vol_pct_threshold = Number(res.vol_pct_threshold ?? 5.0)
    minuteStatus.volume_mult_threshold = Number(res.volume_mult_threshold ?? 20.0)
    minuteStatus.ob_notional_threshold = Number(res.ob_notional_threshold ?? 200000.0)

    // 回显到表单（仅在未运行时同步，避免你改表单时被刷新覆盖）
    if (!minuteStatus.running) {
      minuteForm.interval = minuteStatus.interval
      minuteForm.vol_pct_threshold = minuteStatus.vol_pct_threshold
      minuteForm.volume_mult_threshold = minuteStatus.volume_mult_threshold
      minuteForm.ob_notional_threshold = minuteStatus.ob_notional_threshold
    }
  } catch {}
}

const displayPairs = computed(() => Array.isArray(status.pairs) ? status.pairs : [])
const filteredSymbols = computed(() => {
  const kw = symbolKeyword.value.trim().toUpperCase()
  if (!kw) return symbolList.value
  return symbolList.value.filter((s) => String(s).toUpperCase().includes(kw))
})

const minuteFilteredSymbols = computed(() => {
  const kw = minuteSymbolKeyword.value.trim().toUpperCase()
  if (!kw) return symbolList.value
  return symbolList.value.filter((s) => String(s).toUpperCase().includes(kw))
})

const hasAnyAlerted = computed(() => {
  return displayPairs.value.some((p) => alertedPairs.value.has(`${p[0]}|${p[1]}`))
})

function isAlerted(p) {
  return alertedPairs.value.has(`${p[0]}|${p[1]}`)
}

function handleSymbolFilter(query) {
  symbolKeyword.value = query || ''
}

function handleSymbolDropdown(visible) {
  if (!visible) symbolKeyword.value = ''
}

function handleMinuteSymbolFilter(query) {
  minuteSymbolKeyword.value = query || ''
}

function handleMinuteSymbolDropdown(visible) {
  if (!visible) minuteSymbolKeyword.value = ''
}

async function handleStart() {
  if (!selectedSymbols.value.length || !selectedTimeframes.value.length) {
    ElMessage.warning('请选择币种和 K 线级别')
    return
  }
  loading.value = true
  try {
    await startMonitor({ symbols: selectedSymbols.value, timeframes: selectedTimeframes.value })
    ElMessage.success('已开始监视')
    selectedSymbols.value = []
    selectedTimeframes.value = []
    await refreshStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '启动失败')
  } finally {
    loading.value = false
  }
}

async function handleStop() {
  try {
    await stopMonitor()
    ElMessage.success('已停止全部监视')
    await refreshStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '停止失败')
  }
}

async function removePair(symbol, timeframe) {
  try {
    await apiRemovePair({ symbol, timeframe })
    await refreshStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '移除失败')
  }
}

async function handleMinuteStart() {
  if (!minuteForm.symbols.length) {
    ElMessage.warning('请选择预警监控币种')
    return
  }
  minuteLoading.value = true
  try {
    await startMinuteAlert({
      symbols: minuteForm.symbols,
      interval: minuteForm.interval,
      vol_pct_threshold: minuteForm.vol_pct_threshold,
      volume_mult_threshold: minuteForm.volume_mult_threshold,
      ob_notional_threshold: minuteForm.ob_notional_threshold,
    })
    ElMessage.success('已启动1分钟预警')
    await refreshMinuteStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '启动失败')
  } finally {
    minuteLoading.value = false
  }
}

async function handleMinuteStop() {
  try {
    await stopMinuteAlert()
    ElMessage.success('已停止预警')
    await refreshMinuteStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '停止失败')
  }
}
</script>

<style scoped>
.title-row {
  margin-bottom: 20px;
  padding-left: 16px;
  border-left: 4px solid var(--color-primary);
}
.title-row h2 { margin: 0; font-size: 24px; font-weight: 700; color: var(--color-text); }
.config-form { display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start; }
.symbol-select { width: 320px; min-width: 280px; }
.timeframe-group { display: flex; flex-wrap: wrap; gap: 16px 28px; }
.btn-row { margin-left: 8px; }
.minute-alert-card { margin-top: 18px; }
.minute-alert-card :deep(.el-card__body) { padding: 24px; }

.minute-form-grid{
  display: grid;
  /* 规整两行布局（用 grid areas 固定位置） */
  /* 6列：最后一列留给按钮，避免按钮换行堆叠 */
  grid-template-columns: minmax(360px, 2.2fr) 120px 160px 160px 220px minmax(280px, 1fr);
  grid-template-areas:
    "symbols symbols interval vol volume ."
    "ob      ob      ob       ob  ob     actions";
  gap: 12px 18px;
  align-items: end;
}
.minute-symbols{ grid-area: symbols; }
.minute-interval{ grid-area: interval; }
.minute-vol{ grid-area: vol; }
.minute-volume{ grid-area: volume; }
.minute-ob{ grid-area: ob; }
.minute-actions{
  grid-area: actions;
  display: flex;
  justify-content: flex-end;
  gap: 14px;
  flex-wrap: nowrap;
  min-width: 280px;
}
.w-120{ width: 120px; }
.w-160{ width: 160px; }
.w-220{ width: 220px; }
.symbol-select-full{ width: 100%; }
.field-with-help{ display: flex; flex-direction: column; align-items: flex-start; }
.field-help{
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-muted);
  line-height: 1.4;
  max-width: 420px;
}

@media (max-width: 760px) {
  .minute-form-grid { grid-template-columns: 1fr; }
  .minute-form-grid{
    grid-template-areas:
      "symbols"
      "interval"
      "vol"
      "volume"
      "ob"
      "actions";
  }
  .minute-actions { justify-content: stretch; flex-wrap: nowrap; }
  .minute-actions :deep(.el-button) { flex: 1; }
}

/* 高级币种池：正常蓝色，有异动时变红 */
.pool-card :deep(.el-card__body) { padding: 24px; }
.pool {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  min-height: 96px;
  padding: 24px;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 50%, #bfdbfe 100%);
  border-radius: 12px;
  border: 1px solid rgba(59, 130, 246, 0.35);
  transition: background 0.3s ease, border-color 0.3s ease;
}
.pool.pool-alerted {
  background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 50%, #fecaca 100%);
  border-color: rgba(239, 68, 68, 0.5);
}
.pool-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px 10px 16px;
  background: #fff;
  border-radius: 10px;
  border: 1px solid var(--color-border);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  font-weight: 600;
  transition: all 0.2s ease;
}
.pool-chip:hover {
  box-shadow: 0 4px 14px rgba(59, 130, 246, 0.25);
  border-color: rgba(59, 130, 246, 0.5);
}
.pool-chip.alerted {
  background: linear-gradient(135deg, #fef2f2, #fee2e2);
  border-color: rgba(239, 68, 68, 0.5);
  box-shadow: 0 2px 12px rgba(239, 68, 68, 0.2);
}
.pool-chip.alerted:hover {
  box-shadow: 0 4px 16px rgba(239, 68, 68, 0.3);
}
.chip-symbol {
  font-size: 14px;
  color: var(--color-text);
  font-family: var(--font-mono);
  letter-spacing: 0.03em;
}
.chip-timeframe {
  font-size: 12px;
  color: var(--color-text-muted);
  font-weight: 500;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
}
.pool-chip.alerted .chip-timeframe { background: rgba(239, 68, 68, 0.15); color: var(--color-danger); }
.chip-close {
  margin-left: 4px;
  width: 22px;
  height: 22px;
  border: none;
  background: #f1f5f9;
  color: var(--color-text-muted);
  border-radius: 6px;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}
.chip-close:hover {
  background: var(--color-danger);
  color: #fff;
}
.hint { margin: 0 0 16px 0; font-size: 13px; color: var(--color-text-muted); }
.empty { text-align: center; padding: 48px; color: var(--color-text-muted); font-size: 14px; }
</style>
