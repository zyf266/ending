import { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { fetchKline, runAnalyze, type KlineData } from '../api/aiLab';
import { getSymbols } from '../api/currencyMonitor';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Textarea } from './ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import {
  Upload,
  Download,
  TrendingUp,
  Activity,
  Sparkles,
  Image as ImageIcon,
  BarChart3,
  FileText,
  Zap,
} from 'lucide-react';
import { Badge } from './ui/badge';

const INTERVAL_OPTIONS = [
  { label: '1分钟', value: '1m' },
  { label: '15分钟', value: '15m' },
  { label: '1小时', value: '1h' },
  { label: '2小时', value: '2h' },
  { label: '4小时', value: '4h' },
  { label: '日线', value: '1d' },
  { label: '周线', value: '1w' },
];

export function AiLabPage() {
  const chartRef = useRef<HTMLDivElement>(null);
  const [imagePreview, setImagePreview] = useState('');
  const [imageBase64, setImageBase64] = useState('');
  const [klineJson, setKlineJson] = useState('');
  const [userQuery, setUserQuery] = useState(
    '请根据当前的 K 线图形和原始数据，识别趋势并标注买卖点。'
  );
  const [analysisOutput, setAnalysisOutput] = useState('');
  const [suggestedBuy, setSuggestedBuy] = useState<number[]>([]);
  const [suggestedSell, setSuggestedSell] = useState<number[]>([]);
  const [fetching, setFetching] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [symbolList, setSymbolList] = useState<string[]>([]);
  const [filteredSymbols, setFilteredSymbols] = useState<string[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState('ETHUSDT');
  const [interval, setInterval] = useState('15m');

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const result = ev.target?.result as string;
      setImagePreview(result);
      setImageBase64(result);
    };
    reader.readAsDataURL(file);
  };

  const loadSymbols = async () => {
    if (symbolList.length) {
      setFilteredSymbols(symbolList);
      return;
    }
    try {
      const res = await getSymbols();
      const list = Array.isArray(res.symbols) ? res.symbols : [];
      setSymbolList(list);
      setFilteredSymbols(list);
    } catch (_) {
      alert('获取币安合约列表失败');
    }
  };

  const fetchKlineData = async () => {
    if (!selectedSymbol) {
      alert('请先选择币种');
      return;
    }
    setFetching(true);
    try {
      const res = await fetchKline({
        symbol: selectedSymbol,
        interval,
        limit: 1500,
      });
      if (res.error) {
        alert(res.error);
      } else if (res.data) {
        setKlineJson(JSON.stringify(res.data, null, 2));
        alert('抓取成功');
      }
    } catch (_) {
      alert('抓取失败');
    } finally {
      setFetching(false);
    }
  };

  const runAnalysis = async () => {
    setAnalyzing(true);
    setAnalysisOutput('');
    try {
      let kj: any = null;
      if (klineJson) {
        try {
          kj = JSON.parse(klineJson);
        } catch {
          kj = klineJson;
        }
      }
      const res = await runAnalyze({
        image_base64: imageBase64 || undefined,
        kline_json: kj,
        user_query: userQuery,
        symbol: selectedSymbol || 'ETHUSDT',
        interval: interval || '15m',
      });
      setAnalysisOutput(res.analysis || '');
      setSuggestedBuy(res.buy || []);
      setSuggestedSell(res.sell || []);
      alert('分析完成');
    } catch (e: any) {
      alert(e?.response?.data?.detail || '分析失败');
    } finally {
      setAnalyzing(false);
    }
  };

  const renderChart = () => {
    if (!chartRef.current || !klineJson) return;
    let data: KlineData[];
    try {
      data = JSON.parse(klineJson);
    } catch {
      return;
    }
    if (Array.isArray(data) && data.length === 0) return;

    const times = data.map((d) => {
      const t = d.time;
      const ms = t < 10000000000 ? t * 1000 : t;
      return new Date(ms).toLocaleString('zh-CN', { 
        month: '2-digit', 
        day: '2-digit', 
        hour: '2-digit', 
        minute: '2-digit' 
      });
    });
    
    const candlestickData = data.map((d) => [d.open, d.close, d.low, d.high]);

    const maxVisible = 200;
    const total = data.length;
    let zoomStart = 0;
    let zoomEnd = 100;
    if (total > maxVisible) {
      zoomStart = ((total - maxVisible) / total) * 100;
    }

    const markPoints: any[] = [];
    const buys = [...new Set(suggestedBuy)].map(Number).filter((p) => p > 0);
    const sells = [...new Set(suggestedSell)].map(Number).filter((p) => p > 0);
    const allPrices = [
      ...buys.map((p) => ({ p, type: '买' })),
      ...sells.map((p) => ({ p, type: '卖' })),
    ];

    for (const { p, type } of allPrices) {
      let bestIdx = 0;
      let bestDist = Infinity;
      for (let i = 0; i < data.length; i++) {
        const dist = Math.abs(Number(data[i].close) - p);
        if (dist < bestDist) {
          bestDist = dist;
          bestIdx = i;
        }
      }
      markPoints.push({
        name: type,
        coord: [bestIdx, p],
        value: p.toFixed(2),
        itemStyle: { color: type === '买' ? '#10b981' : '#ef4444' },
      });
    }

    const ch = echarts.init(chartRef.current);
    ch.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
        },
      },
      xAxis: { 
        type: 'category', 
        data: times, 
        boundaryGap: true,
        axisLine: { lineStyle: { color: '#e5e7eb' } },
        axisLabel: { color: '#6b7280' },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { type: 'dashed', color: '#f3f4f6' } },
        axisLine: { lineStyle: { color: '#e5e7eb' } },
        axisLabel: { color: '#6b7280' },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: 0, start: zoomStart, end: zoomEnd },
        { 
          type: 'slider', 
          xAxisIndex: 0, 
          start: zoomStart, 
          end: zoomEnd, 
          height: 24,
          borderColor: '#e5e7eb',
          fillerColor: 'rgba(59, 130, 246, 0.1)',
          handleStyle: { color: '#3b82f6' },
        },
      ],
      series: [
        {
          type: 'candlestick',
          data: candlestickData,
          itemStyle: {
            color: '#10b981',
            color0: '#ef4444',
            borderColor: '#10b981',
            borderColor0: '#ef4444',
            borderWidth: 1.5,
          },
          markPoint:
            markPoints.length
              ? { 
                  data: markPoints, 
                  symbol: 'pin', 
                  symbolSize: 50, 
                  label: { fontSize: 12, fontWeight: 'bold' } 
                }
              : undefined,
        },
      ],
      grid: { left: 60, right: 30, top: 30, bottom: 80 },
    });
  };

  useEffect(() => {
    if (klineJson) {
      renderChart();
    }
    
    return () => {
      if (chartRef.current) {
        const instance = echarts.getInstanceByDom(chartRef.current);
        if (instance) {
          instance.dispose();
        }
      }
    };
  }, [klineJson, suggestedBuy, suggestedSell]);

  return (
    <div className="p-6 space-y-6 bg-gray-50">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-2xl font-bold text-gray-900">AI 自适应实验室</h1>
            <Badge className="bg-purple-100 text-purple-700 border-0">
              <Sparkles className="w-3 h-3 mr-1" />
              DeepSeek V3
            </Badge>
          </div>
          <p className="text-sm text-gray-500 mt-1">基于视觉识别和数据分析的智能交易策略生成</p>
        </div>
      </div>

      {/* Input Card */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <Upload className="w-4 h-4 text-blue-600" />
            <span>输入数据</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white space-y-5">
          {/* Step 1: Upload Image */}
          <div className="space-y-3">
            <Label className="text-sm font-medium flex items-center">
              <span className="w-6 h-6 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center text-xs font-bold mr-2">
                1
              </span>
              上传 K 线截图（可选）
            </Label>
            <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 hover:border-blue-400 transition-colors">
              <label className="cursor-pointer flex flex-col items-center">
                <input
                  type="file"
                  accept="image/*"
                  onChange={onFileChange}
                  className="hidden"
                />
                <ImageIcon className="w-12 h-12 text-gray-400 mb-3" />
                <span className="text-sm text-gray-600">点击上传或拖拽图片到此处</span>
                <span className="text-xs text-gray-400 mt-1">支持 JPG, PNG 格式</span>
              </label>
            </div>
            {imagePreview && (
              <div className="rounded-lg border border-gray-200 overflow-hidden">
                <img src={imagePreview} alt="preview" className="w-full h-auto" />
              </div>
            )}
          </div>

          {/* Step 2: Select Symbol and Interval */}
          <div className="space-y-3">
            <Label className="text-sm font-medium flex items-center">
              <span className="w-6 h-6 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center text-xs font-bold mr-2">
                2
              </span>
              选择币种与 K 线周期
            </Label>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-xs text-gray-600">交易对</Label>
                <Input
                  list="symbol-list"
                  value={selectedSymbol}
                  onChange={(e) => setSelectedSymbol(e.target.value)}
                  onFocus={loadSymbols}
                  placeholder="如 ETHUSDT"
                  className="h-10"
                />
                <datalist id="symbol-list">
                  {filteredSymbols.map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-gray-600">K线周期</Label>
                <Select value={interval} onValueChange={setInterval}>
                  <SelectTrigger className="h-10">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {INTERVAL_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {/* Step 3: Fetch Kline */}
          <div className="space-y-3">
            <Label className="text-sm font-medium flex items-center">
              <span className="w-6 h-6 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center text-xs font-bold mr-2">
                3
              </span>
              原始 OHLC 数据（JSON）
            </Label>
            <Button
              onClick={fetchKlineData}
              disabled={fetching}
              variant="outline"
              className="w-full border-blue-200 text-blue-600 hover:bg-blue-50"
            >
              <Download className="w-4 h-4 mr-2" />
              {fetching ? '抓取中...' : '抓取最新行情数据'}
            </Button>
            <Textarea
              value={klineJson}
              onChange={(e) => setKlineJson(e.target.value)}
              rows={6}
              placeholder='[{"time": 123, "open": 100, "high": 101, "low": 99, "close": 100}]'
              className="font-mono text-xs bg-gray-50"
            />
          </div>

          {/* Step 4: User Query */}
          <div className="space-y-3">
            <Label className="text-sm font-medium flex items-center">
              <span className="w-6 h-6 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center text-xs font-bold mr-2">
                4
              </span>
              分析指令（驯化提示词）
            </Label>
            <Input
              value={userQuery}
              onChange={(e) => setUserQuery(e.target.value)}
              placeholder="请根据当前的 K 线图形和原始数据，识别趋势并标注买卖点。"
              className="h-10"
            />
          </div>

          {/* Analyze Button */}
          <Button
            onClick={runAnalysis}
            disabled={analyzing}
            className="w-full bg-blue-600 hover:bg-blue-700 h-12"
          >
            <Sparkles className="w-5 h-5 mr-2" />
            {analyzing ? '分析中...' : '开始 AI 综合分析'}
          </Button>
        </CardContent>
      </Card>

      {/* Chart Card */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <BarChart3 className="w-4 h-4 text-blue-600" />
            <span>K 线策略可视化</span>
            {(suggestedBuy.length > 0 || suggestedSell.length > 0) && (
              <div className="flex items-center space-x-2 ml-auto">
                {suggestedBuy.length > 0 && (
                  <Badge className="bg-green-100 text-green-700 border-0 text-xs">
                    {suggestedBuy.length} 个买点
                  </Badge>
                )}
                {suggestedSell.length > 0 && (
                  <Badge className="bg-red-100 text-red-700 border-0 text-xs">
                    {suggestedSell.length} 个卖点
                  </Badge>
                )}
              </div>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white">
          {!klineJson ? (
            <div className="w-full h-[500px] flex items-center justify-center bg-gray-50 rounded-lg border border-gray-200">
              <div className="text-center">
                <Activity className="w-16 h-16 text-gray-300 mx-auto mb-3" />
                <p className="text-sm text-gray-500">请先抓取 K 线数据</p>
              </div>
            </div>
          ) : (
            <div 
              ref={chartRef} 
              className="w-full h-[500px] bg-white rounded-lg border border-gray-100"
            />
          )}
        </CardContent>
      </Card>

      {/* Analysis Output Card */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <FileText className="w-4 h-4 text-purple-600" />
            <span>DeepSeek V3 策略分析报告</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white">
          {analysisOutput ? (
            <div className="prose prose-sm max-w-none">
              <pre className="whitespace-pre-wrap text-sm text-gray-700 leading-relaxed font-sans">
                {analysisOutput}
              </pre>
            </div>
          ) : (
            <div className="text-center py-12">
              <Zap className="w-16 h-16 text-gray-300 mx-auto mb-3" />
              <p className="text-sm text-gray-500">等待 AI 分析结果...</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}