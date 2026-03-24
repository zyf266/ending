import React, { useEffect, useState } from 'react'
import {
  getBoards,
  getIndustries,
  screenStocks,
  analyzeStocksWithDaily,
  analyzeSingleStock,
  getDailyPredict,
  trainModel,
  refreshKlineCache,
} from '../api/stockAi'
import './StockAi.css'

const DEFAULT_BOARDS = [
  { value: '主板', label: '主板（沪市+深市）' },
  { value: '创业板', label: '创业板' },
  { value: '科创板', label: '科创板' },
  { value: '北交所', label: '北交所' },
]

const DEFAULT_INDUSTRIES = [
  { value: '化学原料', label: '化学原料' },
  { value: '贵金属', label: '贵金属' },
  { value: '电力', label: '电力' },
  { value: '银行', label: '银行' },
  { value: '半导体', label: '半导体' },
]

const scoreClass = (score) => {
  if (score == null) return ''
  if (score >= 70) return 'score-high'
  if (score >= 50) return 'score-mid'
  return 'score-low'
}

const pctClass = (pct) => {
  if (pct == null) return ''
  if (pct > 0) return 'pct-up'
  if (pct < 0) return 'pct-down'
  return ''
}

const probaClass = (proba) => {
  if (proba == null) return ''
  if (proba >= 0.6) return 'score-high'
  if (proba >= 0.5) return 'score-mid'
  return 'score-low'
}

