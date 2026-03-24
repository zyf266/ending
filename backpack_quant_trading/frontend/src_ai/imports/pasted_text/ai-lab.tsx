import React, { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { fetchKline as apiFetchKline, runAnalyze as apiRunAnalyze } from '../api/aiLab'
import { getSymbols } from '../api/currencyMonitor'
import './AiLab.css'

const INTERVAL_OPTIONS = [
  { label: '1分钟', value: '1m' },
  { label: '15分钟', value: '15m' },
  { label: '1小时', value: '1h' },
  { label: '2小时', value: '2h' },
  { label: '4小时', value: '4h' },
  { label: '日线', value: '1d' },
  { label: '周线', value: '1w' },
]

const AiLab = () => {
  const chartRef = useRef(null)
  const [imagePreview, setImagePreview] = useState('')
  const [imageBase64, setImageBase64] = useState('')
  const [klineJson, setKlineJson] = useState('')
  const [userQuery, setUserQuery] = useState(
    '请根据当前的 K 线图形和原始数据，识别趋势并标注买卖点。'
  )
  const [analysisOutput, setAnalysisOutput] = useState('')
  const [suggestedBuy, setSuggestedBuy] = useState([])
  const [suggestedSell, setSuggestedSell] = useState([])
  const [fetching, setFetching] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [symbolList, setSymbolList] = useState([])
  const [filteredSymbols, setFilteredSymbols] = useState([])
  const [selectedSymbol, setSelectedSymbol] = useState('ETHUSDT')
  const [interval, setInterval] = useState('15m')
  const [symbolKeyword, setSymbolKeyword] = useState('')

  const onFileChange = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      setImagePreview(ev.target.result)
      setImageBase64(ev.target.result)
    }
    reader.readAsDataURL(file)
  }

  const loadSymbols = async () => {
    if (symbolList.length) {
      setFilteredSymbols(symbolList)
      return
    }
    try {
      const res = await getSymbols()
      const list = Array.isArray(res.symbols) ? res.symbols : []
      setSymbolList(list)
      setFilteredSymbols(list)
    } catch (_) {
      alert('获取币安合约列表失败')
    }
  }

  const handleSymbolFilter = (e) => {
    const kw = (e.target.value || '').toUpperCase()
    if (!kw) setFilteredSymbols(symbolList)
    else setFilteredSymbols(symbolList.filter((s) => s.includes(kw)))
  }

  const fetchKline = async () => {
    if (!selectedSymbol) {
      alert('请先选择币种')
      return
    }
    setFetching(true)
    try {
      const res = await apiFetchKline({
        symbol: selectedSymbol,
        interval,
        limit: 1500,
      })
      if (res.error) alert(res.error)
      else if (res.data) {
        setKlineJson(JSON.stringify(res.data, null, 2))
        alert('抓取成功')
      }
    } catch (_) {
      alert('抓取失败')
    } finally {
      setFetching(false)
    }
  }

  const runAnalyze = async () => {
    setAnalyzing(true)
    setAnalysisOutput('')
    try {
      let kj = null
      if (klineJson) {
        try {
          kj = JSON.parse(klineJson)
        } catch {
          kj = klineJson
        }
      }
      const res = await apiRunAnalyze({
        image_base64: imageBase64 || undefined,
        kline_json: kj,
        user_query: userQuery,
        symbol: selectedSymbol || 'ETHUSDT',
        interval: interval || '15m',
      })
      setAnalysisOutput(res.analysis || '')
      setSuggestedBuy(res.buy || [])
      setSuggestedSell(res.sell || [])
      alert('分析完成')
    } catch (e) {
      alert(e?.response?.data?.detail || '分析失败')
    } finally {
      setAnalyzing(false)
    }
  }

  const renderChart = () => {
    if (!chartRef.current || !klineJson) return
    let data
    try {
      data = JSON.parse(klineJson)
    } catch {
      return
    }
    if (Array.isArray(data) && data.length === 0) return
    if (data?.data) data = data.data
    const times = data.map((d) => {
      const t = d.time
      const ms = t < 10000000000 ? t * 1000 : t
      return new Date(ms).toLocaleString()
    })
    const o = data.map((d) => d.open)
    const c = data.map((d) => d.close)
    const l = data.map((d) => d.low)
    const h = data.map((d) => d.high)
    const candlestickData = data.map((d, i) => [o[i], c[i], l[i], h[i]])
    const maxVisible = 200
    const total = data.length
    let zoomStart = 0
    let zoomEnd = 100
    if (total > maxVisible) {
      zoomStart = ((total - maxVisible) / total) * 100
    }
    const markPoints = []
    const buys = [...new Set(suggestedBuy)].map(Number).filter((p) => p > 0)
    const sells = [...new Set(suggestedSell)].map(Number).filter((p) => p > 0)
    const allPrices = [
      ...buys.map((p) => ({ p, type: '买' })),
      ...sells.map((p) => ({ p, type: '卖' })),
    ]
    for (const { p, type } of allPrices) {
      let bestIdx = 0
      let bestDist = Infinity
      for (let i = 0; i < data.length; i++) {
        const dist = Math.abs(Number(data[i].close) - p)
        if (dist < bestDist) {
          bestDist = dist
          bestIdx = i
        }
      }
      markPoints.push({
        name: type,
        coord: [bestIdx, p],
        value: p.toFixed(2),
        itemStyle: { color: type === '买' ? '#10b981' : '#ef4444' },
      })
    }
    const ch = echarts.init(chartRef.current)
    ch.setOption({
      xAxis: { type: 'category', data: times, boundaryGap: true },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { type: 'dashed', opacity: 0.3 } },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: 0, start: zoomStart, end: zoomEnd },
        { type: 'slider', xAxisIndex: 0, start: zoomStart, end: zoomEnd, height: 24 },
      ],
      series: [
        {
          type: 'candlestick',
          data: candlestickData,
          itemStyle: {
            color: '#ef4444',
            color0: '#10b981',
            borderColor: '#ef4444',
            borderColor0: '#10b981',
            borderWidth: 1.5,
          },
          markPoint:
            markPoints.length
              ? { data: markPoints, symbol: 'pin', symbolSize: 40, label: { fontSize: 12 } }
              : undefined,
        },
      ],
      grid: { left: 60, right: 30, top: 30, bottom: 90 },
    })
  }

  useEffect(() => {
    renderChart()
  }, [klineJson, suggestedBuy, suggestedSell])

  return (
    <div className="page ai-lab-page">
      <div className="title-row">
        <h2>AI 自适应实验室</h2>
      </div>

      <div className="input-card card-block">
        <h4>输入数据</h4>
        <div className="form-item">
          <span className="label">1. 上传 K 线截图</span>
          <label className="upload-area">
            <input type="file" accept="image/*" onChange={onFileChange} className="upload-input" />
            <div className="upload-inner">拖拽或 选择图片</div>
          </label>
          {imagePreview && (
            <div className="preview">
              <img src={imagePreview} alt="preview" />
            </div>
          )}
        </div>
        <div className="form-item">
          <span className="label">2. 选择币种与K线周期</span>
          <div className="symbol-interval-row">
            <input
              list="symbol-list"
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              onFocus={loadSymbols}
              placeholder="选择币安合约交易对，如 ETHUSDT"
              className="symbol-input"
            />
            <datalist id="symbol-list">
              {filteredSymbols.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
            <select
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
              className="interval-select"
            >
              {INTERVAL_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="form-item">
          <span className="label">3. 原始 OHLC 数据 (JSON)</span>
          <button
            type="button"
            className="fetch-btn"
            onClick={fetchKline}
            disabled={fetching}
          >
            {fetching ? '抓取中...' : '抓取最新行情'}
          </button>
          <textarea
            value={klineJson}
            onChange={(e) => setKlineJson(e.target.value)}
            rows={6}
            placeholder='[{"time": 123, "open": 100, "high": 101, "low": 99, "close": 100}]'
            className="kline-textarea"
          />
        </div>
        <div className="form-item">
          <span className="label">4. 分析指令 (驯化提示词)</span>
          <input
            value={userQuery}
            onChange={(e) => setUserQuery(e.target.value)}
            placeholder="请根据当前的 K 线图形和原始数据，识别趋势并标注买卖点。"
            className="query-input"
          />
        </div>
        <div className="form-item">
          <button
            type="button"
            className="analyze-btn"
            onClick={runAnalyze}
            disabled={analyzing}
          >
            {analyzing ? '分析中...' : '开始 AI 综合分析'}
          </button>
        </div>
      </div>

      <div className="chart-card card-block">
        <h4>K 线策略可视化</h4>
        <div ref={chartRef} className="chart-container" />
      </div>

      <div className="output-card card-block">
        <h4>DeepSeek V3 策略分析报告</h4>
        <div className="output-content">{analysisOutput || '等待分析...'}</div>
      </div>
    </div>
  )
}

export default AiLab
