<template>
  <div class="page dashboard-page">
    <div class="title-row">
      <h2>数据资产监控大屏</h2>
      <div class="meta">
        <span class="online">NETWORK ONLINE</span>
        <span>{{ now }}</span>
      </div>
    </div>

    <div class="summary-grid dense">
      <div class="summary-card">
        <p>总资产价值</p>
        <h3>${{ (summary.portfolio_value || 0).toLocaleString('en-US', { minimumFractionDigits: 2 }) }}</h3>
      </div>
      <div class="summary-card">
        <p>可用现金</p>
        <h3>${{ (summary.cash_balance || 0).toLocaleString('en-US', { minimumFractionDigits: 2 }) }}</h3>
      </div>
      <div class="summary-card" :class="pnlClass">
        <p>当日盈亏</p>
        <h3>{{ pnlPrefix }}${{ Math.abs(summary.daily_pnl || 0).toLocaleString('en-US', { minimumFractionDigits: 2 }) }}</h3>
      </div>
      <div class="summary-card" :class="returnClass">
        <p>当日收益率</p>
        <h3>{{ returnPrefix }}{{ (Math.abs(summary.daily_return || 0) * 100).toFixed(2) }}%</h3>
      </div>
    </div>

    <el-card class="chart-card">
      <template #header>📈 组合累计净值曲线</template>
      <div ref="chartRef" class="chart-area"></div>
    </el-card>

    <div class="tables-row">
      <el-card class="table-card">
        <template #header>💼 当前活动仓位</template>
        <el-table v-if="positions.length" :data="positions" size="small">
          <el-table-column prop="symbol" label="交易对" min-width="120" show-overflow-tooltip />
          <el-table-column prop="side" label="方向" width="72">
            <template #default="{ row }">
              <span :class="row.side === 'long' ? 'long' : 'short'">{{ (row.side || '').toUpperCase() }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="100" />
          <el-table-column prop="entry_price" label="入场价" width="100">
            <template #default="{ row }">${{ Number(row.entry_price || 0).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="current_price" label="当前价" width="100">
            <template #default="{ row }">${{ Number(row.current_price || 0).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="unrealized_pnl" label="未实现盈亏">
            <template #default="{ row }">
              <span :class="(row.unrealized_pnl || 0) >= 0 ? 'profit' : 'loss'">
                ${{ Number(row.unrealized_pnl || 0).toLocaleString() }}
              </span>
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="empty">无活跃持仓</div>
      </el-card>

      <el-card class="table-card">
        <template #header>📋 订单</template>
        <el-table v-if="orders.length" :data="orders" size="small">
          <el-table-column prop="symbol" label="交易对" min-width="130" show-overflow-tooltip />
          <el-table-column prop="order_type" label="类型" width="72" />
          <el-table-column prop="side" label="方向" width="72">
            <template #default="{ row }">
              <span :class="row.side === 'buy' ? 'long' : 'short'">{{ (row.side || '').toUpperCase() }}</span>
            </template>
          </el-table-column>
          <el-table-column label="价格" min-width="88">
            <template #default="{ row }">
              {{ row.price != null && row.price !== '' ? '$' + Number(row.price).toLocaleString() : (row.order_type === 'market' ? '市价' : '-') }}
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" min-width="90" />
          <el-table-column prop="status" label="状态" width="72" />
        </el-table>
        <div v-else class="empty">无活跃订单</div>
      </el-card>
    </div>

    <div class="tables-row">
      <el-card class="table-card">
        <template #header>📊 成交历史</template>
        <el-table v-if="trades.length" :data="trades" size="small">
          <el-table-column label="时间" width="80">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="symbol" label="交易对" min-width="110" show-overflow-tooltip />
          <el-table-column prop="side" label="方向" width="70">
            <template #default="{ row }">
              <span :class="['long', 'buy'].includes(row.side) ? 'long' : 'short'">{{ (row.side || '').toUpperCase() }}</span>
            </template>
          </el-table-column>
          <el-table-column label="价格" width="90">
            <template #default="{ row }">{{ row.price != null && row.price !== '' ? '$' + Number(row.price).toLocaleString() : '-' }}</template>
          </el-table-column>
          <el-table-column prop="quantity" label="成交额" width="80" />
          <el-table-column prop="pnl_amount" label="盈亏">
            <template #default="{ row }">
              <span v-if="row.pnl_amount != null" :class="row.pnl_amount >= 0 ? 'profit' : 'loss'">
                ${{ Number(row.pnl_amount).toLocaleString() }}
              </span>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="empty">暂无成交历史</div>
      </el-card>

      <el-card class="table-card">
        <template #header>⚠️ 风险事件</template>
        <div v-if="risks.length" class="risk-list">
          <div v-for="r in risks" :key="r.id" class="risk-item">
            <div class="risk-head">
              <span :class="r.severity === 'high' ? 'danger' : 'warn'">{{ r.event_type }}</span>
              <span class="time">{{ formatTime(r.created_at) }}</span>
            </div>
            <p>{{ r.description }}</p>
          </div>
        </div>
        <div v-else class="empty success">系统运行正常</div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { getDashboard } from '../api/dashboard'
import { getInstances } from '../api/trading'

const chartRef = ref(null)
const summary = ref({})
const chartData = ref([])
const positions = ref([])
const orders = ref([])
const trades = ref([])
const risks = ref([])
const exchange = ref('backpack')
const now = ref('')

const pnlClass = computed(() => {
  const v = summary.value.daily_pnl || 0
  return v > 0 ? 'profit' : v < 0 ? 'loss' : ''
})
const pnlPrefix = computed(() => {
  const v = summary.value.daily_pnl || 0
  return v > 0 ? '+' : v < 0 ? '-' : ''
})
const returnClass = computed(() => {
  const v = summary.value.daily_return || 0
  return v > 0 ? 'profit' : v < 0 ? 'loss' : ''
})
const returnPrefix = computed(() => {
  const v = summary.value.daily_return || 0
  return v > 0 ? '+' : v < 0 ? '-' : ''
})

function formatTime(s) {
  if (!s) return '--'
  const d = new Date(s)
  return d.toTimeString().slice(0, 8)
}

onMounted(async () => {
  try {
    const res = await getInstances()
    const insts = res.instances || []
    if (insts.length) exchange.value = insts[0].platform || 'backpack'
  } catch {}
  await refresh()
  const t = setInterval(refresh, 10000)
  const t2 = setInterval(() => { now.value = new Date().toISOString().slice(0, 19).replace('T', ' ') }, 1000)
  onUnmounted(() => { clearInterval(t); clearInterval(t2) })
})

async function refresh() {
  try {
    const res = await getDashboard(exchange.value)
    summary.value = res.summary || {}
    chartData.value = res.chart || []
    positions.value = res.positions || []
    orders.value = res.orders || []
    trades.value = res.trades || []
    risks.value = res.risks || []
    renderChart()
  } catch {}
}

function renderChart() {
  if (!chartRef.value || !chartData.value.length) return
  const ch = echarts.init(chartRef.value)
  ch.setOption({
    xAxis: { type: 'category', data: chartData.value.map((d) => d.timestamp?.slice(0, 16)) },
    yAxis: { type: 'value' },
    series: [{ type: 'line', data: chartData.value.map((d) => d.value), areaStyle: { color: 'rgba(245, 158, 11, 0.18)' }, lineStyle: { color: '#f59e0b', width: 3 } }],
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
  })
}
</script>

<style scoped>
.dashboard-page { max-width: none; margin: -8px -4px 0; }
.title-row {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px; padding-left: 12px; border-left: 4px solid var(--color-primary);
}
.title-row h2 { margin: 0; font-size: 22px; font-weight: 700; color: var(--color-text); }
.meta .online { color: var(--color-success); font-weight: 600; margin-right: 8px; font-size: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
.summary-grid.dense .summary-card { padding: 12px 16px; }
.summary-card {
  padding: 18px; background: var(--color-bg-card); border-radius: var(--radius-md);
  border: 1px solid var(--color-border); box-shadow: var(--shadow-sm);
}
.summary-card p { margin: 0; font-size: 11px; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.4px; }
.summary-card h3 { margin: 6px 0 0 0; font-size: 18px; font-weight: 700; font-family: var(--font-mono); }
.summary-card.profit h3 { color: var(--color-success); }
.summary-card.loss h3 { color: var(--color-danger); }
.chart-card { margin-bottom: 16px; }
.chart-card :deep(.el-card__body) { padding: 12px 16px; }
.chart-area { height: 260px; min-height: 180px; }
.tables-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.tables-row .el-card { border-radius: var(--radius-md); }
.table-card :deep(.el-card__body) { padding: 10px 14px; }
.table-card :deep(.el-table) { font-size: 12px; width: 100%; }
.table-card :deep(.el-table th) { padding: 8px 6px; }
.table-card :deep(.el-table td) { padding: 6px 6px; }
.empty { text-align: center; padding: 20px 16px; color: var(--color-text-muted); font-size: 12px; }
.empty.success { color: var(--color-success); }
.long { color: var(--color-success); font-weight: 600; }
.short { color: var(--color-danger); font-weight: 600; }
.profit { color: var(--color-success); }
.loss { color: var(--color-danger); }
.risk-list { max-height: 180px; overflow-y: auto; }
.risk-item { padding: 8px 0; border-bottom: 1px solid var(--color-border); }
.risk-item:last-child { border-bottom: none; }
.risk-head { margin-bottom: 4px; }
.risk-head .danger { color: var(--color-danger); font-weight: 600; }
.risk-head .warn { color: var(--color-warning); font-weight: 600; }
.risk-head .time { float: right; font-size: 11px; color: var(--color-text-muted); }
</style>
