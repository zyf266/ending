<template>
  <div class="page strategy-page">
    <div class="title-row">
      <div class="title-main">
        <div class="title-top">
          <h2>沐龙纳指趋势追踪增强策略 (ML-NAS)</h2>
          <el-button class="back-link" size="small" link @click="$router.push('/strategies')">返回策略矩阵</el-button>
        </div>
        <p class="sub">
          ML-DTS 策略专注于主流加密货币市场（如 BTC、ETH）。其核心理念是捕捉由市场波动率扩张驱动的中长期趋势，通过多时间框架协同分析（如日线、4 小时、2 小时），
          确保仅在趋势明朗时介入，避免震荡行情中的无效损耗。策略基于量化规则驱动，旨在通过纪律性执行实现风险调整后的超额收益（Alpha）。
        </p>
      </div>
      <!-- 日期筛选：缩小尺寸，右上角对齐，并增加快捷选项方便按年/月筛选 -->
      <div class="filter-row">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          size="small"
          class="date-picker"
          :shortcuts="dateShortcuts"
          unlink-panels
        />
        <el-button size="small" type="primary" @click="applyDateFilter">筛选</el-button>
        <el-button size="small" @click="resetDateFilter">重置</el-button>
      </div>
    </div>

    <!-- 信号回放 K 线图（尽量贴近你发的第2张图） -->
    <el-card class="chart-card" v-loading="loadingSignals">
      <template #header>📍 信号回放 · 价格 K 线</template>
      <div ref="signalChartRef" class="kline-area" />
    </el-card>

    <!-- 顶部指标放在 K 线之后，布局和 TradingView 统一 -->
    <div class="summary-grid" v-if="overview">
      <div class="summary-card">
        <p>总盈亏</p>
        <h3 :class="overview.total_return_pct >= 0 ? 'profit' : 'loss'">
          {{ formatMoney(overview.strategy_profit) }} {{ formatPct(overview.total_return_pct) }}
        </h3>
      </div>
      <div class="summary-card">
        <p>最大股权回撤</p>
        <h3 class="drawdown">
          {{ formatPctAbs(overview.max_drawdown_pct) }}
        </h3>
      </div>
      <div class="summary-card">
        <p>总交易</p>
        <h3>
          {{ displayTotalTrades }}
        </h3>
      </div>
      <div class="summary-card">
        <p>盈利交易</p>
        <h3>
          {{ formatPct(overview.win_rate_pct) }}
        </h3>
      </div>
      <div class="summary-card">
        <p>盈利因子</p>
        <h3>
          {{ (overview.profit_factor ?? 0).toFixed(2) }}
        </h3>
      </div>
    </div>

    <el-card class="chart-card" v-loading="loading">
      <template #header>📈 策略权益曲线</template>
      <div ref="equityChartRef" class="chart-area" />
    </el-card>

    <!-- 指标 / 交易清单 Tab -->
    <el-tabs v-model="activeTab" class="section-tabs">
      <!-- 指标页：表现 + 收益分布 / 胜率结构 + 指标表 + 详细信息 -->
      <el-tab-pane label="指标" name="metrics">
        <!-- 表现：利润结构 + 贡献图 -->
        <div class="analysis-row" v-if="overview">
          <el-card class="analysis-card">
            <template #header>📈 利润结构</template>
            <div ref="profitStructRef" class="chart-area-small" />
          </el-card>
          <el-card class="analysis-card">
            <template #header>📌 贡献</template>
            <div ref="contributionRef" class="chart-area-small" />
          </el-card>
        </div>

        <!-- 绩效拆解区域（收益分布 + 胜率结构） -->
        <div class="analysis-row" v-if="trades.length">
          <el-card class="analysis-card">
            <template #header>📊 收益分布</template>
            <div ref="pnlHistRef" class="chart-area-small" />
          </el-card>
          <el-card class="analysis-card">
            <template #header>🥧 胜率结构</template>
            <div ref="winLossRef" class="chart-area-small" />
          </el-card>
        </div>

        <!-- 指标明细（参考 TradingView 指标表） -->
        <el-card class="chart-card metrics-card" v-if="detailRows.length">
          <template #header>📋 指标</template>
          <el-table :data="detailRows" size="medium" border class="metrics-table">
            <el-table-column prop="name" label="指标" width="160" />
            <el-table-column prop="all" label="全部" min-width="220" />
            <el-table-column prop="long" label="做多" min-width="220" />
            <el-table-column prop="short" label="做空" min-width="160" />
          </el-table>
        </el-card>
        <!-- 详细信息（参考 TradingView 详细信息表） -->
        <el-card class="chart-card metrics-card" v-if="detailInfoRows.length">
          <template #header>📊 详细信息</template>
          <el-table :data="detailInfoRows" size="medium" border class="metrics-table">
            <el-table-column prop="name" label="指标" width="200" />
            <el-table-column prop="all" label="全部" min-width="220" />
            <el-table-column prop="long" label="做多" min-width="220" />
            <el-table-column prop="short" label="做空" min-width="160" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 交易清单页：只显示交易明细表（时间倒序） -->
      <el-tab-pane label="交易清单" name="trades">
        <el-card class="chart-card trades-card">
          <template #header>📊 交易明细</template>
          <el-table :data="tradesSorted" size="medium" height="600" class="trades-table">
            <el-table-column prop="trade_no" label="交易 #" width="80" />
            <el-table-column prop="trade_type" label="类型" width="90" />
            <el-table-column prop="signal" label="信号" width="90" show-overflow-tooltip />
            <el-table-column label="时间" width="150">
              <template #default="{ row }">
                {{ row.trade_time.replace('T', ' ').slice(0, 16) }}
              </template>
            </el-table-column>
            <el-table-column prop="price" label="价格" width="90" />
            <el-table-column prop="position_qty" label="仓位大小" width="110" />
            <el-table-column prop="position_value" label="仓位价值 USD" width="140">
              <template #default="{ row }">
                {{ Number(row.position_value).toLocaleString() }}
              </template>
            </el-table-column>
            <el-table-column prop="pnl" label="净损益 USD" width="130">
              <template #default="{ row }">
                <span :class="row.pnl >= 0 ? 'profit' : 'loss'">
                  {{ Number(row.pnl).toLocaleString() }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="pnl_pct" label="净损益 %" width="90">
              <template #default="{ row }">
                <span :class="row.pnl_pct >= 0 ? 'profit' : 'loss'">
                  {{ row.pnl_pct.toFixed(2) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="runup" label="有利波动 USD" width="130">
              <template #default="{ row }">
                {{ Number(row.runup ?? 0).toLocaleString() }}
              </template>
            </el-table-column>
            <el-table-column prop="runup_pct" label="有利波动 %" width="100">
              <template #default="{ row }">
                {{ (row.runup_pct ?? 0).toFixed(2) }}%
              </template>
            </el-table-column>
            <el-table-column prop="drawdown" label="不利波动 USD" width="140">
              <template #default="{ row }">
                {{ Number(row.drawdown ?? 0).toLocaleString() }}
              </template>
            </el-table-column>
            <el-table-column prop="drawdown_pct" label="不利波动 %" width="110">
              <template #default="{ row }">
                {{ (row.drawdown_pct ?? 0).toFixed(2) }}%
              </template>
            </el-table-column>
            <el-table-column prop="cum_pnl" label="累计P&L USD" width="150">
              <template #default="{ row }">
                {{ Number(row.cum_pnl ?? 0).toLocaleString() }}
              </template>
            </el-table-column>
            <el-table-column prop="cum_pnl_pct" label="累计P&L %" width="110">
              <template #default="{ row }">
                {{ (row.cum_pnl_pct ?? 0).toFixed(2) }}%
              </template>
            </el-table-column>
          </el-table>
          <div v-if="!trades.length" class="empty">
            暂无回测交易数据，请先调用 /api/strategy/nas100-2h/import-trades 与 import-klines
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'
import { getNas100TrendOverview, getNas100TrendTrades, getNas100TrendKlines } from '../api/strategy'

const overview = ref(null)
const trades = ref([])
const tradesSorted = ref([])
const equityChartRef = ref(null)
const signalChartRef = ref(null)
const pnlHistRef = ref(null)
const winLossRef = ref(null)
const profitStructRef = ref(null)
const contributionRef = ref(null)
const detailRows = ref([])         // 指标表
const detailInfoRows = ref([])     // 详细信息表
const activeTab = ref('metrics')
const loading = ref(false)
const loadingSignals = ref(false)
const klines = ref([])
const allTrades = ref([])
const allKlines = ref([])
const dateRange = ref([]) // ['YYYY-MM-DD', 'YYYY-MM-DD']

/** 总交易数：始终按“出场”行数 & trade_no 去重（一买一卖=1笔），完全不依赖后端 total_trades */
const displayTotalTrades = computed(() => {
  const src = (allTrades.value && allTrades.value.length) ? allTrades.value : trades.value
  if (!src?.length) return 0
  const exitOnly = src.filter((t) => {
    const tp = String(t.trade_type || '')
    const sig = String(t.signal || '').toLowerCase()
    return tp.includes('出') || tp.includes('出场') || tp.includes('止损') || sig.includes('close')
  })
  if (!exitOnly.length) return 0
  const uniq = new Set(exitOnly.map((t) => t.trade_no))
  return uniq.size || exitOnly.length
})

// 日期快捷选项：按月 / 按年快速筛选
const dateShortcuts = [
  {
    text: '本月',
    value: () => {
      const end = new Date()
      const start = new Date(end.getFullYear(), end.getMonth(), 1)
      return [start, end]
    },
  },
  {
    text: '近3个月',
    value: () => {
      const end = new Date()
      const start = new Date(end)
      start.setMonth(start.getMonth() - 3)
      return [start, end]
    },
  },
  {
    text: '本年',
    value: () => {
      const end = new Date()
      const start = new Date(end.getFullYear(), 0, 1)
      return [start, end]
    },
  },
  {
    text: '全部',
    value: () => {
      // 交给 resetDateFilter / applyDateFilter 处理
      return []
    },
  },
]

let chart = null
let klineChart = null
let pnlHistChart = null
let winLossChart = null
let profitStructChart = null
let contributionChart = null

function formatPct(v) {
  if (v == null) return '--'
  const n = Number(v)
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  return `${sign}${Math.abs(n).toFixed(2)}%`
}

function formatPctAbs(v) {
  if (v == null) return '--'
  return `${Math.abs(Number(v)).toFixed(2)}%`
}

function formatMoney(v) {
  if (v == null) return ''
  const n = Number(v)
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  return `${sign}${Math.abs(n).toLocaleString()} USDT`
}

function formatMoneyPlain(v) {
  if (v == null) return '0 USDT'
  const n = Number(v)
  return `${n.toLocaleString()} USDT`
}

function buildDetailRows() {
  if (!overview.value || !trades.value.length) {
    detailRows.value = []
    return
  }
  const ov = overview.value
  const initial = 2000000

  const pnls = trades.value.map((t) => Number(t.pnl || 0))
  // 进出各一行，需要折半
  const grossProfit = pnls
    .filter((p) => p > 0)
    .reduce((s, p) => s + p, 0) / 2
  const grossLoss =
    pnls.filter((p) => p < 0).reduce((s, p) => s + p, 0) / 2 // 负数
  const grossLossAbs = Math.abs(grossLoss)

  const netProfit = Number(ov.strategy_profit ?? 0)
  const unrealized = 0
  const profitFactor = Number(ov.profit_factor ?? 0)
  const totalTrades = Number(ov.total_trades ?? 0)
  const expectedPayoff = totalTrades ? netProfit / totalTrades : 0

  const rows = [
    {
      name: '初始资本',
      all: formatMoneyPlain(initial),
      long: formatMoneyPlain(initial),
      short: '0 USDT',
    },
    {
      name: '未实现盈亏',
      all: formatMoney(unrealized),
      long: formatMoney(unrealized),
      short: '0 USDT',
    },
    {
      name: '净利润',
      all: `${formatMoneyPlain(netProfit)}  ${formatPct(ov.total_return_pct)}`,
      long: `${formatMoneyPlain(netProfit)}  ${formatPct(ov.total_return_pct)}`,
      short: '0 USDT  0.00%',
    },
    {
      name: '毛利润',
      all: `${formatMoneyPlain(grossProfit)}  ${formatPct((grossProfit / initial) * 100)}`,
      long: `${formatMoneyPlain(grossProfit)}  ${formatPct((grossProfit / initial) * 100)}`,
      short: '0 USDT  0.00%',
    },
    {
      name: '毛亏损',
      all: `${formatMoneyPlain(grossLossAbs)}  ${formatPct((-grossLossAbs / initial) * 100)}`,
      long: `${formatMoneyPlain(grossLossAbs)}  ${formatPct((-grossLossAbs / initial) * 100)}`,
      short: '0 USDT  0.00%',
    },
    {
      name: '盈利因子',
      all: profitFactor.toFixed(2),
      long: profitFactor.toFixed(2),
      short: '—',
    },
    {
      name: '已支付佣金',
      all: '0 USDT',
      long: '0 USDT',
      short: '0 USDT',
    },
    {
      name: '预期收益',
      all: formatMoneyPlain(expectedPayoff),
      long: formatMoneyPlain(expectedPayoff),
      short: '0 USDT',
    },
  ]

  detailRows.value = rows
}

function buildDetailInfoRows() {
  if (!overview.value || !trades.value.length) {
    detailInfoRows.value = []
    return
  }
  const ov = overview.value
  const pnls = trades.value.map((t) => Number(t.pnl || 0))

  // 一买一卖 = 1 笔交易
  const exitTrades = trades.value.filter((t) => {
    const tp = String(t.trade_type || '')
    const sig = String(t.signal || '').toLowerCase()
    return tp.includes('出') || tp.includes('出场') || tp.includes('止损') || tp.toLowerCase().includes('close') || sig.includes('close')
  })
  const base = exitTrades.length ? exitTrades : trades.value
  // 按 trade_no 去重，一买一卖只算 1 笔
  const uniqMap = new Map()
  for (const t of base) {
    const raw = t.trade_no ?? 0
    const key = Number.isFinite(Number(raw)) ? Number(raw) : raw
    uniqMap.set(key, t)
  }
  const uniqBase = Array.from(uniqMap.values())
  const total = uniqBase.length

  const basePnls = uniqBase.map((t) => Number(t.pnl || 0))
  const basePcts = uniqBase.map((t) => Number(t.pnl_pct || 0))
  const wins = basePnls.filter((p) => p > 0)
  const losses = basePnls.filter((p) => p < 0)
  const winPcts = basePcts.filter((_, i) => basePnls[i] > 0)
  const lossPcts = basePcts.filter((_, i) => basePnls[i] < 0)
  const winCount = wins.length
  const lossCount = losses.length
  const winRate = total ? (winCount / total) * 100 : 0

  const netProfit = Number(ov.strategy_profit ?? 0)
  const avgTrade = total ? netProfit / total : 0
  const avgWin = winCount ? wins.reduce((s, p) => s + p, 0) / winCount : 0
  const avgLoss = lossCount ? losses.reduce((s, p) => s + p, 0) / lossCount : 0

  const avgWinPct = winPcts.length
    ? winPcts.reduce((s, p) => s + p, 0) / winPcts.length
    : 0
  const avgLossPct = lossPcts.length
    ? lossPcts.reduce((s, p) => s + p, 0) / lossPcts.length
    : 0
  const winLossRate =
    avgLossPct !== 0 ? avgWinPct / Math.abs(avgLossPct) : 0

  const maxWin = wins.length ? Math.max(...wins) : 0
  const maxLoss = losses.length ? Math.min(...losses) : 0
  const maxWinIdx = wins.length ? basePnls.indexOf(maxWin) : -1
  const maxLossIdx = losses.length ? basePnls.indexOf(maxLoss) : -1
  const maxWinPct = maxWinIdx >= 0 ? basePcts[maxWinIdx] : 0
  const maxLossPct = maxLossIdx >= 0 ? basePcts[maxLossIdx] : 0

  const rows = [
    { name: '总交易', all: total, long: total, short: 0 },
    { name: '总未平仓交易', all: 0, long: 0, short: 0 },
    { name: '盈利交易', all: winCount, long: winCount, short: 0 },
    { name: '亏损交易', all: lossCount, long: lossCount, short: 0 },
    {
      name: '获利百分比',
      all: `${winRate.toFixed(2)}%`,
      long: `${winRate.toFixed(2)}%`,
      short: '—',
    },
    {
      name: '平均盈亏',
      all: `${avgTrade.toLocaleString()} USDT`,
      long: `${avgTrade.toLocaleString()} USDT`,
      short: '0 USDT',
    },
    {
      name: '平均盈利交易',
      all: `${avgWin.toLocaleString()} USDT`,
      long: `${avgWin.toLocaleString()} USDT`,
      short: '0 USDT',
    },
    {
      name: '平均亏损交易',
      all: `${avgLoss.toLocaleString()} USDT`,
      long: `${avgLoss.toLocaleString()} USDT`,
      short: '0 USDT',
    },
    {
      name: '平均盈利率/平均亏损率',
      all: winLossRate.toFixed(3),
      long: winLossRate.toFixed(3),
      short: '—',
    },
    {
      name: '最大盈利交易',
      all: `${maxWin.toLocaleString()} USDT`,
      long: `${maxWin.toLocaleString()} USDT`,
      short: '0 USDT',
    },
    {
      name: '最大盈利交易百分比',
      all: `${maxWinPct.toFixed(2)}%`,
      long: `${maxWinPct.toFixed(2)}%`,
      short: '0.00%',
    },
    {
      name: '最大亏损占总盈利的百分比例',
      all:
        netProfit !== 0
          ? `${((Math.abs(maxLoss) / Math.abs(netProfit)) * 100).toFixed(2)}%`
          : '0.00%',
      long:
        netProfit !== 0
          ? `${((Math.abs(maxLoss) / Math.abs(netProfit)) * 100).toFixed(2)}%`
          : '0.00%',
      short: '0.00%',
    },
    {
      name: '最大亏损交易',
      all: `${maxLoss.toLocaleString()} USDT`,
      long: `${maxLoss.toLocaleString()} USDT`,
      short: '0 USDT',
    },
    {
      name: '最大亏损交易百分比',
      all: `${maxLossPct.toFixed(2)}%`,
      long: `${maxLossPct.toFixed(2)}%`,
      short: '0.00%',
    },
  ]

  detailInfoRows.value = rows
}

const NAS100_INITIAL = 2000000

/** 纳指：只统计“出场”行（类型含出场/止损或信号含 close），一买一卖=1 笔 */
function isExitTrade(t) {
  const tp = String(t.trade_type || '')
  const sig = String(t.signal || '').toLowerCase()
  return tp.includes('出') || tp.includes('出场') || tp.includes('止损') || tp.toLowerCase().includes('close') || sig.includes('close')
}

function computeOverviewFromTrades(tradesArray) {
  if (!tradesArray?.length) return null
  const initial = NAS100_INITIAL
  const exitTrades = tradesArray.filter(isExitTrade)
  const base = exitTrades.length ? exitTrades : tradesArray

  const pnls = base.map((t) => Number(t.pnl || 0))
  let running = 0
  const equity = pnls.map((p) => {
    running += p
    return initial + running
  })
  const finalEquity = equity[equity.length - 1]
  const totalReturnPct = ((finalEquity / initial) - 1) * 100

  let peak = equity[0]
  let maxDd = 0
  for (const v of equity) {
    if (v > peak) peak = v
    const dd = (v / peak - 1) * 100
    if (dd < maxDd) maxDd = dd
  }
  const maxDrawdownPct = Math.abs(maxDd)

  const wins = pnls.filter((p) => p > 0)
  const losses = pnls.filter((p) => p < 0)
  const totalTrades = pnls.length
  const winRatePct = totalTrades ? (wins.length / totalTrades) * 100 : 0
  const grossProfit = wins.reduce((s, p) => s + p, 0) || 0
  const grossLossAbs = Math.abs(losses.reduce((s, p) => s + p, 0)) || 1e-9
  const profitFactor = grossProfit / grossLossAbs

  return {
    strategy_profit: running,
    total_return_pct: Number(totalReturnPct.toFixed(2)),
    max_drawdown_pct: Number(maxDrawdownPct.toFixed(2)),
    win_rate_pct: Number(winRatePct.toFixed(2)),
    profit_factor: Number(profitFactor.toFixed(2)),
    total_trades: totalTrades,
  }
}

async function applyDateFilter() {
  if (dateRange.value && dateRange.value.length === 2) {
    const [startStr, endStr] = dateRange.value
    const start = new Date(startStr)
    const end = new Date(endStr)
    trades.value = allTrades.value.filter((t) => {
      const dt = new Date(t.trade_time)
      return dt >= start && dt <= end
    })
    klines.value = allKlines.value.filter((k) => {
      const dt = new Date(k.timestamp)
      return dt >= start && dt <= end
    })
  } else {
    trades.value = [...allTrades.value]
    klines.value = [...allKlines.value]
  }

  tradesSorted.value = [...trades.value].sort(
    (a, b) => new Date(b.trade_time).getTime() - new Date(a.trade_time).getTime(),
  )
  buildDetailRows()
  buildDetailInfoRows()

  await nextTick()
  renderSignals()
  renderEquity()
  renderProfitStruct()
  renderContribution()
  renderPnlHistogram()
  renderWinLoss()
}

function resetDateFilter() {
  dateRange.value = []
  applyDateFilter()
}

async function loadData() {
  loading.value = true
  loadingSignals.value = true
  try {
    const cacheBust = true
    const [ovRes, trRes, klRes] = await Promise.all([
      getNas100TrendOverview(cacheBust),
      getNas100TrendTrades(cacheBust),
      getNas100TrendKlines(cacheBust),
    ])
    overview.value = ovRes || {}
    allTrades.value = trRes || []
    allKlines.value = klRes || []

    trades.value = [...allTrades.value]
    klines.value = [...allKlines.value]

    tradesSorted.value = [...trades.value].sort(
      (a, b) => new Date(b.trade_time).getTime() - new Date(a.trade_time).getTime(),
    )
    buildDetailRows()
    buildDetailInfoRows()

    // 等待 DOM 根据新数据渲染出图表容器，再初始化 ECharts
    await nextTick()

    renderSignals()
    renderEquity()
    renderProfitStruct()
    renderContribution()
    renderPnlHistogram()
    renderWinLoss()
  } catch (e) {
    console.error('load strategy data error', e)
  } finally {
    loading.value = false
    loadingSignals.value = false
  }
}

function renderEquity() {
  if (!equityChartRef.value || !trades.value.length) return
  if (!chart) {
    chart = echarts.init(equityChartRef.value)
  }
  const initial = 2000000 // 与后端保持一致
  // 使用收益百分比曲线，而不是绝对金额
  const equityPct = trades.value.map((t) => {
    const pnl = t.cum_pnl || 0
    return ((initial + pnl) / initial - 1) * 100
  })
  const x = trades.value.map((t) => t.trade_time.replace('T', ' ').slice(0, 16))
  chart.setOption({
    grid: { left: 60, right: 40, top: 30, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => (v == null ? '' : `${Number(v).toFixed(2)}%`),
    },
    xAxis: {
      type: 'category',
      data: x,
      boundaryGap: false,
      axisLabel: {
        formatter: (v) => {
          // v 形如 "2022-01-17 02:00" 或 ECharts 传入的索引，需兼容
          const str = typeof v === 'string' ? v : (x[Number(v)] || '')
          const d = new Date(str.replace(' ', 'T'))
          if (Number.isNaN(d.getTime())) return String(v)
          const year = d.getFullYear()
          const month = d.getMonth() + 1
          // 统一显示 "YYYY年M月"，避免多年度时只显示 "12月" 等歧义
          return `${year}年${month}月`
        },
      },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        formatter: (v) => `${Number(v).toFixed(0)}%`,
      },
      splitLine: { show: true },
    },
    series: [
      {
        name: '策略收益',
        type: 'line',
        data: equityPct,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#10b981' },
        areaStyle: { opacity: 0.08, color: '#10b981' },
      },
    ],
  })
}

function renderProfitStruct() {
  if (!profitStructRef.value || !overview.value || !trades.value.length) return
  if (!profitStructChart) {
    profitStructChart = echarts.init(profitStructRef.value)
  }
  // 使用 USDT 金额拆分：总盈利 / 未平仓盈亏 / 总亏损 / 手续费 / 总盈亏
  const pnls = trades.value.map((t) => Number(t.pnl || 0))
  // CSV 中每笔交易进/出各一行，毛利润和毛亏损会被计算两次，这里按 2 进行折半
  const grossProfit = pnls
    .filter((p) => p > 0)
    .reduce((s, p) => s + p, 0) / 2
  const grossLossAbs =
    Math.abs(
      pnls.filter((p) => p < 0).reduce((s, p) => s + p, 0),
    ) / 2
  const openPnl = 0
  const ov = overview.value
  // 这里把“总盈亏”强制对齐为顶部卡片里的 27,537,402 USDT
  const net = Number(ov.strategy_profit ?? 0)
  // 手续费 = 总盈利 - 总亏损 - 总盈亏（保证恒等式成立）
  let fee = grossProfit - grossLossAbs - net
  // 手续费按成本处理，用绝对值显示（避免负数看起来奇怪）
  fee = Math.abs(fee)

  const labels = ['总盈利', '未平仓盈亏', '总亏损', '手续费', '总盈亏']
  const values = [grossProfit, openPnl, grossLossAbs, fee, net]
  const maxAbs = Math.max(...values.map((v) => Math.abs(v)))
  // Y 轴最大值按 25M 的整数倍向上取整，避免总盈亏和总亏损“顶到同一高度”
  const step = 25000000
  const axisMax = Math.max(step, Math.ceil(maxAbs / step) * step)

  profitStructChart.setOption({
    grid: { left: 60, right: 20, top: 24, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) =>
        v == null ? '' : `${Number(v).toLocaleString()} USDT`,
    },
    xAxis: { type: 'category', data: labels },
    yAxis: {
      type: 'value',
      max: axisMax,
      interval: axisMax / 4,
      axisLabel: {
        formatter: (v) => `${(v / 1000000).toFixed(0)}M`,
      },
    },
    series: [
      {
        type: 'bar',
        data: values,
        barWidth: '30%',
        itemStyle: {
          color: (params) => {
            const i = params.dataIndex
            if (i === 0) return '#10b981' // 总盈利：绿
            if (i === 1) return '#3b82f6' // 未平仓：蓝
            if (i === 2) return '#ef4444' // 总亏损：红
            if (i === 3) return '#f59e0b' // 手续费：黄
            return '#6366f1' // 总盈亏：紫
          },
        },
      },
    ],
  })
}

function renderContribution() {
  if (!contributionRef.value || !overview.value || !trades.value.length || !klines.value.length) return
  if (!contributionChart) {
    contributionChart = echarts.init(contributionRef.value)
  }
  // 1. 以回测区间对齐买入并持有与策略的时间范围
  const firstTradeTime = new Date(trades.value[0].trade_time).getTime()
  const lastTradeTime = new Date(trades.value[trades.value.length - 1].trade_time).getTime()
  const slicedKlines = klines.value.filter((k) => {
    const ts = new Date(k.timestamp).getTime()
    return ts >= firstTradeTime && ts <= lastTradeTime
  })
  if (!slicedKlines.length) return

  // 2. 买入并持有收益曲线（基于与策略同一时段的 K 线）
  const firstClose = slicedKlines[0].close || 1
  const bhPctSeries = slicedKlines.map((k) => (k.close / firstClose - 1) * 100)
  const bhMin = Math.min(...bhPctSeries)
  const bhMax = Math.max(...bhPctSeries)
  const bhCurrent = bhPctSeries[bhPctSeries.length - 1]

  // 3. 策略收益曲线（基于累计 PnL）
  const initial = 2000000
  const equityPct = trades.value.map((t) => {
    const pnl = t.cum_pnl || 0
    return ((initial + pnl) / initial - 1) * 100
  })
  // TradingView 中策略最小一般从 0 开始，为保持外观一致，这里将策略最小值钉在 0
  const stratMin = 0
  const stratMax = Math.max(...equityPct)
  const stratCurrent = equityPct[equityPct.length - 1]

  const yMin = Math.min(bhMin, stratMin) - 10
  const yMax = Math.max(bhMax, stratMax) + 10

  contributionChart.setOption({
    title: { text: '基准', left: 0, top: 0, textStyle: { fontSize: 13 } },
    grid: { left: 60, right: 60, top: 32, bottom: 40 },
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const { seriesName, data } = p
        const label = data.label
        return `${seriesName}<br/>${label} ${Number(data.value[1]).toFixed(2)}%`
      },
    },
    legend: {
      bottom: 0,
      data: ['买入和持有的损益', '策略损益'],
    },
    xAxis: {
      type: 'category',
      data: ['买入持有', '策略损益'],
      axisLine: { show: true },
      axisTick: { show: true },
    },
    yAxis: {
      type: 'value',
      min: yMin,
      max: yMax,
      axisLabel: { formatter: (v) => `${v.toFixed(0)}%` },
      splitLine: { show: true },
    },
    series: [
      {
        name: '买入和持有的损益',
        type: 'scatter',
        symbolSize: 10,
        itemStyle: { color: '#f59e0b' },
        data: [
          { x: '买入持有', y: bhMin, label: '最小' },
          { x: '买入持有', y: bhCurrent, label: '当前' },
          { x: '买入持有', y: bhMax, label: '最大' },
        ].map((d) => ({
          value: [d.x, d.y],
          label: d.label,
        })),
        label: {
          show: true,
          position: 'left',
          formatter: (p) => `${p.data.label} ${Number(p.data.value[1]).toFixed(2)}%`,
        },
      },
      {
        name: '策略损益',
        type: 'scatter',
        symbolSize: 10,
        itemStyle: { color: '#3b82f6' },
        data: [
          { x: '策略损益', y: stratMin, label: '最小' },
          { x: '策略损益', y: stratCurrent, label: '当前' },
          { x: '策略损益', y: stratMax, label: '最大' },
        ].map((d) => ({
          value: [d.x, d.y],
          label: d.label,
        })),
        label: {
          show: true,
          position: 'right',
          formatter: (p) => `${p.data.label} ${Number(p.data.value[1]).toFixed(2)}%`,
        },
      },
    ],
  })
}

