<template>
  <div class="page stock-ai-page">
    <div class="title-row">
      <h2>A股 AI 选股</h2>
      <p class="subtitle">按板块、行业筛选，结合 MACD / RSI / KDJ / 量比等指标综合打分，偏多标的供短期（3～5 日）关注参考，非涨跌预测</p>
    </div>

    <el-card class="filter-card">
      <template #header>筛选条件（不选则默认全部）</template>
      <p class="filter-tip">选股会逐只拉取日线数据（来源：腾讯/新浪/东方财富），<strong>接口较慢或限流时等待会较长</strong>。可把「返回数量」或「回溯天数」调小以加快。若已用 pytdx 拉过全市场 K 线，可先点「刷新 K 线缓存」再做选股，可得到全市场得分前 N。</p>
      <el-form :model="form" label-width="100px" class="filter-form">
        <el-form-item label="板块">
          <el-select
            v-model="form.boards"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="全部板块"
            class="filter-select"
            clearable
          >
            <el-option v-for="opt in boardOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="行业">
          <el-select
            v-model="form.industries"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="全部行业"
            class="filter-select filter-select-wide"
            clearable
          >
            <el-option v-for="opt in industryOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="返回数量">
          <el-input-number v-model="form.top_n" :min="0" :max="100" :step="5" />
        </el-form-item>
        <el-form-item label="最低得分">
          <el-input-number v-model="form.min_score" :min="0" :max="100" :step="5" :precision="1" />
        </el-form-item>
        <el-form-item label="回溯天数">
          <el-input-number v-model="form.lookback_days" :min="30" :max="250" :step="30" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="runScreen">开始选股</el-button>
          <el-button @click="resetForm">重置</el-button>
          <el-button plain type="primary" :loading="cacheRefreshing" @click="runRefreshCache">刷新 K 线缓存</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="single-analyze-card">
      <template #header>
        <span>股票分析</span>
      </template>
      <p class="single-analyze-desc">输入 6 位 A 股代码（如 000001、600519），从数据源拉取日 K 线后由 DeepSeek 进行技术分析，需配置 DEEPSEEK_API_KEY。</p>
      <div class="single-analyze-row">
        <el-input
          v-model="singleStockCode"
          placeholder="输入股票代码，如 000001"
          clearable
          maxlength="6"
          show-word-limit
          style="width: 200px; margin-right: 12px"
          @keyup.enter="runSingleAnalyze"
        />
        <el-button type="primary" :loading="singleAnalyzing" @click="runSingleAnalyze">DeepSeek 分析</el-button>
      </div>
      <div v-if="singleAnalysis" class="ai-analysis-block single-result">
        <p class="ai-label">DeepSeek 分析结果</p>
        <pre class="ai-content">{{ singleAnalysis }}</pre>
      </div>
    </el-card>

    <el-card class="train-card">
      <template #header>
        <span>模型训练（首次使用必做）</span>
        <el-button type="warning" size="small" :loading="trainLoading" @click="runTrain">执行模型训练</el-button>
      </template>
      <p class="predict-desc">训练「未来 3~5 日涨跌」预测模型，约 2~5 分钟。训练完成后即可使用下方「每日预测」。若报错可改用命令行：在项目根执行 <code>python backpack_quant_trading/run_train_stock_model.py</code></p>
      <div v-if="trainMessage" :class="trainSuccess ? 'train-ok' : 'screen-error'">{{ trainMessage }}</div>
    </el-card>

    <el-card class="predict-card">
      <template #header>
        <span>每日预测（未来 3~5 日看涨）</span>
        <el-button type="primary" size="small" :loading="dailyPredictLoading" @click="fetchDailyPredict(false, null)">获取今日预测</el-button>
        <el-button size="small" :loading="dailyPredictLoading" @click="fetchDailyPredict(true, null)">强制刷新</el-button>
        <el-button type="success" size="small" :loading="dailyPredictLoading" :disabled="!results.length" @click="fetchDailyPredict(true, results)">对选股结果预测</el-button>
      </template>
      <p class="predict-desc">
        请先完成上方「模型训练」后再使用。<br>
        <strong>逻辑说明：</strong><br>
        · 「获取今日预测」：从全市场主板按代码顺序取前 80 只，用模型算每只的「未来 3~5 日看涨概率」，按概率排序后给出<strong>看涨概率最高的 20 只</strong>。与下方选股结果不是同一批股票。<br>
        · 「对选股结果预测」：用<strong>当前选股结果</strong>作为股票池，对这批股票算看涨概率并排序，与选股表一致。
        <br><span class="predict-hint">看涨概率为模型相对排序，数值低不代表看跌；AI 解读为技术面短周期建议，可与预测结果综合参考。</span>
      </p>
      <div v-if="dailyPredictError" class="screen-error">{{ dailyPredictError }}</div>
      <div v-else-if="dailyPredictList.length === 0 && !dailyPredictLoading" class="empty">点击「获取今日预测」拉取当日看涨排序</div>
      <el-table v-else :data="dailyPredictList" stripe border class="result-table" max-height="320">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column prop="code" label="代码" width="90" />
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column label="看涨概率" width="100">
          <template #default="{ row }">
            <span :class="probaClass(row.proba_up)">{{ (row.proba_up != null ? row.proba_up * 100 : 0).toFixed(1) }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="最新价" width="85">
          <template #default="{ row }">{{ row.close != null ? row.close.toFixed(2) : '-' }}</template>
        </el-table-column>
        <el-table-column label="更新日期" width="110">{{ dailyPredictDate || '-' }}</el-table-column>
      </el-table>
    </el-card>

    <el-card class="result-card">
      <template #header>
        <span>选股结果（共 {{ results.length }} 只）<template v-if="candidatesCount > 0"> · {{ fromFullMarket ? '全市场 ' + candidatesCount + ' 只中得分前 ' + results.length + ' 只' : '从 ' + candidatesCount + ' 只中选出' }}</template></span>
        <span v-if="usedFilters" class="used-filters">已筛选：{{ usedFilters }}</span>
        <el-button v-if="results.length > 0" type="success" size="small" :loading="analyzing" @click="runAnalyze">DeepSeek AI 解读</el-button>
      </template>
      <div v-if="screenError" class="screen-error">{{ screenError }}</div>
      <div v-if="aiAnalysis" class="ai-analysis-block">
        <p class="ai-label">DeepSeek 解读与建议</p>
        <pre class="ai-content">{{ aiAnalysis }}</pre>
      </div>
      <div v-if="results.length === 0 && !loading && !screenError" class="empty">
        {{ screenDoneOnce ? '本次未筛出符合条件的股票，可调低「最低得分」或更换板块/行业后重试' : '请选择条件后点击「开始选股」，或保持默认全部进行选股' }}
      </div>
      <el-table v-else :data="results" stripe border class="result-table" max-height="560">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column prop="code" label="代码" width="90" />
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column prop="market" label="市场" width="70" />
        <el-table-column prop="score" label="综合得分" width="95" sortable>
          <template #default="{ row }">
            <span :class="scoreClass(row.score)">{{ row.score != null ? row.score.toFixed(1) : '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="close" label="最新价" width="85">
          <template #default="{ row }">{{ row.close != null ? row.close.toFixed(2) : '-' }}</template>
        </el-table-column>
        <el-table-column prop="pct_chg" label="涨跌幅%" width="90">
          <template #default="{ row }">
            <span :class="pctClass(row.pct_chg)">{{ row.pct_chg != null ? row.pct_chg.toFixed(2) + '%' : '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="MACD" width="95">
          <template #default="{ row }">
            <span v-if="row.details && row.details.macd_hist != null">
              {{ row.details.macd_hist >= 0 ? '红柱 ' : '绿柱 ' }}{{ row.details.macd_hist >= 0 ? row.details.macd_hist.toFixed(2) : (-row.details.macd_hist).toFixed(2) }}
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="RSI" width="75">
          <template #default="{ row }">{{ row.details && row.details.rsi != null ? row.details.rsi.toFixed(0) : '-' }}</template>
        </el-table-column>
        <el-table-column label="KDJ(J)" width="80">
          <template #default="{ row }">{{ row.details && row.details.kdj_j != null ? row.details.kdj_j.toFixed(0) : '-' }}</template>
        </el-table-column>
        <el-table-column label="量比" width="75">
          <template #default="{ row }">{{ row.details && row.details.volume_ratio != null ? row.details.volume_ratio.toFixed(2) : '-' }}</template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="180">
          <template #default="{ row }">
            <span class="detail-hint">{{ row.description || '量价/均线等已计入综合得分' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { getBoards, getIndustries, screenStocks, analyzeStocksWithDaily, analyzeSingleStock, getDailyPredict, trainModel, refreshKlineCache } from '../api/stockAi'

// 本地默认选项，接口失败时仍可显示下拉
const DEFAULT_BOARD_OPTIONS = [
  { value: '主板', label: '主板（沪市+深市）' },
  { value: '创业板', label: '创业板' },
  { value: '科创板', label: '科创板' },
  { value: '北交所', label: '北交所' },
]
const DEFAULT_INDUSTRY_OPTIONS = [
  { value: '化学原料', label: '化学原料' },
  { value: '贵金属', label: '贵金属' },
  { value: '电力', label: '电力' },
  { value: '银行', label: '银行' },
  { value: '半导体', label: '半导体' },
]
const boardOptions = ref([...DEFAULT_BOARD_OPTIONS])
const industryOptions = ref([...DEFAULT_INDUSTRY_OPTIONS])
const loading = ref(false)
const analyzing = ref(false)
const results = ref([])
const aiAnalysis = ref('')
const screenError = ref('')
const screenDoneOnce = ref(false)
const candidatesCount = ref(0)
const fromFullMarket = ref(false)
const dailyPredictList = ref([])
const dailyPredictLoading = ref(false)
const dailyPredictError = ref('')
const dailyPredictDate = ref('')
const trainLoading = ref(false)
const trainMessage = ref('')
const trainSuccess = ref(false)
const cacheRefreshing = ref(false)
const singleStockCode = ref('')
const singleAnalyzing = ref(false)
const singleAnalysis = ref('')
const form = reactive({
  boards: [],
  industries: [],
  top_n: 30,
  min_score: 0,
  lookback_days: 120,
})

const usedFilters = computed(() => {
  const parts = []
  if (form.boards && form.boards.length) parts.push('板块: ' + form.boards.join(', '))
  if (form.industries && form.industries.length) parts.push('行业: ' + form.industries.join(', '))
  return parts.length ? parts.join('；') : ''
})

function scoreClass(score) {
  if (score == null) return ''
  if (score >= 70) return 'score-high'
  if (score >= 50) return 'score-mid'
  return 'score-low'
}

function pctClass(pct) {
  if (pct == null) return ''
  if (pct > 0) return 'pct-up'
  if (pct < 0) return 'pct-down'
  return ''
}

function probaClass(proba) {
  if (proba == null) return ''
  if (proba >= 0.6) return 'score-high'
  if (proba >= 0.5) return 'score-mid'
  return 'score-low'
}

async function runRefreshCache() {
  cacheRefreshing.value = true
  try {
    const res = await refreshKlineCache()
    if (res && res.ok) {
      ElMessage.success(res.message || `缓存已更新，新增 ${res.rows_added || 0} 条，最新日期 ${res.max_date || '-'}`)
    } else {
      ElMessage.warning(res?.message || '刷新失败')
    }
  } catch (e) {
    const msg = e.response?.data?.detail ?? e.message ?? '请求失败'
    ElMessage.error(msg)
  } finally {
    cacheRefreshing.value = false
  }
}

async function runTrain() {
  trainLoading.value = true
  trainMessage.value = ''
  trainSuccess.value = false
  try {
    const res = await trainModel({
  stock_codes: ['000001', '000002', '600000', '600519', '000858', '601318', '000333', '600036'],
  forward_days: 5,
  lookback_days: 500,
})
    if (res.ok) {
      trainSuccess.value = true
      trainMessage.value = `训练完成。模型已保存，样本数 ${res.n_samples}，股票数 ${res.n_stocks}。可点击「获取今日预测」。`
      ElMessage.success('模型训练完成')
    } else {
      trainMessage.value = res.error || '训练失败'
      ElMessage.error(trainMessage.value)
    }
  } catch (e) {
    trainMessage.value = e.response?.data?.detail || e.message || '训练请求失败，请检查后端与网络'
    ElMessage.error(trainMessage.value)
  } finally {
    trainLoading.value = false
  }
}

async function fetchDailyPredict(forceRefresh, screenResults) {
  dailyPredictLoading.value = true
  dailyPredictError.value = ''
  const useScreenPool = Array.isArray(screenResults) && screenResults.length > 0
  try {
    const payload = {
      force_refresh: !!forceRefresh || !!useScreenPool,
      top_n: 20,
    }
    if (useScreenPool) {
      payload.stock_codes = screenResults.map(r => r.code).filter(Boolean)
    }
    const res = await getDailyPredict(payload)
    dailyPredictList.value = res.list || []
    dailyPredictDate.value = res.date || ''
    if (res.error) {
      dailyPredictError.value = res.error
    } else if (res.from_cache && !useScreenPool) {
      ElMessage.success('已加载今日缓存结果')
    } else {
      ElMessage.success(useScreenPool ? `已对选股结果预测，共 ${dailyPredictList.value.length} 只` : `今日预测已更新，共 ${dailyPredictList.value.length} 只`)
    }
  } catch (e) {
    dailyPredictError.value = e.response?.data?.detail || e.message || '获取每日预测失败'
    ElMessage.error(dailyPredictError.value)
  } finally {
    dailyPredictLoading.value = false
  }
}

function resetForm() {
  form.boards = []
  form.industries = []
  form.top_n = 30
  form.min_score = 0
  form.lookback_days = 120
}

async function loadOptions() {
  try {
    const [b, i] = await Promise.all([getBoards(), getIndustries()])
    const boards = (b && Array.isArray(b.options) && b.options.length) ? b.options : DEFAULT_BOARD_OPTIONS
    const industries = (i && Array.isArray(i.options) && i.options.length) ? i.options : DEFAULT_INDUSTRY_OPTIONS
    boardOptions.value = boards
    industryOptions.value = industries
  } catch (e) {
    // 接口失败时保留默认选项，避免下拉“无数据”
    boardOptions.value = [...DEFAULT_BOARD_OPTIONS]
    industryOptions.value = [...DEFAULT_INDUSTRY_OPTIONS]
    ElMessage.warning('加载板块/行业接口异常，已使用默认选项')
  }
}

async function runScreen() {
  loading.value = true
  results.value = []
  screenError.value = ''
  candidatesCount.value = 0
  fromFullMarket.value = false
  try {
    const res = await screenStocks({
      boards: form.boards,
      industries: form.industries,
      top_n: form.top_n,
      min_score: form.min_score,
      lookback_days: form.lookback_days,
    })
    results.value = res.list || []
    screenError.value = res.error || ''
    screenDoneOnce.value = true
    candidatesCount.value = res.candidates_count ?? 0
    fromFullMarket.value = res.from_full_market ?? false
    if (res.error) {
      ElMessage.warning(res.error)
    } else {
      const n = candidatesCount.value
      const len = results.value.length
      let msg = n > 0
        ? (fromFullMarket.value ? `全市场 ${n} 只中得分前 ${len} 只` : `共 ${len} 只（从 ${n} 只中选出）`)
        : (len ? `选股完成，共 ${len} 只` : '选股完成，共 0 只。可调低「最低得分」或先点「刷新 K 线缓存」再选股')
      ElMessage.success(msg)
    }
  } catch (e) {
    const isTimeout = e.code === 'ECONNABORTED' || (e.message && String(e.message).toLowerCase().includes('timeout'))
    const msg = e.response?.data?.detail ?? e.response?.data?.error ?? e.message
    const status = e.response?.status
    if (status === 401) {
      screenError.value = '请先登录'
    } else if (isTimeout) {
      screenError.value = '选股请求超时。请将「返回数量」调小（如 10～15）或「回溯天数」调小（如 60）后重试。'
    } else if (msg) {
      screenError.value = typeof msg === 'string' ? msg : String(msg)
    } else {
      screenError.value = status ? `请求失败 (${status})，请检查后端日志` : '选股请求失败，请检查网络或后端是否启动'
    }
    ElMessage.error(screenError.value)
  } finally {
    loading.value = false
  }
  aiAnalysis.value = ''
}

async function runAnalyze() {
  if (!results.value.length) {
    ElMessage.warning('请先执行选股')
    return
  }
  analyzing.value = true
  aiAnalysis.value = ''
  try {
    const res = await analyzeStocksWithDaily(results.value)
    aiAnalysis.value = res.analysis || ''
    if (res.analysis) {
      if (res.analysis.includes('请配置') || res.analysis.includes('接口异常') || res.analysis.includes('超时') || res.analysis.includes('调用失败')) {
        ElMessage.warning('AI 解读返回提示，请查看下方内容')
      } else {
        ElMessage.success('AI 解读完成')
      }
    }
  } catch (e) {
    const msg = e.response?.data?.detail ?? e.message ?? 'AI 解读失败'
    if (e.response?.status === 401) {
      ElMessage.error('请先登录后再使用 AI 解读')
    } else if (msg.includes('timeout') || msg.includes('超时')) {
      ElMessage.error('请求超时，请稍后重试')
    } else {
      ElMessage.error(typeof msg === 'string' ? msg : 'AI 解读失败')
    }
  } finally {
  analyzing.value = false
  }
}

async function runSingleAnalyze() {
  const code = (singleStockCode.value || '').trim()
  if (!code) {
    ElMessage.warning('请输入股票代码')
    return
  }
  singleAnalyzing.value = true
  singleAnalysis.value = ''
  try {
    const res = await analyzeSingleStock(code)
    singleAnalysis.value = res.analysis || ''
    if (res.analysis) {
      if (res.analysis.includes('请配置') || res.analysis.includes('接口异常') || res.analysis.includes('超时') || res.analysis.includes('调用失败') || res.analysis.includes('无法拉取')) {
        ElMessage.warning('请查看下方分析结果或检查配置')
      } else {
        ElMessage.success('股票分析完成')
      }
    }
  } catch (e) {
    const msg = e.response?.data?.detail ?? e.message ?? '股票分析请求失败'
    singleAnalysis.value = msg
    if (e.response?.status === 401) {
      ElMessage.error('请先登录')
    } else {
      ElMessage.error(typeof msg === 'string' ? msg : '股票分析失败')
    }
  } finally {
    singleAnalyzing.value = false
  }
}

onMounted(() => {
  loadOptions()
})
</script>

<style scoped>
.title-row {
  margin-bottom: 20px;
  padding-left: 16px;
  border-left: 4px solid var(--color-primary);
}
.title-row h2 { margin: 0 0 8px 0; font-size: 24px; font-weight: 700; color: var(--color-text); }
.subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-muted);
  line-height: 1.5;
}
.filter-card { margin-bottom: 20px; }
.single-analyze-card { margin-bottom: 20px; }
.single-analyze-desc { margin: 0 0 12px 0; font-size: 12px; color: var(--color-text-muted); }
.single-analyze-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.single-result { margin-top: 12px; }
.filter-tip { margin: 0 0 12px 0; font-size: 12px; color: var(--color-text-muted); line-height: 1.5; }
.filter-tip strong { color: var(--color-primary); }
.train-card { margin-bottom: 20px; }
.train-card code { font-size: 11px; background: var(--color-bg); padding: 2px 6px; border-radius: 4px; }
.train-ok { margin-top: 8px; padding: 10px 12px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; color: #166534; font-size: 13px; }
.predict-card { margin-bottom: 20px; }
.predict-desc { margin: 0 0 12px 0; font-size: 12px; color: var(--color-text-muted); }
.predict-hint { font-size: 11px; color: var(--color-text-muted); opacity: 0.9; }
.filter-form { display: flex; flex-wrap: wrap; gap: 16px 24px; align-items: flex-start; }
.filter-select { width: 220px; }
.filter-select-wide { min-width: 260px; max-width: 360px; }
.result-card :deep(.el-card__header) { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.used-filters { font-size: 12px; color: var(--color-text-muted); }
.empty { text-align: center; padding: 48px; color: var(--color-text-muted); font-size: 14px; }
.result-table { width: 100%; }
.score-high { color: #16a34a; font-weight: 600; }
.score-mid { color: var(--color-text); }
.score-low { color: var(--color-text-muted); }
.pct-up { color: #dc2626; }
.pct-down { color: #16a34a; }
.detail-hint { font-size: 12px; color: var(--color-text-muted); }
.placeholder-tag { font-size: 10px; color: #94a3b8; margin-left: 2px; }
.screen-error { margin-bottom: 12px; padding: 12px 16px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; color: #b91c1c; font-size: 13px; line-height: 1.5; }
.ai-analysis-block { margin-bottom: 16px; padding: 12px 16px; background: var(--color-bg); border-radius: 8px; border: 1px solid var(--color-border); }
.ai-label { margin: 0 0 8px 0; font-size: 13px; font-weight: 600; color: var(--color-primary); }
.ai-content { margin: 0; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; color: var(--color-text); }
</style>
