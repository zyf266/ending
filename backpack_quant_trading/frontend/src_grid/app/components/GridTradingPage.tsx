import { useEffect, useState } from 'react';
import {
  getGridStatus,
  startGrid as apiStartGrid,
  stopGrid,
  stopAllGrids,
  type GridInstance,
} from '../api/grid';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import {
  Grid3x3,
  TrendingUp,
  TrendingDown,
  ArrowUpDown,
  Zap,
  DollarSign,
  Activity,
  Target,
  AlertTriangle,
  Play,
  Square,
  BarChart3,
  Clock,
  Percent,
  Layers,
} from 'lucide-react';

const EXCHANGES = [
  { label: 'Backpack', value: 'backpack' },
  { label: 'Deepcoin', value: 'deepcoin' },
  { label: 'Hyperliquid', value: 'hyper' },
  { label: 'Hyperliquid3', value: 'hip3_testnet' },
  { label: 'Ostium', value: 'ostium' },
];

const MODES = [
  { label: '做空网格', value: 'short_only', icon: TrendingDown, color: 'red' },
  { label: '做多网格', value: 'long_only', icon: TrendingUp, color: 'green' },
  { label: '双向网格', value: 'long_short', icon: ArrowUpDown, color: 'blue' },
];

const modeLabel = (m: string) => {
  const map: Record<string, string> = { long_short: '双向', long_only: '做多', short_only: '做空' };
  return map[m] || m;
};

const modeColor = (m: string) => {
  const map: Record<string, string> = {
    long_short: 'bg-blue-100 text-blue-700',
    long_only: 'bg-green-100 text-green-700',
    short_only: 'bg-red-100 text-red-700',
  };
  return map[m] || 'bg-gray-100 text-gray-700';
};

