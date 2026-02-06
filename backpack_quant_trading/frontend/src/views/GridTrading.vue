<template>
  <div class="page grid-page">
    <div class="title-row">
      <h2>网格配置</h2>
    </div>

    <el-card class="config-card">
      <template #header>交易参数</template>
      <el-form :model="form" label-width="140px" class="config-form">
        <div class="form-grid">
          <el-form-item label="交易所">
            <el-select v-model="form.exchange" teleported style="width: 100%">
              <el-option label="Backpack" value="backpack" />
              <el-option label="Deepcoin" value="deepcoin" />
            </el-select>
          </el-form-item>
          <el-form-item label="交易对">
            <el-input v-model="form.symbol" placeholder="ETH / BTC / SOL..." style="width: 100%" />
          </el-form-item>
          <el-form-item label="价格下限 (USDT)">
            <el-input-number v-model="form.price_lower" :min="0" :precision="2" style="width: 100%" />
          </el-form-item>
          <el-form-item label="价格上限 (USDT)">
            <el-input-number v-model="form.price_upper" :min="0" :precision="2" style="width: 100%" />
          </el-form-item>
          <el-form-item label="网格数量">
            <el-input-number v-model="form.grid_count" :min="2" :max="100" style="width: 100%" />
          </el-form-item>
          <el-form-item label="单格投资 (USDT)">
            <el-input-number v-model="form.investment_per_grid" :min="0.1" :precision="2" style="width: 100%" />
          </el-form-item>
          <el-form-item label="杠杆倍数">
            <el-input-number v-model="form.leverage" :min="1" :max="100" style="width: 100%" />
          </el-form-item>
          <el-form-item label="网格类型">
            <el-select v-model="form.grid_mode" teleported :popper-options="{ placement: 'bottom-start' }" style="width: 100%">
              <el-option label="做空网格" value="short_only" />
              <el-option label="做多网格" value="long_only" />
              <el-option label="双向网格" value="long_short" />
            </el-select>
          </el-form-item>
          <el-form-item label="API Key" class="span-2">
            <el-input v-model="form.api_key" type="password" placeholder="手动输入" show-password style="width: 100%" />
          </el-form-item>
          <el-form-item label="Secret Key" class="span-2">
            <el-input v-model="form.secret_key" type="password" placeholder="手动输入" show-password style="width: 100%" />
          </el-form-item>
        </div>
        <div class="form-actions">
          <el-button type="primary" size="large" :loading="starting" @click="startGrid">启动当前类型网格</el-button>
          <el-button type="danger" size="large" :loading="stopping" @click="stopAll">停止全部网格</el-button>
        </div>
      </el-form>

      <div v-if="previewValid" class="param-preview">
        <h4>参数预览</h4>
        <div class="preview-grid">
          <div class="preview-card">
            <div class="card-icon">📊</div>
            <div class="card-label">网格间距</div>
            <div class="card-value">${{ gridPreview.gridSpacing.toFixed(2) }} <span class="muted">({{ gridPreview.gridSpacingPercent.toFixed(2) }}%)</span></div>
          </div>
          <div class="preview-card">
            <div class="card-icon">💰</div>
            <div class="card-label">总投资</div>
            <div class="card-value">${{ gridPreview.totalInvestment.toFixed(2) }} <span class="muted">(保证金)</span></div>
          </div>
          <div class="preview-card">
            <div class="card-icon">📈</div>
            <div class="card-label">实际持仓价值</div>
            <div class="card-value">${{ gridPreview.positionValue.toFixed(2) }} <span class="muted">({{ form.leverage }}x杠杆)</span></div>
          </div>
          <div class="preview-card">
            <div class="card-icon">💵</div>
            <div class="card-label">单网格收益率</div>
            <div class="card-value profit">{{ gridPreview.profitRatePercent.toFixed(2) }}% (${{ gridPreview.profitPerGrid.toFixed(2) }})</div>
          </div>
          <div class="preview-card">
            <div class="card-icon">🎯</div>
            <div class="card-label">建议网格数</div>
            <div class="card-value">{{ form.grid_count }} 格 <span class="muted">(间距 {{ gridPreview.gridSpacingPercent.toFixed(2) }}%)</span></div>
          </div>
          <div class="preview-card">
            <div class="card-icon">💥</div>
            <div class="card-label">预估强平价</div>
            <div class="card-value danger">${{ gridPreview.liqPrice.toFixed(2) }}</div>
          </div>
        </div>
      </div>
    </el-card>

    <el-card class="instances-card">
      <template #header>运行中的网格实例</template>
      <div v-if="grids.length === 0" class="empty">网格未启动，点击上方「启动当前类型网格」新增实例</div>
      <div v-else class="grid-list">
        <div v-for="g in grids" :key="g.id" class="grid-card">
          <div class="grid-info">
            <div class="tags">
              <el-tag size="small" type="warning">{{ g.exchange?.toUpperCase() }}</el-tag>
              <span class="status">● 运行中</span>
            </div>
            <h3>{{ g.symbol }} | {{ modeLabel(g.grid_mode) }}</h3>
            <p>价格 ${{ (g.current_price || 0).toFixed(2) }} | 成交 {{ g.total_trades || 0 }} 次</p>
          </div>
          <el-button type="danger" size="small" @click="stopOne(g.id)">停止</el-button>
        </div>
      </div>
    </el-card>

    <el-card>
      <template #header>网格日志</template>
      <div class="log-area">暂无日志</div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getGridStatus, startGrid as apiStartGrid, stopGrid, stopAllGrids } from '../api/grid'