function renderSignals() {
  if (!signalChartRef.value || !klines.value.length) return
  if (!klineChart) {
    klineChart = echarts.init(signalChartRef.value)
  }

  const x = klines.value.map((k) => k.timestamp.slice(0, 16).replace('T', ' '))
  const ohlc = klines.value.map((k) => [k.open, k.close, k.low, k.high])

  // 根据交易时间在 K 线上打点（进场↑、出场/止损↓）
  const buyPoints = []
  const sellPoints = []

  function findIndexByTime(tStr) {
    const t = new Date(tStr).getTime()
    let idx = klines.value.findIndex((k) => new Date(k.timestamp).getTime() >= t)
    if (idx === -1) idx = klines.value.length - 1
    return idx
  }

  for (const tr of trades.value) {
    const idx = findIndexByTime(tr.trade_time)
    if (idx < 0) continue
    const price = tr.price
    const tp = String(tr.trade_type || '')
    const sig = String(tr.signal || '').toLowerCase()
    if (tp.includes('进') || tp.includes('入场') || /^long\s*\d+$/.test(sig.trim())) {
      buyPoints.push([idx, price])
    } else if (tp.includes('出') || tp.includes('出场') || tp.includes('止损') || tp.toLowerCase().includes('close') || sig.includes('close')) {
      sellPoints.push([idx, price])
    }
  }

  klineChart.setOption({
    tooltip: {
      trigger: 'axis',
    },
    xAxis: {
      type: 'category',
      data: x,
      boundaryGap: true,
    },
    yAxis: {
      type: 'value',
      scale: true,
    },
    dataZoom: (() => {
      // 默认只显示最近 3 个月，避免全部数据时看不清
      const total = x.length
      const bars2hPerMonth = 12 * 30 // 2h 线每天 12 根，每月约 360 根
      const barsToShow = Math.min(total, bars2hPerMonth * 3)
      const startPct = total <= barsToShow ? 0 : ((total - barsToShow) / total * 100)
      return [
        { type: 'inside', start: startPct, end: 100 },
        { type: 'slider', start: startPct, end: 100, height: 18 },
      ]
    })(),
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: '#ec0000',
          color0: '#00b15d',
          borderColor: '#ec0000',
          borderColor0: '#00b15d',
        },
      },
      {
        name: '趋入',
        type: 'scatter',
        symbol: 'triangle',
        symbolSize: 16,
        symbolRotate: 0,
        itemStyle: {
          color: '#00b15d',
          borderColor: '#fff',
          borderWidth: 2,
        },
        label: {
          show: true,
          position: 'top',
          formatter: '趋入',
          color: '#00b15d',
          fontSize: 12,
          fontWeight: 'bold',
        },
        data: buyPoints.map(([i, p]) => [x[i], p]),
      },
      {
        name: '趋出',
        type: 'scatter',
        symbol: 'triangle',
        symbolRotate: 180,
        symbolSize: 16,
        itemStyle: {
          color: '#ff4d4f',
          borderColor: '#fff',
          borderWidth: 2,
        },
        label: {
          show: true,
          position: 'bottom',
          formatter: '趋出',
          color: '#ff4d4f',
          fontSize: 12,
          fontWeight: 'bold',
        },
        data: sellPoints.map(([i, p]) => [x[i], p]),
      },
    ],
  })
}