export function GridTradingPage() {
  const [grids, setGrids] = useState<GridInstance[]>([]);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [form, setForm] = useState({
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
  });

  const previewValid =
    form.price_lower != null &&
    form.price_upper != null &&
    form.price_lower < form.price_upper &&
    form.grid_count >= 2 &&
    form.investment_per_grid > 0 &&
    form.leverage >= 1;

  const gridPreview = previewValid
    ? (() => {
        const { price_lower, price_upper, grid_count, investment_per_grid, leverage } = form;
        const priceRange = price_upper - price_lower;
        const gridSpacing = priceRange / grid_count;
        const gridSpacingPercent = (gridSpacing / price_lower) * 100;
        const totalInvestment = investment_per_grid * grid_count;
        const positionValue = totalInvestment * leverage;
        const profitPerGrid = (investment_per_grid * leverage * gridSpacingPercent) / 100;
        const profitRatePercent = gridSpacingPercent * leverage - 0.1 * leverage;
        const avgPrice = (price_lower + price_upper) / 2;
        const liqPrice = leverage > 1 ? avgPrice * (1 - 1 / leverage + 0.005) : 0;
        return {
          gridSpacing,
          gridSpacingPercent,
          totalInvestment,
          positionValue,
          profitPerGrid,
          profitRatePercent,
          liqPrice,
        };
      })()
    : null;

  const refreshStatus = async () => {
    try {
      const res = await getGridStatus();
      setGrids(res.grids || []);
    } catch (_) {}
  };

  useEffect(() => {
    refreshStatus();
    const t = setInterval(refreshStatus, 3000);
    return () => clearInterval(t);
  }, []);

  const setField = (name: string, value: string | number) =>
    setForm((prev) => ({ ...prev, [name]: value }));

  const startGridTrading = async () => {
    if (!form.symbol || !form.api_key || !form.secret_key) {
      alert('请填写交易对、API Key 和 Secret Key');
      return;
    }
    setStarting(true);
    try {
      const res = await apiStartGrid({
        ...form,
        api_key: form.api_key,
        secret_key: form.secret_key,
      });
      if (res.ok) {
        alert('网格已启动');
        await refreshStatus();
      } else {
        alert(res.message || '启动失败');
      }
    } catch (e: any) {
      alert(e?.response?.data?.detail || '启动失败');
    } finally {
      setStarting(false);
    }
  };

  const stopOne = async (id: string) => {
    try {
      await stopGrid(id);
      alert('已停止');
      await refreshStatus();
    } catch (e: any) {
      alert(e?.response?.data?.detail || '停止失败');
    }
  };

  const stopAll = async () => {
    setStopping(true);
    try {
      await stopAllGrids();
      alert('已停止全部');
      await refreshStatus();
    } catch (e: any) {
      alert(e?.response?.data?.detail || '停止失败');
    } finally {
      setStopping(false);
    }
  };

  return (
    <div className="p-6 space-y-6 bg-gray-50">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-2xl font-bold text-gray-900">合约网格交易</h1>
            <Badge className="bg-blue-100 text-blue-700 border-0">
              <Grid3x3 className="w-3 h-3 mr-1" />
              智能套利
            </Badge>
          </div>
          <p className="text-sm text-gray-500 mt-1">自动化网格策略 · 捕捉价格波动收益</p>
        </div>
        {grids.length > 0 && (
          <Button variant="outline" onClick={stopAll} disabled={stopping} className="border-red-200 text-red-600 hover:bg-red-50">
            <Square className="w-4 h-4 mr-2" />
            {stopping ? '停止中...' : '停止全部网格'}
          </Button>
        )}
      </div>

      {/* Configuration Card */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <Zap className="w-4 h-4 text-blue-600" />
            <span>网格配置</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white space-y-6">
          {/* Basic Parameters */}
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center">
              <Target className="w-4 h-4 mr-2 text-blue-600" />
              交易参数
            </h3>
            <div className="grid grid-cols-4 gap-4">
              <div className="space-y-2">
                <Label className="text-xs text-gray-600">交易所</Label>
                <Select value={form.exchange} onValueChange={(value) => setField('exchange', value)}>
                  <SelectTrigger className="h-10">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {EXCHANGES.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">交易对</Label>
                <Input
                  value={form.symbol}
                  onChange={(e) => setField('symbol', e.target.value)}
                  placeholder="ETH / BTC / SOL"
                  className="h-10"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">价格下限 (USDT)</Label>
                <Input
                  type="number"
                  min={0}
                  step={0.01}
                  value={form.price_lower}
                  onChange={(e) => setField('price_lower', Number(e.target.value))}
                  className="h-10"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">价格上限 (USDT)</Label>
                <Input
                  type="number"
                  min={0}
                  step={0.01}
                  value={form.price_upper}
                  onChange={(e) => setField('price_upper', Number(e.target.value))}
                  className="h-10"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">网格数量</Label>
                <Input
                  type="number"
                  min={2}
                  max={100}
                  value={form.grid_count}
                  onChange={(e) => setField('grid_count', Number(e.target.value))}
                  className="h-10"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">单格投资 (USDT)</Label>
                <Input
                  type="number"
                  min={0}
                  step={0.01}
                  value={form.investment_per_grid}
                  onChange={(e) => setField('investment_per_grid', Number(e.target.value))}
                  className="h-10"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">杠杆倍数</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={form.leverage}
                  onChange={(e) => setField('leverage', Number(e.target.value))}
                  className="h-10"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-xs text-gray-600">网格类型</Label>
                <Select value={form.grid_mode} onValueChange={(value) => setField('grid_mode', value)}>
                  <SelectTrigger className="h-10">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MODES.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {/* API Credentials */}
          <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
            <div className="flex items-start space-x-2 mb-3">
              <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5" />
              <div className="flex-1">
                <h4 className="text-sm font-semibold text-amber-900">API 密钥配置</h4>
                <p className="text-xs text-amber-700 mt-0.5">请确保 API 密钥具有合约交易权限</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label className="text-xs text-gray-700">API Key</Label>
                <Input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setField('api_key', e.target.value)}
                  placeholder="输入 API Key"
                  className="h-10 bg-white"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-gray-700">Secret Key</Label>
                <Input
                  type="password"
                  value={form.secret_key}
                  onChange={(e) => setField('secret_key', e.target.value)}
                  placeholder="输入 Secret Key"
                  className="h-10 bg-white"
                />
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center space-x-3">
            <Button
              onClick={startGridTrading}
              disabled={starting}
              className="flex-1 bg-blue-600 hover:bg-blue-700 h-11"
            >
              <Play className="w-4 h-4 mr-2" />
              {starting ? '启动中...' : '启动当前类型网格'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Grid Preview */}
      {previewValid && gridPreview && (
        <Card className="border border-blue-200 shadow-sm bg-gradient-to-br from-blue-50 to-white">
          <CardHeader className="border-b border-blue-100">
            <CardTitle className="flex items-center space-x-2 text-base font-semibold">
              <BarChart3 className="w-4 h-4 text-blue-600" />
              <span>参数预览</span>
              <Badge variant="outline" className="ml-2 text-xs border-blue-300 text-blue-700">
                实时计算
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-6">
            <div className="grid grid-cols-3 gap-4">
              <PreviewCard
                icon={<Layers className="w-5 h-5 text-blue-600" />}
                label="网格间距"
                value={`$${gridPreview.gridSpacing.toFixed(2)}`}
                subtitle={`${gridPreview.gridSpacingPercent.toFixed(2)}%`}
                color="blue"
              />
              <PreviewCard
                icon={<DollarSign className="w-5 h-5 text-green-600" />}
                label="总投资"
                value={`$${gridPreview.totalInvestment.toFixed(2)}`}
                subtitle="保证金"
                color="green"
              />
              <PreviewCard
                icon={<TrendingUp className="w-5 h-5 text-purple-600" />}
                label="实际持仓价值"
                value={`$${gridPreview.positionValue.toFixed(2)}`}
                subtitle={`${form.leverage}x 杠杆`}
                color="purple"
              />
              <PreviewCard
                icon={<Percent className="w-5 h-5 text-emerald-600" />}
                label="单网格收益率"
                value={`${gridPreview.profitRatePercent.toFixed(2)}%`}
                subtitle={`$${gridPreview.profitPerGrid.toFixed(2)}`}
                color="emerald"
              />
              <PreviewCard
                icon={<Target className="w-5 h-5 text-indigo-600" />}
                label="建议网格数"
                value={`${form.grid_count} 格`}
                subtitle={`间距 ${gridPreview.gridSpacingPercent.toFixed(2)}%`}
                color="indigo"
              />
              <PreviewCard
                icon={<AlertTriangle className="w-5 h-5 text-red-600" />}
                label="预估强平价"
                value={`$${gridPreview.liqPrice.toFixed(2)}`}
                subtitle="风险提示"
                color="red"
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Running Grids */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <Activity className="w-4 h-4 text-blue-600" />
            <span>运行中的网格实例</span>
            <Badge className="bg-blue-600 text-white border-0 text-xs">{grids.length}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white">
          {grids.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-blue-50 rounded-xl flex items-center justify-center mx-auto mb-4">
                <Grid3x3 className="w-8 h-8 text-blue-400" />
              </div>
              <h3 className="text-base font-semibold text-gray-900 mb-2">暂无运行中的网格</h3>
              <p className="text-sm text-gray-500">配置参数后点击"启动当前类型网格"开始交易</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
              {grids.map((g) => (
                <div
                  key={g.id}
                  className="bg-white rounded-lg border border-gray-200 hover:border-blue-400 hover:shadow-md transition-all duration-200 overflow-hidden"
                >
                  <div className="p-4">
                    {/* Header */}
                    <div className="flex items-start justify-between mb-3">
                      <Badge className={`${modeColor(g.grid_mode)} border-0 text-xs`}>
                        {modeLabel(g.grid_mode)}
                      </Badge>
                      <Badge className="bg-green-100 text-green-700 border-0 text-xs">
                        <span className="w-1.5 h-1.5 bg-green-500 rounded-full mr-1 inline-block animate-pulse"></span>
                        运行中
                      </Badge>
                    </div>

                    {/* Symbol */}
                    <h3 className="font-semibold text-gray-900 mb-1">
                      {g.symbol} · {g.exchange.toUpperCase()}
                    </h3>

                    {/* Price Info */}
                    <div className="bg-gray-50 rounded-lg p-3 mb-3 space-y-2">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-gray-600">当前价格</span>
                        <span className="font-semibold text-gray-900">${g.current_price.toFixed(2)}</span>
                      </div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-gray-600">价格区间</span>
                        <span className="text-gray-900">
                          ${g.price_lower} - ${g.price_upper}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-gray-600">网格数量</span>
                        <span className="text-gray-900">{g.grid_count} 格</span>
                      </div>
                    </div>

                    {/* Stats */}
                    <div className="grid grid-cols-2 gap-2 mb-3">
                      <div className="bg-blue-50 rounded-lg p-2">
                        <div className="flex items-center space-x-1 mb-1">
                          <Activity className="w-3 h-3 text-blue-600" />
                          <span className="text-xs text-blue-600">成交次数</span>
                        </div>
                        <p className="text-lg font-bold text-blue-900">{g.total_trades}</p>
                      </div>
                      <div className="bg-green-50 rounded-lg p-2">
                        <div className="flex items-center space-x-1 mb-1">
                          <DollarSign className="w-3 h-3 text-green-600" />
                          <span className="text-xs text-green-600">累计收益</span>
                        </div>
                        <p className="text-lg font-bold text-green-900">
                          ${g.profit.toFixed(2)}
                        </p>
                      </div>
                    </div>

                    {/* Start Time */}
                    <div className="flex items-center text-xs text-gray-500 mb-3">
                      <Clock className="w-3 h-3 mr-1" />
                      {g.start_time}
                    </div>

                    {/* Stop Button */}
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full border-red-200 text-red-600 hover:bg-red-50"
                      onClick={() => stopOne(g.id)}
                    >
                      <Square className="w-4 h-4 mr-1.5" />
                      停止网格
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Grid Logs */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <Activity className="w-4 h-4 text-gray-600" />
            <span>网格日志</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white">
          <div className="bg-gray-900 rounded-lg p-4 font-mono text-sm text-green-400 min-h-[120px]">
            <p>系统就绪，等待网格交易日志...</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// Preview Card Component
function PreviewCard({
  icon,
  label,
  value,
  subtitle,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  subtitle: string;
  color: string;
}) {
  const colorClasses: Record<string, string> = {
    blue: 'bg-blue-100',
    green: 'bg-green-100',
    purple: 'bg-purple-100',
    emerald: 'bg-emerald-100',
    indigo: 'bg-indigo-100',
    red: 'bg-red-100',
  };

  return (
    <div className="bg-white rounded-lg p-4 border border-gray-200">
      <div className={`w-10 h-10 ${colorClasses[color]} rounded-lg flex items-center justify-center mb-3`}>
        {icon}
      </div>
      <p className="text-xs text-gray-600 mb-1">{label}</p>
      <p className="text-xl font-bold text-gray-900 mb-0.5">{value}</p>
      <p className="text-xs text-gray-500">{subtitle}</p>
    </div>
  );
}