const grids = ref([])
const starting = ref(false)
const stopping = ref(false)

const form = reactive({
  exchange: 'backpack',
  symbol: 'ETH',
  price_lower: 2000,
  price_upper: 2500,
  grid_count: 5,
  investment_per_grid: 10,
  leverage: 10,
  grid_mode: 'short_only',
  api_key: '',
  secret_key: '',
})

const previewValid = computed(() => {
  const { price_lower, price_upper, grid_count, investment_per_grid, leverage } = form
  return price_lower != null && price_upper != null && price_lower < price_upper && grid_count >= 2 && investment_per_grid > 0 && leverage >= 1
})

const gridPreview = computed(() => {
  const { price_lower, price_upper, grid_count, investment_per_grid, leverage } = form
  const priceRange = price_upper - price_lower
  const gridSpacing = priceRange / grid_count
  const gridSpacingPercent = (gridSpacing / price_lower) * 100
  const totalInvestment = investment_per_grid * grid_count
  const positionValue = totalInvestment * leverage
  const profitPerGrid = investment_per_grid * leverage * gridSpacingPercent / 100
  const profitRatePercent = gridSpacingPercent * leverage - (0.1 * leverage)
  const avgPrice = (price_lower + price_upper) / 2
  const liqPrice = leverage > 1 ? avgPrice * (1 - 1 / leverage + 0.005) : 0
  return {
    gridSpacing,
    gridSpacingPercent,
    totalInvestment,
    positionValue,
    profitPerGrid,
    profitRatePercent,
    liqPrice,
  }
})

onMounted(async () => {
  await refreshStatus()
  const t = setInterval(refreshStatus, 3000)
  onUnmounted(() => clearInterval(t))
})

async function refreshStatus() {
  try {
    const res = await getGridStatus()
    grids.value = res.grids || []
  } catch {}
}

function modeLabel(m) {
  const map = { long_short: '双向', long_only: '做多', short_only: '做空' }
  return map[m] || m
}

async function startGrid() {
  if (!form.symbol || !form.api_key || !form.secret_key) {
    ElMessage.warning('请填写交易对、API Key 和 Secret Key')
    return
  }
  starting.value = true
  try {
    const res = await apiStartGrid({
      ...form,
      api_key: form.api_key,
      secret_key: form.secret_key,
    })
    if (res.ok) {
      ElMessage.success('网格已启动')
      await refreshStatus()
    } else {
      ElMessage.error(res.message || '启动失败')
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '启动失败')
  } finally {
    starting.value = false
  }
}

async function stopOne(id) {
  try {
    await stopGrid(id)
    ElMessage.success('已停止')
    await refreshStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '停止失败')
  }
}

async function stopAll() {
  stopping.value = true
  try {
    await stopAllGrids()
    ElMessage.success('已停止全部')
    await refreshStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '停止失败')
  } finally {
    stopping.value = false
  }
}
</script>

<style scoped>
.title-row { margin-bottom: 24px; padding-left: 16px; border-left: 4px solid var(--color-primary); }
.title-row h2 { margin: 0; font-size: 24px; font-weight: 700; color: var(--color-text); }

.config-card { margin-bottom: 28px; overflow: visible; }
.config-card :deep(.el-card__body) { padding: 32px 40px; overflow: visible; }
.config-form :deep(.el-form-item) { margin-bottom: 24px; }

.form-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0 40px;
  overflow: visible;
}
.form-grid .el-form-item { margin-bottom: 24px; }
.form-grid .el-form-item.span-2 { grid-column: span 2; }
.form-actions {
  display: flex;
  justify-content: center;
  gap: 24px;
  margin-top: 8px;
  padding-top: 24px;
  border-top: 1px solid var(--color-border);
}

.param-preview {
  margin-top: 28px;
  padding: 20px 24px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-radius: 12px;
  border: 1px solid var(--color-border);
}
.param-preview h4 {
  margin: 0 0 16px 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}
.preview-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.preview-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 12px 16px;
  background: #fff;
  border-radius: 10px;
  border: 1px solid var(--color-border);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  min-height: 72px;
}
.preview-card .card-icon { font-size: 18px; margin-bottom: 6px; }
.preview-card .card-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: 4px;
  letter-spacing: 0.02em;
}
.preview-card .card-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  line-height: 1.35;
}
.preview-card .card-value .muted { font-weight: 500; color: var(--color-text-muted); font-size: 12px; }
.preview-card .card-value.profit { color: var(--color-success); font-size: 15px; }
.preview-card .card-value.danger { color: var(--color-danger); font-size: 15px; }

.grid-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
.grid-card {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px; background: var(--color-bg-card); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); box-shadow: var(--shadow-sm); transition: box-shadow 0.2s;
}
.grid-card:hover { box-shadow: var(--shadow-md); }
.grid-info h3 { margin: 0 0 8px 0; font-size: 15px; font-weight: 600; color: var(--color-text); }
.grid-info p { margin: 0; font-size: 13px; color: var(--color-text-secondary); }
.tags { margin-bottom: 10px; }
.status { color: var(--color-success); font-size: 11px; font-weight: 600; margin-left: 8px; }
.empty { text-align: center; padding: 56px; color: var(--color-text-muted); font-size: 15px; }
.log-area {
  min-height: 160px; background: #1e293b; padding: 24px; border-radius: var(--radius-md);
  color: #e2e8f0; font-family: var(--font-mono); font-size: 13px; line-height: 1.8;
}
</style>