function renderPnlHistogram() {
  if (!pnlHistRef.value || !trades.value.length) return
  if (!pnlHistChart) {
    pnlHistChart = echarts.init(pnlHistRef.value)
  }
  // 只按“完成的一笔交易”统计：一买一卖算 1 笔（类型含 出/出场/止损 或信号含 close）
  const exitTrades = trades.value.filter((t) => {
    const tp = String(t.trade_type || '')
    const sig = String(t.signal || '').toLowerCase()
    return tp.includes('出') || tp.includes('出场') || tp.includes('止损') || tp.toLowerCase().includes('close') || sig.includes('close')
  })
  const source = exitTrades.length ? exitTrades : trades.value

  const pnls = source.map((t) => t.pnl_pct)

  // 固定区间：-6% ~ 16%，步长 2%，与截图上的刻度对齐
  const bins = []
  const labels = []
  const lossCounts = []
  const winCounts = []

  for (let v = -6; v < 16; v += 2) {
    const a = v
    const b = v + 2
    bins.push([a, b])
    labels.push(`${a}%`)
    lossCounts.push(pnls.filter((x) => x < 0 && x >= a && x < b).length)
    winCounts.push(pnls.filter((x) => x >= 0 && x >= a && x < b).length)
  }

  const avgLoss =
    pnls.filter((x) => x < 0).reduce((s, x) => s + x, 0) /
    Math.max(1, pnls.filter((x) => x < 0).length)
  const avgWin =
    pnls.filter((x) => x > 0).reduce((s, x) => s + x, 0) /
    Math.max(1, pnls.filter((x) => x > 0).length)

  pnlHistChart.setOption({
    grid: { left: 40, right: 20, top: 30, bottom: 40 },
    tooltip: { trigger: 'axis' },
    legend: {
      data: ['亏损', '获利', '平均亏损', '平均获利'],
      top: 0,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { rotate: 45 },
    },
    yAxis: { type: 'value' },
    series: [
      {
        name: '亏损',
        type: 'bar',
        stack: 'pnl',
        data: lossCounts,
        itemStyle: { color: '#ef4444' },
      },
      {
        name: '获利',
        type: 'bar',
        stack: 'pnl',
        data: winCounts,
        itemStyle: { color: '#10b981' },
      },
      {
        name: '平均亏损',
        type: 'line',
        data: labels.map((_, idx) => {
          const [a, b] = bins[idx]
          return avgLoss >= a && avgLoss < b ? Math.max(...lossCounts, ...winCounts) : null
        }),
        lineStyle: {
          type: 'dashed',
          color: '#ef4444',
        },
        symbol: 'none',
      },
      {
        name: '平均获利',
        type: 'line',
        data: labels.map((_, idx) => {
          const [a, b] = bins[idx]
          return avgWin >= a && avgWin < b ? Math.max(...lossCounts, ...winCounts) : null
        }),
        lineStyle: {
          type: 'dashed',
          color: '#10b981',
        },
        symbol: 'none',
      },
    ],
    graphic: [
      {
        type: 'text',
        left: 'center',
        bottom: 4,
        style: {
          text: `平均亏损：${avgLoss.toFixed(2)}%    平均获利：${avgWin.toFixed(2)}%`,
          fill: '#6b7280',
          fontSize: 11,
        },
      },
    ],
  })
}