const StockAi = () => {
  const [boardOptions, setBoardOptions] = useState([...DEFAULT_BOARDS])
  const [industryOptions, setIndustryOptions] = useState([...DEFAULT_INDUSTRIES])
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [results, setResults] = useState([])
  const [aiAnalysis, setAiAnalysis] = useState('')
  const [screenError, setScreenError] = useState('')
  const [screenDoneOnce, setScreenDoneOnce] = useState(false)
  const [candidatesCount, setCandidatesCount] = useState(0)
  const [fromFullMarket, setFromFullMarket] = useState(false)
  const [dailyPredictList, setDailyPredictList] = useState([])
  const [dailyPredictLoading, setDailyPredictLoading] = useState(false)
  const [dailyPredictError, setDailyPredictError] = useState('')
  const [dailyPredictDate, setDailyPredictDate] = useState('')
  const [trainLoading, setTrainLoading] = useState(false)
  const [trainMessage, setTrainMessage] = useState('')
  const [trainSuccess, setTrainSuccess] = useState(false)
  const [cacheRefreshing, setCacheRefreshing] = useState(false)
  const [singleStockCode, setSingleStockCode] = useState('')
  const [singleAnalyzing, setSingleAnalyzing] = useState(false)
  const [singleAnalysis, setSingleAnalysis] = useState('')
  const [form, setForm] = useState({
    boards: [],
    industries: [],
    top_n: 30,
    min_score: 0,
    lookback_days: 120,
  })

  const usedFilters = [
    ...(form.boards?.length ? ['板块: ' + form.boards.join(', ')] : []),
    ...(form.industries?.length ? ['行业: ' + form.industries.join(', ')] : []),
  ].join('；')

  const loadOptions = async () => {
    try {
      const [b, i] = await Promise.all([getBoards(), getIndustries()])
      const boards =
        b?.options?.length ? b.options : DEFAULT_BOARDS
      const industries =
        i?.options?.length ? i.options : DEFAULT_INDUSTRIES
      setBoardOptions(boards)
      setIndustryOptions(industries)
    } catch (_) {
      setBoardOptions([...DEFAULT_BOARDS])
      setIndustryOptions([...DEFAULT_INDUSTRIES])
    }
  }

  useEffect(() => {
    loadOptions()
  }, [])

  const runRefreshCache = async () => {
    setCacheRefreshing(true)
    try {
      const res = await refreshKlineCache()
      if (res?.ok) {
        alert(res.message || `缓存已更新，新增 ${res.rows_added || 0} 条，最新日期 ${res.max_date || '-'}`)
      } else {
        alert(res?.message || '刷新失败')
      }
    } catch (e) {
      alert(e?.response?.data?.detail ?? e?.message ?? '请求失败')
    } finally {
      setCacheRefreshing(false)
    }
  }

  const runTrain = async () => {
    setTrainLoading(true)
    setTrainMessage('')
    setTrainSuccess(false)
    try {
      const res = await trainModel({
        stock_codes: ['000001', '000002', '600000', '600519', '000858', '601318', '000333', '600036'],
        forward_days: 5,
        lookback_days: 500,
      })
      if (res.ok) {
        setTrainSuccess(true)
        setTrainMessage(
          `训练完成。模型已保存，样本数 ${res.n_samples}，股票数 ${res.n_stocks}。可点击「获取今日预测」。`
        )
        alert('模型训练完成')
      } else {
        const errMsg = res.error || '训练失败'
        setTrainMessage(errMsg)
        alert(errMsg)
      }
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || '训练请求失败，请检查后端与网络'
      setTrainMessage(msg)
      alert(msg)
    } finally {
      setTrainLoading(false)
    }
  }

  const fetchDailyPredict = async (forceRefresh, screenResults) => {
    setDailyPredictLoading(true)
    setDailyPredictError('')
    const useScreenPool = Array.isArray(screenResults) && screenResults.length > 0
    try {
      const payload = { force_refresh: !!forceRefresh || !!useScreenPool, top_n: 20 }
      if (useScreenPool) payload.stock_codes = screenResults.map((r) => r.code).filter(Boolean)
      const res = await getDailyPredict(payload)
      setDailyPredictList(res.list || [])
      setDailyPredictDate(res.date || '')
      if (res.error) setDailyPredictError(res.error)
      else alert(useScreenPool ? `已对选股结果预测，共 ${(res.list || []).length} 只` : `今日预测已更新，共 ${(res.list || []).length} 只`)
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || '获取每日预测失败'
      setDailyPredictError(msg)
      alert(msg)
    } finally {
      setDailyPredictLoading(false)
    }
  }

  const resetForm = () => {
    setForm({
      boards: [],
      industries: [],
      top_n: 30,
      min_score: 0,
      lookback_days: 120,
    })
  }

  const runScreen = async () => {
    setLoading(true)
    setResults([])
    setScreenError('')
    setCandidatesCount(0)
    setFromFullMarket(false)
    try {
      const res = await screenStocks({
        boards: form.boards,
        industries: form.industries,
        top_n: form.top_n,
        min_score: form.min_score,
        lookback_days: form.lookback_days,
      })
      setResults(res.list || [])
      setScreenError(res.error || '')
      setScreenDoneOnce(true)
      setCandidatesCount(res.candidates_count ?? 0)
      setFromFullMarket(res.from_full_market ?? false)
      if (res.error) alert(res.error)
      else {
        const n = res.candidates_count ?? 0
        const len = (res.list || []).length
        const fromFull = res.from_full_market ?? false
        alert(
          n > 0
            ? fromFull
              ? `全市场 ${n} 只中得分前 ${len} 只`
              : `共 ${len} 只（从 ${n} 只中选出）`
            : len
              ? `选股完成，共 ${len} 只`
              : '选股完成，共 0 只。可调低「最低得分」或先点「刷新 K 线缓存」再选股'
        )
      }
    } catch (e) {
      const msg =
        e?.response?.data?.detail ?? e?.response?.data?.error ?? e?.message
      const status = e?.response?.status
      const errStr = status === 401 ? '请先登录' : (msg ? (typeof msg === 'string' ? msg : String(msg)) : '选股请求失败，请检查网络或后端是否启动')
      setScreenError(errStr)
      alert(errStr)
    } finally {
      setLoading(false)
    }
    setAiAnalysis('')
  }

  const runAnalyze = async () => {
    if (!results.length) {
      alert('请先执行选股')
      return
    }
    setAnalyzing(true)
    setAiAnalysis('')
    try {
      const res = await analyzeStocksWithDaily(results)
      setAiAnalysis(res.analysis || '')
      if (res.analysis) alert('AI 解读完成')
    } catch (e) {
      const msg = e?.response?.data?.detail ?? e?.message ?? 'AI 解读失败'
      alert(typeof msg === 'string' ? msg : 'AI 解读失败')
    } finally {
      setAnalyzing(false)
    }
  }

  const runSingleAnalyze = async () => {
    const code = (singleStockCode || '').trim()
    if (!code) {
      alert('请输入股票代码')
      return
    }
    setSingleAnalyzing(true)
    setSingleAnalysis('')
    try {
      const res = await analyzeSingleStock(code)
      setSingleAnalysis(res.analysis || '')
      if (res.analysis) alert('股票分析完成')
    } catch (e) {
      const msg = e?.response?.data?.detail ?? e?.message ?? '股票分析请求失败'
      setSingleAnalysis(msg)
      alert(typeof msg === 'string' ? msg : '股票分析失败')
    } finally {
      setSingleAnalyzing(false)
    }
  }

  return (
    <div className="page stock-ai-page">
      <div className="title-row">
        <h2>A股 AI 选股</h2>
        <p className="subtitle">
          按板块、行业筛选，结合 MACD / RSI / KDJ / 量比等指标综合打分，偏多标的供短期（3～5 日）关注参考，非涨跌预测
        </p>
      </div>

      <div className="filter-card card-block">
        <div className="card-block-header">筛选条件（不选则默认全部）</div>
        <p className="filter-tip">
          选股会逐只拉取日线数据（来源：腾讯/新浪/东方财富），<strong>接口较慢或限流时等待会较长</strong>。可把「返回数量」或「回溯天数」调小以加快。
        </p>
        <div className="filter-form">
          <div className="form-item">
            <label>板块</label>
            <select
              multiple
              value={form.boards}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  boards: Array.from(e.target.selectedOptions).map((o) => o.value),
                }))
              }
              className="filter-select"
            >
              {boardOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div className="form-item">
            <label>行业</label>
            <select
              multiple
              value={form.industries}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  industries: Array.from(e.target.selectedOptions).map((o) => o.value),
                }))
              }
              className="filter-select filter-select-wide"
            >
              {industryOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div className="form-item">
            <label>返回数量</label>
            <input
              type="number"
              min={0}
              max={100}
              step={5}
              value={form.top_n}
              onChange={(e) => setForm((prev) => ({ ...prev, top_n: Number(e.target.value) }))}
            />
          </div>
          <div className="form-item">
            <label>最低得分</label>
            <input
              type="number"
              min={0}
              max={100}
              step={5}
              value={form.min_score}
              onChange={(e) => setForm((prev) => ({ ...prev, min_score: Number(e.target.value) }))}
            />
          </div>
          <div className="form-item">
            <label>回溯天数</label>
            <input
              type="number"
              min={30}
              max={250}
              step={30}
              value={form.lookback_days}
              onChange={(e) => setForm((prev) => ({ ...prev, lookback_days: Number(e.target.value) }))}
            />
          </div>
          <div className="form-item">
            <button type="button" className="btn-primary" disabled={loading} onClick={runScreen}>
              {loading ? '选股中...' : '开始选股'}
            </button>
            <button type="button" className="btn-default" onClick={resetForm}>
              重置
            </button>
            <button type="button" className="btn-warning" disabled={cacheRefreshing} onClick={runRefreshCache}>
              {cacheRefreshing ? '刷新中...' : '刷新 K 线缓存'}
            </button>
          </div>
        </div>
      </div>

      <div className="single-analyze-card card-block">
        <div className="card-block-header">股票分析</div>
        <p className="single-analyze-desc">
          输入 6 位 A 股代码（如 000001、600519），从数据源拉取日 K 线后由 DeepSeek 进行技术分析，需配置 DEEPSEEK_API_KEY。
        </p>
        <div className="single-analyze-row">
          <input
            value={singleStockCode}
            onChange={(e) => setSingleStockCode(e.target.value.slice(0, 6))}
            placeholder="输入股票代码，如 000001"
            maxLength={6}
            className="code-input"
            onKeyDown={(e) => e.key === 'Enter' && runSingleAnalyze()}
          />
          <button type="button" className="btn-primary" disabled={singleAnalyzing} onClick={runSingleAnalyze}>
            {singleAnalyzing ? '分析中...' : 'DeepSeek 分析'}
          </button>
        </div>
        {singleAnalysis && (
          <div className="ai-analysis-block single-result">
            <p className="ai-label">DeepSeek 分析结果</p>
            <pre className="ai-content">{singleAnalysis}</pre>
          </div>
        )}
      </div>

      <div className="predict-card card-block">
        <div className="card-block-header">
          <span>每日预测（未来 3~5 日看涨）</span>
          <button type="button" className="btn-primary-sm" disabled={dailyPredictLoading} onClick={() => fetchDailyPredict(false, null)}>
            获取今日预测
          </button>
          <button type="button" className="btn-default-sm" disabled={dailyPredictLoading} onClick={() => fetchDailyPredict(true, null)}>
            强制刷新
          </button>
          <button
            type="button"
            className="btn-success-sm"
            disabled={dailyPredictLoading || !results.length}
            onClick={() => fetchDailyPredict(true, results)}
          >
            对选股结果预测
          </button>
        </div>
        <p className="predict-desc">
          请先完成上方「模型训练」后再使用。逻辑说明：「获取今日预测」从全市场主板取前 80 只算看涨概率排序；「对选股结果预测」用当前选股结果作为股票池算看涨概率。
        </p>
        {dailyPredictError && <div className="screen-error">{dailyPredictError}</div>}
        {!dailyPredictError && dailyPredictList.length === 0 && !dailyPredictLoading && (
          <div className="empty">点击「获取今日预测」拉取当日看涨排序</div>
        )}
        {dailyPredictList.length > 0 && (
          <table className="result-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>代码</th>
                <th>名称</th>
                <th>看涨概率</th>
                <th>最新价</th>
                <th>更新日期</th>
              </tr>
            </thead>
            <tbody>
              {dailyPredictList.map((row, i) => (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td>{row.code}</td>
                  <td>{row.name}</td>
                  <td className={probaClass(row.proba_up)}>
                    {row.proba_up != null ? (row.proba_up * 100).toFixed(1) : 0}%
                  </td>
                  <td>{row.close != null ? row.close.toFixed(2) : '-'}</td>
                  <td>{dailyPredictDate || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="result-card card-block">
        <div className="card-block-header">
          <span>
            选股结果（共 {results.length} 只）
            {candidatesCount > 0 &&
              (fromFullMarket ? ` · 全市场 ${candidatesCount} 只中得分前 ${results.length} 只` : ` · 从 ${candidatesCount} 只中选出`)}
          </span>
          {usedFilters && <span className="used-filters">已筛选：{usedFilters}</span>}
          {results.length > 0 && (
            <button type="button" className="btn-success-sm" disabled={analyzing} onClick={runAnalyze}>
              {analyzing ? '解读中...' : 'DeepSeek AI 解读'}
            </button>
          )}
        </div>
        {screenError && <div className="screen-error">{screenError}</div>}
        {aiAnalysis && (
          <div className="ai-analysis-block">
            <p className="ai-label">DeepSeek 解读与建议</p>
            <pre className="ai-content">{aiAnalysis}</pre>
          </div>
        )}
        {results.length === 0 && !loading && !screenError && (
          <div className="empty">
            {screenDoneOnce
              ? '本次未筛出符合条件的股票，可调低「最低得分」或更换板块/行业后重试'
              : '请选择条件后点击「开始选股」，或保持默认全部进行选股'}
          </div>
        )}
        {results.length > 0 && (
          <table className="result-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>代码</th>
                <th>名称</th>
                <th>市场</th>
                <th>综合得分</th>
                <th>最新价</th>
                <th>涨跌幅%</th>
                <th>MACD</th>
                <th>RSI</th>
                <th>KDJ(J)</th>
                <th>量比</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row, i) => (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td>{row.code}</td>
                  <td>{row.name}</td>
                  <td>{row.market}</td>
                  <td className={scoreClass(row.score)}>{row.score != null ? row.score.toFixed(1) : '-'}</td>
                  <td>{row.close != null ? row.close.toFixed(2) : '-'}</td>
                  <td className={pctClass(row.pct_chg)}>{row.pct_chg != null ? row.pct_chg.toFixed(2) + '%' : '-'}</td>
                  <td>
                    {row.details?.macd_hist != null
                      ? (row.details.macd_hist >= 0 ? '红柱 ' : '绿柱 ') +
                        Math.abs(row.details.macd_hist).toFixed(2)
                      : '-'}
                  </td>
                  <td>{row.details?.rsi != null ? row.details.rsi.toFixed(0) : '-'}</td>
                  <td>{row.details?.kdj_j != null ? row.details.kdj_j.toFixed(0) : '-'}</td>
                  <td>{row.details?.volume_ratio != null ? row.details.volume_ratio.toFixed(2) : '-'}</td>
                  <td className="detail-hint">{row.description || '量价/均线等已计入综合得分'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default StockAi
