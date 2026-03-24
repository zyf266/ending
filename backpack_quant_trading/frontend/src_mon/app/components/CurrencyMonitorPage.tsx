import { useEffect, useState } from 'react';
import {
  getSymbols,
  getStatus,
  startMonitor,
  stopMonitor,
  removePair as apiRemovePair,
  getMinuteAlertStatus,
  startMinuteAlert,
  stopMinuteAlert,
} from '../api/currencyMonitor';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Checkbox } from './ui/checkbox';
import { MultiSelect } from './ui/multi-select';
import {
  Eye,
  Bell,
  Play,
  Square,
  X,
  TrendingUp,
  Activity,
  Zap,
  AlertCircle,
  Clock,
  BarChart3,
  Target,
  Radio,
} from 'lucide-react';

const TIMEFRAME_OPTIONS = [
  { label: '1小时', value: '1小时' },
  { label: '2小时', value: '2小时' },
  { label: '4小时', value: '4小时' },
  { label: '天', value: '天' },
  { label: '周', value: '周' },
];

const MINUTE_INTERVALS = ['1m', '3m', '5m', '15m'];

export function CurrencyMonitorPage() {
  const [symbolList, setSymbolList] = useState<string[]>([]);
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([]);
  const [selectedTimeframes, setSelectedTimeframes] = useState<string[]>([]);
  const [status, setStatus] = useState({ running: false, pairs: [] as [string, string][] });
  const [loading, setLoading] = useState(false);
  const [alertedPairs, setAlertedPairs] = useState(new Set<string>());
  const [symbolFilter, setSymbolFilter] = useState('');

  const [minuteLoading, setMinuteLoading] = useState(false);
  const [minuteStatus, setMinuteStatus] = useState({
    running: false,
    symbols: [] as string[],
    interval: '1m',
    vol_pct_threshold: 5.0,
    volume_mult_threshold: 20.0,
    ob_notional_threshold: 200000,
  });
  const [minuteForm, setMinuteForm] = useState({
    symbols: [] as string[],
    interval: '1m',
    vol_pct_threshold: 5.0,
    volume_mult_threshold: 20.0,
    ob_notional_threshold: 200000,
  });
  const [minuteSymbolFilter, setMinuteSymbolFilter] = useState('');

  const minutePairsForPool = minuteStatus.running
    ? (minuteStatus.symbols || []).map((s): [string, string] => [
        String(s).toUpperCase(),
        `预警(${minuteStatus.interval || '1m'})`,
      ])
    : [];
  const displayPairs = [...(status.pairs || []), ...minutePairsForPool];
  const hasAnyAlerted = displayPairs.some((p) => alertedPairs.has(`${p[0]}|${p[1]}`));

  const isAlerted = (p: [string, string]) => alertedPairs.has(`${p[0]}|${p[1]}`);

  const filteredSymbolList = symbolList.filter((s) =>
    s.toLowerCase().includes(symbolFilter.toLowerCase())
  );

  const filteredMinuteSymbolList = symbolList.filter((s) =>
    s.toLowerCase().includes(minuteSymbolFilter.toLowerCase())
  );

  const refreshStatus = async () => {
    try {
      const res = await getStatus();
      setStatus({ running: res.running, pairs: res.pairs || [] });
      setAlertedPairs(new Set(res.alerted || []));
    } catch (_) {}
  };

  const refreshMinuteStatus = async () => {
    try {
      const res = await getMinuteAlertStatus();
      setMinuteStatus({
        running: !!res.running,
        symbols: res.symbols || [],
        interval: res.interval || '1m',
        vol_pct_threshold: Number(res.vol_pct_threshold ?? 5),
        volume_mult_threshold: Number(res.volume_mult_threshold ?? 20),
        ob_notional_threshold: Number(res.ob_notional_threshold ?? 200000),
      });
      if (!res.running) {
        setMinuteForm((prev) => ({
          ...prev,
          interval: res.interval || '1m',
          vol_pct_threshold: Number(res.vol_pct_threshold ?? 5),
          volume_mult_threshold: Number(res.volume_mult_threshold ?? 20),
          ob_notional_threshold: Number(res.ob_notional_threshold ?? 200000),
        }));
      }
    } catch (_) {}
  };

  useEffect(() => {
    let t1: NodeJS.Timeout, t2: NodeJS.Timeout;
    const load = async () => {
      try {
        const res = await getSymbols();
        setSymbolList(res.symbols || []);
      } catch (_) {}
      await refreshStatus();
      await refreshMinuteStatus();
      t1 = setInterval(refreshStatus, 5000);
      t2 = setInterval(refreshMinuteStatus, 5000);
    };
    load();
    return () => {
      if (t1) clearInterval(t1);
      if (t2) clearInterval(t2);
    };
  }, []);

  const handleStart = async () => {
    if (!selectedSymbols.length || !selectedTimeframes.length) {
      alert('请选择币种和 K 线级别');
      return;
    }
    setLoading(true);
    try {
      await startMonitor({ symbols: selectedSymbols, timeframes: selectedTimeframes });
      alert('已开始监视');
      setSelectedSymbols([]);
      setSelectedTimeframes([]);
      await refreshStatus();
    } catch (e: any) {
      alert(e?.response?.data?.detail || '启动失败');
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    try {
      await stopMonitor();
      alert('已停止全部监视');
      await refreshStatus();
    } catch (e: any) {
      alert(e?.response?.data?.detail || '停止失败');
    }
  };

  const removePair = async (symbol: string, timeframe: string) => {
    if (String(timeframe || '').startsWith('预警(')) {
      await handleMinuteStop();
      return;
    }
    try {
      await apiRemovePair({ symbol, timeframe });
      await refreshStatus();
    } catch (e: any) {
      alert(e?.response?.data?.detail || '移除失败');
    }
  };

  const handleMinuteStart = async () => {
    if (!minuteForm.symbols.length) {
      alert('请选择预警监控币种');
      return;
    }
    setMinuteLoading(true);
    try {
      await startMinuteAlert({
        symbols: minuteForm.symbols,
        interval: minuteForm.interval,
        vol_pct_threshold: minuteForm.vol_pct_threshold,
        volume_mult_threshold: minuteForm.volume_mult_threshold,
        ob_notional_threshold: minuteForm.ob_notional_threshold,
      });
      alert('已启动分钟预警');
      setMinuteForm((prev) => ({ ...prev, symbols: [] }));
      await refreshMinuteStatus();
    } catch (e: any) {
      alert(e?.response?.data?.detail || '启动失败');
    } finally {
      setMinuteLoading(false);
    }
  };

  const handleMinuteStop = async () => {
    try {
      await stopMinuteAlert();
      alert('已停止预警');
      await refreshMinuteStatus();
    } catch (e: any) {
      alert(e?.response?.data?.detail || '停止失败');
    }
  };

  const toggleSymbol = (s: string) => {
    setSelectedSymbols((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  };

  const toggleTimeframe = (v: string) => {
    setSelectedTimeframes((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]));
  };

  const toggleMinuteSymbol = (s: string) => {
    setMinuteForm((prev) => ({
      ...prev,
      symbols: prev.symbols.includes(s) ? prev.symbols.filter((x) => x !== s) : [...prev.symbols, s],
    }));
  };

  return (
    <div className="p-6 space-y-6 bg-gray-50">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-2xl font-bold text-gray-900">币种监控</h1>
            <Badge className="bg-green-100 text-green-700 border-0">
              <Eye className="w-3 h-3 mr-1" />
              实时监控
            </Badge>
            {status.running && (
              <Badge className="bg-blue-100 text-blue-700 border-0">
                <Radio className="w-3 h-3 mr-1 animate-pulse" />
                {status.pairs.length} 个监控项
              </Badge>
            )}
          </div>
          <p className="text-sm text-gray-500 mt-1">多维度市场监控 · 异动实时预警</p>
        </div>
      </div>

      {/* Monitor Configuration */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <Eye className="w-4 h-4 text-blue-600" />
            <span>监视配置</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white space-y-5">
          <div className="grid grid-cols-2 gap-6">
            {/* Symbol Selection */}
            <div className="space-y-3">
              <Label className="text-sm font-medium">选择币种</Label>
              <MultiSelect
                options={symbolList}
                selected={selectedSymbols}
                onChange={setSelectedSymbols}
                placeholder="选择币种..."
                searchPlaceholder="搜索币种..."
                emptyText="未找到币种"
              />
              {selectedSymbols.length > 0 && (
                <p className="text-xs text-blue-600">已选择 {selectedSymbols.length} 个币种</p>
              )}
            </div>

            {/* Timeframe Selection */}
            <div className="space-y-3">
              <Label className="text-sm font-medium">K线级别（可多选）</Label>
              <div className="space-y-3 pt-2">
                {TIMEFRAME_OPTIONS.map((opt) => (
                  <div key={opt.value} className="flex items-center space-x-2">
                    <Checkbox
                      id={`timeframe-${opt.value}`}
                      checked={selectedTimeframes.includes(opt.value)}
                      onCheckedChange={() => toggleTimeframe(opt.value)}
                    />
                    <label
                      htmlFor={`timeframe-${opt.value}`}
                      className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer"
                    >
                      {opt.label}
                    </label>
                  </div>
                ))}
              </div>
              {selectedTimeframes.length > 0 && (
                <p className="text-xs text-blue-600 mt-3">已选择 {selectedTimeframes.length} 个级别</p>
              )}
            </div>
          </div>

          <div className="flex items-center space-x-3 pt-2">
            <Button onClick={handleStart} disabled={loading} className="bg-blue-600 hover:bg-blue-700">
              <Play className="w-4 h-4 mr-2" />
              {loading ? '启动中...' : '开始监视'}
            </Button>
            <Button
              variant="outline"
              onClick={handleStop}
              disabled={!status.running}
              className="border-red-200 text-red-600 hover:bg-red-50"
            >
              <Square className="w-4 h-4 mr-2" />
              停止监视
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Minute Alert Configuration */}
      <Card className="border border-orange-200 shadow-sm bg-gradient-to-br from-orange-50 to-white">
        <CardHeader className="border-b border-orange-100">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <Bell className="w-4 h-4 text-orange-600" />
            <span>分钟预警配置</span>
            {minuteStatus.running && (
              <Badge className="bg-orange-600 text-white border-0 text-xs ml-2">
                <Zap className="w-3 h-3 mr-1" />
                运行中
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white space-y-5">
          <div className="grid grid-cols-2 gap-6">
            {/* Minute Symbol Selection */}
            <div className="space-y-3">
              <Label className="text-sm font-medium">监控币种</Label>
              <MultiSelect
                options={symbolList}
                selected={minuteForm.symbols}
                onChange={(symbols) => setMinuteForm((prev) => ({ ...prev, symbols }))}
                placeholder="选择币种..."
                searchPlaceholder="搜索币种..."
                emptyText="未找���币种"
              />
              {minuteForm.symbols.length > 0 && (
                <p className="text-xs text-orange-600">已选择 {minuteForm.symbols.length} 个币种</p>
              )}
            </div>

            {/* Threshold Parameters */}
            <div className="space-y-4">
              <div className="space-y-2">
                <Label className="text-xs text-gray-600">K线级别</Label>
                <select
                  value={minuteForm.interval}
                  onChange={(e) => setMinuteForm((prev) => ({ ...prev, interval: e.target.value }))}
                  className="w-full h-10 px-3 rounded-md border border-gray-200 text-sm"
                >
                  {MINUTE_INTERVALS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">波动阈值 (%)</Label>
                <Input
                  type="number"
                  min={0}
                  step={0.5}
                  value={minuteForm.vol_pct_threshold}
                  onChange={(e) =>
                    setMinuteForm((prev) => ({ ...prev, vol_pct_threshold: Number(e.target.value) }))
                  }
                  className="h-10"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">量能倍数 (x)</Label>
                <Input
                  type="number"
                  min={1}
                  step={1}
                  value={minuteForm.volume_mult_threshold}
                  onChange={(e) =>
                    setMinuteForm((prev) => ({ ...prev, volume_mult_threshold: Number(e.target.value) }))
                  }
                  className="h-10"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">订单簿大单 (USDT)</Label>
                <Input
                  type="number"
                  min={0}
                  step={10000}
                  value={minuteForm.ob_notional_threshold}
                  onChange={(e) =>
                    setMinuteForm((prev) => ({ ...prev, ob_notional_threshold: Number(e.target.value) }))
                  }
                  className="h-10"
                />
              </div>
            </div>
          </div>

          {minuteStatus.running && (
            <div className="p-4 bg-orange-50 border border-orange-200 rounded-lg">
              <div className="flex items-start space-x-2">
                <AlertCircle className="w-4 h-4 text-orange-600 mt-0.5" />
                <div className="text-sm text-orange-800">
                  <p className="font-semibold mb-1">当前运行参数</p>
                  <p>
                    币种: {minuteStatus.symbols.join(', ')} | 级别: {minuteStatus.interval} | 波动≥
                    {minuteStatus.vol_pct_threshold}% | 量能≥{minuteStatus.volume_mult_threshold}x | 订单簿≥
                    {minuteStatus.ob_notional_threshold}
                  </p>
                </div>
              </div>
            </div>
          )}

          <div className="flex items-center space-x-3">
            <Button
              onClick={handleMinuteStart}
              disabled={minuteLoading}
              className="bg-orange-600 hover:bg-orange-700"
            >
              <Bell className="w-4 h-4 mr-2" />
              {minuteLoading ? '启动中...' : '启动预警'}
            </Button>
            <Button
              variant="outline"
              onClick={handleMinuteStop}
              disabled={!minuteStatus.running}
              className="border-red-200 text-red-600 hover:bg-red-50"
            >
              <Square className="w-4 h-4 mr-2" />
              停止预警
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Monitored Pairs */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <Activity className="w-4 h-4 text-blue-600" />
            <span>监视/预警中的币种</span>
            <Badge className="bg-blue-600 text-white border-0 text-xs">{displayPairs.length}</Badge>
            {hasAnyAlerted && (
              <Badge className="bg-red-600 text-white border-0 text-xs animate-pulse">
                <AlertCircle className="w-3 h-3 mr-1" />
                异动提醒
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white">
          {displayPairs.length > 0 && (
            <p className="text-sm text-gray-600 mb-4">
              已有监视/预警时，选择更多币种/级别后点击「开始监视」可追加；点击 × 可移除该项
            </p>
          )}
          {displayPairs.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-blue-50 rounded-xl flex items-center justify-center mx-auto mb-4">
                <Eye className="w-8 h-8 text-blue-400" />
              </div>
              <h3 className="text-base font-semibold text-gray-900 mb-2">暂无监视/预警</h3>
              <p className="text-sm text-gray-500">请先启动「币种监视」或「分钟预警」</p>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {displayPairs.map((p) => (
                <div
                  key={`${p[0]}-${p[1]}`}
                  className={`inline-flex items-center space-x-2 px-4 py-2 rounded-lg border-2 transition-all ${
                    isAlerted(p)
                      ? 'bg-red-100 border-red-400 text-red-900 animate-pulse'
                      : 'bg-white border-gray-200 hover:border-blue-400'
                  }`}
                >
                  {isAlerted(p) && <AlertCircle className="w-4 h-4 text-red-600" />}
                  <span className="font-semibold text-sm">{p[0]}</span>
                  <Badge variant="outline" className="text-xs">
                    {p[1]}
                  </Badge>
                  <button
                    onClick={() => removePair(p[0], p[1])}
                    className="ml-2 p-1 hover:bg-gray-200 rounded-full transition-colors"
                    aria-label="移除"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}