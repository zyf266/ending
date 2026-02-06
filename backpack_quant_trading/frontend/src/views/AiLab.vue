<template>
  <div class="page ai-lab-page">
    <div class="title-row">
      <h2>AI 自适应实验室</h2>
    </div>

    <el-card class="input-card">
      <h4>输入数据</h4>
      <el-form label-width="0">
        <el-form-item>
          <span class="label">1. 上传 K 线截图</span>
          <el-upload
            class="upload-area"
            :auto-upload="false"
            :show-file-list="false"
            :on-change="onFileChange"
          >
            <div class="upload-inner">拖拽或 选择图片</div>
          </el-upload>
          <div v-if="imagePreview" class="preview">
            <img :src="imagePreview" alt="preview" />
          </div>
        </el-form-item>
        <el-form-item>
          <span class="label">2. 原始 OHLC 数据 (JSON)</span>
          <el-button type="warning" @click="fetchKline" :loading="fetching" class="fetch-btn">
            抓取最新行情 (ETH 15m 币安 · 1500根)
          </el-button>
          <el-input v-model="klineJson" type="textarea" :rows="6" placeholder='[{"time": 123, "open": 100, "high": 101, "low": 99, "close": 100}]' class="kline-textarea" />
        </el-form-item>
        <el-form-item>
          <span class="label">3. 分析指令 (驯化提示词)</span>
          <el-input v-model="userQuery" placeholder="请根据当前的 K 线图形和原始数据，识别趋势并标注买卖点。" class="query-input" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="runAnalyze" :loading="analyzing" class="analyze-btn">
            开始 AI 综合分析
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="chart-card">
      <h4>K 线策略可视化</h4>
      <div ref="chartRef" class="chart-container"></div>
    </el-card>

    <el-card class="output-card">
      <h4>DeepSeek V3 策略分析报告</h4>
      <div class="output-content">{{ analysisOutput || '等待分析...' }}</div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { fetchKline as apiFetchKline, runAnalyze as apiRunAnalyze } from '../api/aiLab'

const chartRef = ref(null)
const imagePreview = ref('')
const imageBase64 = ref('')
const klineJson = ref('')
const userQuery = ref('请根据当前的 K 线图形和原始数据，识别趋势并标注买卖点。')
const analysisOutput = ref('')
const suggestedBuy = ref([])
const suggestedSell = ref([])
const fetching = ref(false)
const analyzing = ref(false)

function onFileChange(file) {
  const reader = new FileReader()
  reader.onload = (e) => {
    imagePreview.value = e.target.result
    imageBase64.value = e.target.result
  }
  reader.readAsDataURL(file.raw)
}

async function fetchKline() {
  fetching.value = true
  try {
    const res = await apiFetchKline()
    if (res.error) {
      ElMessage.error(res.error)
    } else if (res.data) {
      klineJson.value = JSON.stringify(res.data, null, 2)
      ElMessage.success('抓取成功')
    }
  } catch (e) {
    ElMessage.error('抓取失败')
  } finally {
    fetching.value = false
  }
}

async function runAnalyze() {
  analyzing.value = true
  analysisOutput.value = ''
  try {
    let kj = null
    if (klineJson.value) {
      try {
        kj = JSON.parse(klineJson.value)
      } catch {
        kj = klineJson.value
      }
    }
    const res = await apiRunAnalyze({
      image_base64: imageBase64.value || undefined,
      kline_json: kj,
      user_query: userQuery.value,
    })
    analysisOutput.value = res.analysis || ''
    suggestedBuy.value = res.buy || []
    suggestedSell.value = res.sell || []
    ElMessage.success('分析完成')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '分析失败')
  } finally {
    analyzing.value = false
  }
}

function renderChart() {
  if (!chartRef.value || !klineJson.value) return
  let data
  try {
    data = JSON.parse(klineJson.value)
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
  const h = data.map((d) => d.high)
  const l = data.map((d) => d.low)
  const c = data.map((d) => d.close)

  const ch = echarts.init(chartRef.value)
  const option = {
    xAxis: { type: 'category', data: times },
    yAxis: { type: 'value' },
    series: [
      {
        type: 'candlestick',
        data: data.map((d, i) => [o[i], c[i], l[i], h[i]]),
        itemStyle: { color: '#ef4444', color0: '#10b981', borderColor: '#ef4444', borderColor0: '#10b981' },
      },
    ],
    grid: { left: 50, right: 20, top: 20, bottom: 60 },
  }
  ch.setOption(option)
}

watch(klineJson, () => renderChart(), { immediate: true })
</script>

<style scoped>
.title-row {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 24px; padding-left: 16px; border-left: 4px solid var(--color-primary);
}
.title-row h2 { margin: 0; font-size: 22px; font-weight: 700; color: var(--color-text); }
.input-card {
  max-width: none;
  margin: 0 0 24px 0;
  padding: 24px 28px;
  background: var(--color-bg-card);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}
.input-card h4 { color: var(--color-primary); margin-bottom: 20px; text-align: center; font-weight: 600; font-size: 16px; }
.input-card .el-form-item { margin-bottom: 20px; }
.label { display: block; margin-bottom: 8px; font-weight: 600; font-size: 14px; color: var(--color-text); }
.upload-area { width: 100%; }
.upload-inner {
  width: 100%;
  height: 80px;
  line-height: 80px;
  font-size: 14px;
  color: var(--color-text-muted);
  border: 2px dashed var(--color-border);
  border-radius: 10px;
  text-align: center;
  background: #fafbfc;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s, color 0.2s;
}
.upload-inner:hover { border-color: var(--color-primary); background: rgba(245, 158, 11, 0.04); color: var(--color-text); }
.fetch-btn { width: 100%; height: 40px; font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.kline-textarea :deep(.el-textarea__inner) {
  min-height: 120px !important;
  font-size: 13px;
  padding: 12px 14px;
  font-family: var(--font-mono);
  background: #1e293b;
  color: #e2e8f0;
  border: 1px solid #334155;
  border-radius: 10px;
  resize: vertical;
}
.kline-textarea :deep(.el-textarea__inner::placeholder) { color: #94a3b8; }
.kline-textarea :deep(.el-textarea__inner:focus) {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.2);
}
.query-input :deep(.el-input__wrapper) { min-height: 40px; padding: 10px 14px; }
.analyze-btn { width: 100%; height: 44px; font-size: 15px; font-weight: 600; }
.preview { margin-top: 12px; text-align: center; }
.preview img { max-width: 100%; max-height: 200px; border-radius: var(--radius-md); }
.chart-card { margin-bottom: 24px; padding: 24px; }
.chart-card h4 { color: var(--color-primary); margin-bottom: 20px; text-align: center; font-weight: 600; font-size: 16px; }
.chart-container { height: 360px; }
.output-card { padding: 24px; }
.output-card h4 { color: var(--color-primary); margin-bottom: 20px; text-align: center; font-weight: 600; font-size: 16px; }
.output-content {
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 2;
  max-height: 320px;
  overflow-y: auto;
  padding: 20px;
  background: #f8fafc;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-family: var(--font-mono);
}
</style>
