import { useEffect, useState } from 'react';
import {
  getStrategies,
  getInstances,
  launchStrategy,
  stopInstance,
  getLogs,
  type Instance,
  type Strategy,
} from '../api/trading';
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { ScrollArea } from './ui/scroll-area';
import {
  Activity,
  TrendingUp,
  BarChart3,
  Settings,
  FileText,
  LogOut,
  Plus,
  Play,
  Square,
  Zap,
  DollarSign,
  Clock,
  AlertCircle,
  Bell,
  User,
  Menu,
  ChevronRight,
  LineChart,
  Rocket,
  Shield,
  Target,
} from 'lucide-react';
import { Badge } from './ui/badge';

const PLATFORMS = [
  { label: 'Backpack', value: 'backpack' },
  { label: 'Deepcoin', value: 'deepcoin' },
  { label: 'Ostium', value: 'ostium' },
  { label: 'Hyperliquid', value: 'hyperliquid' },
];

export function TradingPage() {
  const [showModal, setShowModal] = useState(false);
  const [instances, setInstances] = useState<Instance[]>([]);
  const [logs, setLogs] = useState('等待日志输出...');
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [launching, setLaunching] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [form, setForm] = useState({
    platform: 'backpack',
    strategy: 'mean_reversion',
    symbol: 'ETH/USDC',
    size: 20,
    leverage: 50,
    take_profit: 2.0,
    stop_loss: 1.5,
    api_key: '',
    api_secret: '',
    passphrase: '',
    private_key: '',
  });

  const isDualFreq = form.strategy === 'dual_freq_trend';

  const setField = (name: string, value: string | number) => {
    setForm((prev) => ({ ...prev, [name]: value }));
    if (name === 'strategy' && value === 'dual_freq_trend') {
      setForm((prev) => ({
        ...prev,
        leverage: 100,
        size: 10,
        take_profit: 150,
        stop_loss: 50,
      }));
    }
  };

  const refresh = async () => {
    try {
      const res = await getInstances();
      setInstances(res.instances || []);
    } catch (_) {}
  };

  const refreshLogs = async () => {
    try {
      const res = await getLogs();
      setLogs(res.logs || '等待日志输出...');
    } catch (_) {}
  };

  useEffect(() => {
    let t1: NodeJS.Timeout, t2: NodeJS.Timeout;
    const load = async () => {
      try {
        const res = await getStrategies();
        setStrategies(res.strategies || []);
      } catch (_) {}
      await refresh();
      await refreshLogs();
      t1 = setInterval(refresh, 5000);
      t2 = setInterval(refreshLogs, 10000);
    };
    load();
    return () => {
      if (t1) clearInterval(t1);
      if (t2) clearInterval(t2);
    };
  }, []);

  const handleLaunch = async () => {
    if (['backpack', 'deepcoin'].includes(form.platform)) {
      if (!form.api_key || !form.api_secret) {
        alert('请输入 API Key 和 Secret');
        return;
      }
    } else {
      if (!form.private_key) {
        alert('请输入私钥');
        return;
      }
    }
    setLaunching(true);
    try {
      const res = await launchStrategy({
        platform: form.platform,
        strategy: form.strategy,
        symbol: form.symbol,
        size: form.size,
        leverage: form.leverage,
        take_profit: form.take_profit,
        stop_loss: form.stop_loss,
        api_key: form.api_key || undefined,
        api_secret: form.api_secret || undefined,
        passphrase: form.passphrase || undefined,
        private_key: form.private_key || undefined,
      });
      alert(res.message || '启动成功');
      setShowModal(false);
      await refresh();
    } catch (e: any) {
      alert(e?.response?.data?.detail || '启动失败');
    } finally {
      setLaunching(false);
    }
  };

  const stopOne = async (id: string) => {
    try {
      await stopInstance(id);
      alert('已停止');
      await refresh();
    } catch (e: any) {
      alert(e?.response?.data?.detail || '停止失败');
    }
  };

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside
        className={`${
          sidebarCollapsed ? 'w-20' : 'w-64'
        } bg-white border-r border-gray-200 transition-all duration-300 flex flex-col`}
      >
        {/* Logo */}
        <div className="h-16 flex items-center justify-between px-5 border-b border-gray-100">
          {!sidebarCollapsed && (
            <div className="flex items-center space-x-3">
              <div className="w-9 h-9 bg-blue-600 rounded-lg flex items-center justify-center">
                <Zap className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-base font-bold text-gray-900">沐龙量化</h1>
                <p className="text-xs text-gray-500">Quant Platform</p>
              </div>
            </div>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="p-1.5 hover:bg-gray-100 rounded-md transition-colors"
          >
            <Menu className="w-5 h-5 text-gray-600" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1">
          <NavItem
            icon={<Rocket className="w-5 h-5" />}
            text="实盘交易"
            collapsed={sidebarCollapsed}
            active
            onClick={() => {}}
          />
          <NavItem
            icon={<LineChart className="w-5 h-5" />}
            text="数据大屏"
            collapsed={sidebarCollapsed}
            onClick={() => {}}
          />
          <NavItem
            icon={<BarChart3 className="w-5 h-5" />}
            text="AI 分析"
            collapsed={sidebarCollapsed}
            onClick={() => {}}
          />
          <NavItem
            icon={<Target className="w-5 h-5" />}
            text="合约网格"
            collapsed={sidebarCollapsed}
            onClick={() => {}}
          />
          <NavItem
            icon={<Bell className="w-5 h-5" />}
            text="市场监控"
            collapsed={sidebarCollapsed}
            onClick={() => {}}
          />
          <NavItem
            icon={<TrendingUp className="w-5 h-5" />}
            text="A股 AI 选股"
            collapsed={sidebarCollapsed}
            onClick={() => {}}
          />
          <NavItem
            icon={<Shield className="w-5 h-5" />}
            text="量化策略矩阵"
            collapsed={sidebarCollapsed}
            onClick={() => {}}
          />
          <NavItem
            icon={<Settings className="w-5 h-5" />}
            text="系统设置"
            collapsed={sidebarCollapsed}
            onClick={() => {}}
          />
        </nav>

        {/* Bottom User Info */}
        {!sidebarCollapsed && (
          <div className="p-4 border-t border-gray-100">
            <div className="flex items-center space-x-3 p-2 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer">
              <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                <span className="text-sm font-semibold text-blue-600">ML</span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">管理员</p>
                <div className="flex items-center space-x-1">
                  <span className="w-2 h-2 bg-green-500 rounded-full"></span>
                  <span className="text-xs text-gray-500">运行正常</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6">
          <div className="flex items-center space-x-3">
            <h1 className="text-lg font-semibold text-gray-900">实盘交易</h1>
            <Badge className="bg-green-100 text-green-700 border-0 text-xs">
              <span className="w-1.5 h-1.5 bg-green-500 rounded-full mr-1"></span>
              系统运行中
            </Badge>
          </div>
          <div className="flex items-center space-x-3">
            <div className="px-3 py-1.5 bg-blue-50 rounded-md">
              <span className="text-xs text-blue-600 font-medium">API 配额: 8,750/10,000</span>
            </div>
            <button className="p-2 hover:bg-gray-100 rounded-lg transition-colors relative">
              <Bell className="w-5 h-5 text-gray-600" />
              <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full"></span>
            </button>
            <button className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
              <User className="w-5 h-5 text-gray-600" />
            </button>
            <Button variant="outline" size="sm" className="text-red-600 border-red-200 hover:bg-red-50">
              <LogOut className="w-4 h-4 mr-1" />
              退出
            </Button>
          </div>
        </header>

        {/* Main */}
        <main className="flex-1 overflow-auto p-6 space-y-6 bg-gray-50">
          {/* Stats Overview */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <StatCard
              icon={<Activity className="w-6 h-6 text-white" />}
              title="运行中策略"
              value={instances.length.toString()}
              subtitle="个活跃实例"
              color="blue"
            />
            <StatCard
              icon={<DollarSign className="w-6 h-6 text-white" />}
              title="总资产"
              value="$24,567"
              subtitle="+5.23% 今日"
              color="green"
            />
            <StatCard
              icon={<TrendingUp className="w-6 h-6 text-white" />}
              title="累计收益"
              value="+18.5%"
              subtitle="本月表现"
              color="purple"
            />
            <StatCard
              icon={<Target className="w-6 h-6 text-white" />}
              title="胜率"
              value="67.8%"
              subtitle="最近30笔"
              color="orange"
            />
          </div>

          {/* Action Bar */}
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-gray-900">策略实例管理</h2>
              <p className="text-sm text-gray-500">查看和管理所有运行中的量化交易策略</p>
            </div>
            <Button 
              onClick={() => setShowModal(true)} 
              className="bg-blue-600 hover:bg-blue-700"
            >
              <Plus className="w-4 h-4 mr-1.5" />
              启动新策略
            </Button>
          </div>

          {/* Instances Section */}
          <Card className="border border-gray-200 shadow-sm">
            <CardHeader className="border-b border-gray-100 bg-white">
              <CardTitle className="flex items-center space-x-2 text-base font-semibold">
                <Play className="w-4 h-4 text-blue-600" />
                <span>运行中的策略实例</span>
                <Badge className="bg-blue-600 text-white border-0 text-xs">{instances.length}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="p-6 bg-white">
              {instances.length === 0 ? (
                <div className="text-center py-12">
                  <div className="w-16 h-16 bg-blue-50 rounded-xl flex items-center justify-center mx-auto mb-4">
                    <Rocket className="w-8 h-8 text-blue-400" />
                  </div>
                  <h3 className="text-base font-semibold text-gray-900 mb-2">暂无运行中的策略</h3>
                  <p className="text-sm text-gray-500 mb-4">点击"启动新策略"按钮开始您的量化交易之旅</p>
                  <Button 
                    onClick={() => setShowModal(true)}
                    className="bg-blue-600 hover:bg-blue-700"
                  >
                    <Plus className="w-4 h-4 mr-1.5" />
                    立即启动
                  </Button>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
                  {instances.map((inst) => (
                    <div
                      key={inst.id}
                      className="bg-white rounded-lg border border-gray-200 hover:border-blue-400 hover:shadow-md transition-all duration-200 overflow-hidden"
                    >
                      <div className="p-4">
                        {/* Header */}
                        <div className="flex items-start justify-between mb-3">
                          <Badge
                            className={`${
                              inst.platform === 'backpack' ? 'bg-blue-50 text-blue-700' :
                              inst.platform === 'deepcoin' ? 'bg-purple-50 text-purple-700' :
                              inst.platform === 'ostium' ? 'bg-orange-50 text-orange-700' :
                              'bg-indigo-50 text-indigo-700'
                            } border-0 text-xs`}
                          >
                            {inst.platform.toUpperCase()}
                          </Badge>
                          <Badge
                            className={
                              inst.status === 'registering'
                                ? 'bg-yellow-50 text-yellow-700 border-0 text-xs'
                                : 'bg-green-50 text-green-700 border-0 text-xs'
                            }
                          >
                            <span className="w-1.5 h-1.5 bg-current rounded-full mr-1 inline-block"></span>
                            {inst.status === 'registering' ? 'REGISTERING' : 'RUNNING'}
                          </Badge>
                        </div>

                        {/* Strategy Name */}
                        <h3 className="font-semibold text-gray-900 mb-3">{inst.strategy_name}</h3>

                        {/* Info */}
                        <div className="space-y-2 mb-3 text-sm">
                          <div className="flex items-center text-gray-600">
                            <TrendingUp className="w-4 h-4 mr-2 text-gray-400" />
                            <span>{inst.symbol}</span>
                          </div>
                          <div className="flex items-center text-gray-600">
                            <Clock className="w-4 h-4 mr-2 text-gray-400" />
                            <span className="text-xs">{inst.start_time}</span>
                          </div>
                          <div className="flex items-center text-gray-600">
                            <Activity className="w-4 h-4 mr-2 text-gray-400" />
                            <span className="text-xs">PID: {inst.pid}</span>
                          </div>
                        </div>

                        {/* Balance Section */}
                        <div className="pt-3 border-t border-gray-100">
                          <div className="bg-gray-50 rounded-lg p-3 mb-3">
                            <div className="flex items-center justify-between">
                              <div>
                                <p className="text-xs text-gray-500 mb-0.5">账户余额</p>
                                <p className="text-xl font-bold text-gray-900">${inst.balance.toLocaleString()}</p>
                              </div>
                              <div className="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center">
                                <DollarSign className="w-5 h-5 text-white" />
                              </div>
                            </div>
                          </div>
                          
                          <Button
                            variant="outline"
                            size="sm"
                            className="w-full border-red-200 text-red-600 hover:bg-red-50"
                            onClick={() => stopOne(inst.id)}
                          >
                            <Square className="w-4 h-4 mr-1.5" />
                            停止策略
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Logs Section */}
          <Card className="border border-gray-200 shadow-sm">
            <CardHeader className="border-b border-gray-100 bg-white">
              <CardTitle className="flex items-center space-x-2 text-base font-semibold">
                <FileText className="w-4 h-4 text-gray-600" />
                <span>系统日志</span>
                <Badge variant="outline" className="text-xs">实时更新</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="p-5 bg-white">
              <div className="rounded-lg overflow-hidden border border-gray-200">
                <div className="bg-gray-100 px-4 py-2 flex items-center justify-between border-b border-gray-200">
                  <div className="flex items-center space-x-2">
                    <div className="w-3 h-3 rounded-full bg-red-500"></div>
                    <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
                    <div className="w-3 h-3 rounded-full bg-green-500"></div>
                  </div>
                  <span className="text-xs text-gray-500 font-mono">system.log</span>
                </div>
                <ScrollArea className="h-72 bg-gray-900 p-4">
                  <pre className="text-sm text-green-400 font-mono whitespace-pre-wrap leading-relaxed">{logs}</pre>
                </ScrollArea>
              </div>
            </CardContent>
          </Card>
        </main>
      </div>

      {/* Launch Strategy Modal */}
      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader className="border-b pb-4">
            <DialogTitle className="text-lg font-semibold">配置并启动实盘策略</DialogTitle>
            <DialogDescription className="text-sm">
              填写以下信息来启动新的量化交易策略，请确保API密钥安全
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {/* Platform & Strategy Row */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-sm font-medium">交易平台</Label>
                <Select value={form.platform} onValueChange={(value) => setField('platform', value)}>
                  <SelectTrigger className="h-10">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PLATFORMS.map((p) => (
                      <SelectItem key={p.value} value={p.value}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-sm font-medium">交易策略</Label>
                <Select value={form.strategy} onValueChange={(value) => setField('strategy', value)}>
                  <SelectTrigger className="h-10">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {strategies.map((s) => (
                      <SelectItem key={s.value} value={s.value}>
                        {s.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* API Credentials Section */}
            {['backpack', 'deepcoin'].includes(form.platform) && (
              <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
                <div className="flex items-start space-x-2 mb-3">
                  <AlertCircle className="w-4 h-4 text-amber-600 mt-0.5" />
                  <div>
                    <h4 className="text-sm font-semibold text-amber-900">API 密钥配置</h4>
                    <p className="text-xs text-amber-700 mt-0.5">请从交易所获取API密钥，确保权限仅限于交易</p>
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="space-y-2">
                    <Label className="text-sm font-medium">API Key</Label>
                    <Input
                      type="password"
                      value={form.api_key}
                      onChange={(e) => setField('api_key', e.target.value)}
                      placeholder="输入 API Key"
                      className="h-10"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm font-medium">API Secret</Label>
                    <Input
                      type="password"
                      value={form.api_secret}
                      onChange={(e) => setField('api_secret', e.target.value)}
                      placeholder="输入 API Secret"
                      className="h-10"
                    />
                  </div>
                  {form.platform === 'deepcoin' && (
                    <div className="space-y-2">
                      <Label className="text-sm font-medium">Passphrase</Label>
                      <Input
                        type="password"
                        value={form.passphrase}
                        onChange={(e) => setField('passphrase', e.target.value)}
                        placeholder="输入 Passphrase"
                        className="h-10"
                      />
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Private Key Section */}
            {!['backpack', 'deepcoin'].includes(form.platform) && (
              <div className="p-4 bg-purple-50 border border-purple-200 rounded-lg">
                <div className="flex items-start space-x-2 mb-3">
                  <Shield className="w-4 h-4 text-purple-600 mt-0.5" />
                  <div>
                    <h4 className="text-sm font-semibold text-purple-900">私钥配置</h4>
                    <p className="text-xs text-purple-700 mt-0.5">该平台使用链上钱包，请输入私钥</p>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="text-sm font-medium">Private Key</Label>
                  <Input
                    type="password"
                    value={form.private_key}
                    onChange={(e) => setField('private_key', e.target.value)}
                    placeholder="输入 0x 开头的私钥"
                    className="h-10"
                  />
                </div>
              </div>
            )}

            {/* Trading Parameters */}
            <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <h4 className="text-sm font-semibold text-blue-900 mb-3 flex items-center">
                <Target className="w-4 h-4 mr-1.5" />
                交易参数配置
              </h4>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label className="text-sm font-medium">交易对</Label>
                  <Input
                    value={form.symbol}
                    onChange={(e) => setField('symbol', e.target.value)}
                    placeholder="ETH/USDC"
                    className="h-10"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-sm font-medium">下单保证金 (USD)</Label>
                  <Input
                    type="number"
                    min={1}
                    value={form.size}
                    onChange={(e) => setField('size', Number(e.target.value))}
                    className="h-10"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-sm font-medium">杠杆倍数</Label>
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
                  <Label className="text-sm font-medium">
                    {isDualFreq ? '止盈(保证金收益%)' : '止盈比例 (%)'}
                  </Label>
                  <Input
                    type="number"
                    min={0}
                    max={isDualFreq ? 300 : 100}
                    step={0.1}
                    value={form.take_profit}
                    onChange={(e) => setField('take_profit', Number(e.target.value))}
                    className="h-10"
                  />
                </div>
                <div className="space-y-2 col-span-2">
                  <Label className="text-sm font-medium">
                    {isDualFreq ? '止损(保证金收益%)' : '止损比例 (%)'}
                  </Label>
                  <Input
                    type="number"
                    min={0}
                    max={isDualFreq ? 200 : 100}
                    step={0.1}
                    value={form.stop_loss}
                    onChange={(e) => setField('stop_loss', Number(e.target.value))}
                    className="h-10"
                  />
                </div>
              </div>
            </div>
          </div>

          <DialogFooter className="border-t pt-4">
            <Button 
              variant="outline" 
              onClick={() => setShowModal(false)}
            >
              取消
            </Button>
            <Button
              className="bg-blue-600 hover:bg-blue-700"
              disabled={launching}
              onClick={handleLaunch}
            >
              <Rocket className="w-4 h-4 mr-1.5" />
              {launching ? '启动中...' : '确认启动实盘进程'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// Stat Card Component
function StatCard({
  icon,
  title,
  value,
  subtitle,
  color,
}: {
  icon: React.ReactNode;
  title: string;
  value: string;
  subtitle: string;
  color: string;
}) {
  const colorClasses = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    purple: 'bg-purple-500',
    orange: 'bg-orange-500',
  }[color];

  return (
    <Card className="border border-gray-200 shadow-sm bg-white">
      <CardContent className="p-5">
        <div className="flex items-start justify-between mb-3">
          <div className={`w-12 h-12 rounded-xl ${colorClasses} flex items-center justify-center`}>
            {icon}
          </div>
        </div>
        <p className="text-sm text-gray-600 mb-1">{title}</p>
        <p className="text-2xl font-bold text-gray-900 mb-0.5">{value}</p>
        <p className="text-xs text-gray-500">{subtitle}</p>
      </CardContent>
    </Card>
  );
}

// Navigation Item Component
function NavItem({
  icon,
  text,
  collapsed,
  active = false,
  onClick,
}: {
  icon: React.ReactNode;
  text: string;
  collapsed: boolean;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center space-x-2.5 px-3 py-2.5 rounded-lg transition-colors text-sm ${
        active
          ? 'bg-blue-50 text-blue-600 font-medium'
          : 'text-gray-700 hover:bg-gray-100'
      } ${collapsed ? 'justify-center' : ''}`}
    >
      {icon}
      {!collapsed && <span className="flex-1 text-left">{text}</span>}
      {!collapsed && active && <ChevronRight className="w-4 h-4" />}
    </button>
  );
}