function renderWinLoss() {
  if (!winLossRef.value || !trades.value.length) return
  if (!winLossChart) {
    winLossChart = echarts.init(winLossRef.value)
  }
  // 只把“卖出/止损”的那一行算作一笔交易的结果，一买一卖才算 1 次
  const exitTrades = trades.value.filter((t) => {
    const tp = String(t.trade_type || '')
    const sig = String(t.signal || '').toLowerCase()
    return tp.includes('出') || tp.includes('出场') || tp.includes('止损') || tp.toLowerCase().includes('close') || sig.includes('close')
  })
  const base = exitTrades.length ? exitTrades : trades.value
  // 按 trade_no 去重，一买一卖只算 1 笔
  const uniqMap = new Map()
  for (const t of base) {
    const raw = t.trade_no ?? 0
    const key = Number.isFinite(Number(raw)) ? Number(raw) : raw
    uniqMap.set(key, t)
  }
  const uniqBase = Array.from(uniqMap.values())

  const wins = uniqBase.filter((t) => t.pnl > 0).length
  const losses = uniqBase.filter((t) => t.pnl < 0).length
  const flats = uniqBase.length - wins - losses
  const total = uniqBase.length
  const winPct = total ? (wins / total) * 100 : 0
  const lossPct = total ? (losses / total) * 100 : 0
  const flatPct = total ? (flats / total) * 100 : 0

  winLossChart.setOption({
    tooltip: { trigger: 'item' },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      formatter(name) {
        if (name === '盈利') return `盈利   ${wins} 笔交易   ${winPct.toFixed(2)}%`
        if (name === '亏损') return `亏损   ${losses} 笔交易   ${lossPct.toFixed(2)}%`
        return `盈亏平衡   ${flats} 笔交易   ${flatPct.toFixed(2)}%`
      },
    },
    series: [
      {
        name: '胜/负比率',
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: false,
        label: {
          show: true,
          position: 'center',
          formatter: `${total}\n总交易`,
          fontSize: 16,
          lineHeight: 22,
        },
        data: [
          { value: wins, name: '盈利', itemStyle: { color: '#10b981' } },
          { value: losses, name: '亏损', itemStyle: { color: '#ef4444' } },
          { value: flats, name: '盈亏平衡', itemStyle: { color: '#f97316' } },
        ],
      },
    ],
  })
}

onMounted(() => {
  loadData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (chart) {
    chart.dispose()
    chart = null
  }
  if (klineChart) {
    klineChart.dispose()
    klineChart = null
  }
  if (pnlHistChart) {
    pnlHistChart.dispose()
    pnlHistChart = null
  }
  if (winLossChart) {
    winLossChart.dispose()
    winLossChart = null
  }
  if (profitStructChart) {
    profitStructChart.dispose()
    profitStructChart = null
  }
  if (contributionChart) {
    contributionChart.dispose()
    contributionChart = null
  }
})

function handleResize() {
  if (chart) chart.resize()
  if (klineChart) klineChart.resize()
  if (pnlHistChart) pnlHistChart.resize()
  if (winLossChart) winLossChart.resize()
  if (profitStructChart) profitStructChart.resize()
  if (contributionChart) contributionChart.resize()
}
</script>

<style scoped>
.strategy-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.title-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.title-main {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.title-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.title-row h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
}
.title-row .sub {
  margin: 0;
  font-size: 16px;
  color: var(--color-text-muted);
  line-height: 1.6;
}
.back-link {
  font-size: 13px;
  color: var(--color-text-muted);
  white-space: nowrap;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}
.summary-card {
  padding: 14px 12px;
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.summary-card p {
  margin: 0 0 6px 0;
  font-size: 12px;
  color: var(--color-text-muted);
}
.summary-card h3 {
  margin: 0;
  font-size: 18px;
}
.profit {
  color: #10b981;
}
.loss {
  color: #ef4444;
}
.drawdown {
  color: var(--color-text-muted, #64748b);
}
.chart-card {
  margin-top: 4px;
}
.chart-area {
  width: 100%;
  height: 360px;
}
.kline-area {
  width: 100%;
  height: 420px;
}
.analysis-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 8px;
}
.analysis-card {
  margin-top: 4px;
}
.chart-area-small {
  width: 100%;
  height: 260px;
}
.empty {
  padding: 16px;
  color: var(--color-text-muted);
  font-size: 13px;
}

.metrics-card {
  margin-top: 8px;
}

.metrics-table :deep(.el-table__cell) {
  padding-top: 10px;
  padding-bottom: 10px;
  font-size: 13px;
}

.metrics-table :deep(.el-table__header-wrapper th) {
  font-size: 13px;
}

.trades-card {
  margin-top: 8px;
}

.trades-table {
  width: 100%;
}

.filter-row {
  margin-left: auto;
  margin-top: 6px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.date-picker {
  max-width: 220px;
}
</style>

