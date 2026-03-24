import { useEffect, useState } from 'react';
import { 
  TrendingUp, 
  Wallet, 
  DollarSign, 
  Percent, 
  Activity,
  CheckCircle,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  BarChart3,
  List,
  Zap,
  AlertTriangle
} from 'lucide-react';
import { 
  LineChart, 
  Line, 
  AreaChart,
  Area,
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer 
} from 'recharts';

// Mock data
const generateChartData = () => {
  const data = [];
  const now = new Date();
  for (let i = 23; i >= 0; i--) {
    const time = new Date(now.getTime() - i * 60 * 60 * 1000);
    data.push({
      time: time.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      value: 10000 + Math.random() * 2000 + (23 - i) * 50,
    });
  }
  return data;
};

const mockOrders = [
  { symbol: 'ETH_USDC_PERP', type: 'market', side: 'BUY', price: '市价', amount: '0.0113', status: 'open' },
  { symbol: 'ETH_USDC_PERP', type: 'market', side: 'BUY', price: '市价', amount: '0.0113', status: 'open' },
  { symbol: 'ETH_USDC_PERP', type: 'market', side: 'SELL', price: '市价', amount: '0.0113', status: 'open' },
  { symbol: 'ETH_USDC_PERP', type: 'market', side: 'BUY', price: '市价', amount: '0.0113', status: 'open' },
  { symbol: 'ETH_USDC_PERP', type: 'market', side: 'SELL', price: '市价', amount: '0.0113', status: 'open' },
];

const StatCard = ({ icon: Icon, label, value, prefix, trend, color = 'blue' }: any) => {
  const colorClasses = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    purple: 'bg-purple-50 text-purple-600',
    orange: 'bg-orange-50 text-orange-600',
  };

  return (
    <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
      <div className="flex items-center justify-between mb-4">
        <div className={`w-12 h-12 rounded-lg ${colorClasses[color]} flex items-center justify-center`}>
          <Icon className="w-6 h-6" />
        </div>
        {trend !== undefined && (
          <div className={`flex items-center gap-1 text-sm font-medium ${trend >= 0 ? 'text-green-600' : 'text-red-600'}`}>
            {trend >= 0 ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
            <span>{Math.abs(trend).toFixed(2)}%</span>
          </div>
        )}
      </div>
      <div className="text-gray-500 text-sm mb-2">{label}</div>
      <div className="flex items-baseline gap-2">
        {prefix && <span className="text-gray-400 text-sm">{prefix}</span>}
        <span className="text-2xl font-semibold text-gray-900">{value}</span>
      </div>
    </div>
  );
};

export default function App() {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [chartData] = useState(generateChartData());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-[1600px] mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
                  <BarChart3 className="w-5 h-5 text-white" />
                </div>
                <h1 className="text-xl font-semibold text-gray-900">数据资产监控</h1>
              </div>
              <span className="px-3 py-1 rounded-full bg-green-50 text-green-700 text-sm border border-green-200 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500"></span>
                实盘运行中
              </span>
            </div>
            <div className="flex items-center gap-2 text-gray-600 text-sm">
              <Clock className="w-4 h-4" />
              <span>{currentTime.toISOString().slice(0, 19).replace('T', ' ')}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-[1600px] mx-auto px-6 py-6">
        {/* Page Title */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2.5 py-1 rounded bg-blue-50 text-blue-600 text-xs font-medium">
              量化监控 · 实盘联动
            </span>
          </div>
          <h2 className="text-2xl font-semibold text-gray-900 mb-1">数据资产监控大屏</h2>
          <p className="text-gray-600">实时汇总账户资产、盈亏表现与风险事件，让你一眼看清今天过得怎么样。</p>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <StatCard
            icon={Wallet}
            label="总资产价值"
            value="$0.00"
            prefix="USD"
            color="blue"
          />
          <StatCard
            icon={DollarSign}
            label="可用现金"
            value="$0.00"
            prefix="CASH"
            color="green"
          />
          <StatCard
            icon={TrendingUp}
            label="当日盈亏"
            value="$0.00"
            prefix="P&L"
            trend={0}
            color="purple"
          />
          <StatCard
            icon={Percent}
            label="当日收益率"
            value="0.00%"
            prefix="RETURN"
            trend={0}
            color="orange"
          />
        </div>

        {/* Chart */}
        <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 mb-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-1">组合累计净值曲线</h3>
              <p className="text-gray-600 text-sm">查看策略24小时内的净值走势</p>
            </div>
            <div className="flex gap-2">
              <span className="px-3 py-1 rounded-full bg-blue-50 text-blue-600 text-xs border border-blue-200">
                净值基准 1.0
              </span>
              <span className="px-3 py-1 rounded-full bg-green-50 text-green-600 text-xs border border-green-200">
                自动刷新
              </span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2}/>
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis 
                dataKey="time" 
                stroke="#9ca3af"
                tick={{ fill: '#6b7280', fontSize: 12 }}
              />
              <YAxis 
                stroke="#9ca3af"
                tick={{ fill: '#6b7280', fontSize: 12 }}
              />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: '#fff', 
                  border: '1px solid #e5e7eb',
                  borderRadius: '8px',
                  boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)'
                }}
              />
              <Area 
                type="monotone" 
                dataKey="value" 
                stroke="#3b82f6" 
                strokeWidth={2}
                fill="url(#colorValue)" 
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Tables Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Positions */}
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <div className="mb-4">
              <h3 className="text-lg font-semibold text-gray-900 mb-1">当前活动仓位</h3>
              <p className="text-gray-600 text-sm">实时跟踪每一笔持仓盈亏</p>
            </div>
            <div className="flex flex-col items-center justify-center py-16">
              <div className="w-16 h-16 rounded-full bg-green-50 flex items-center justify-center mb-4">
                <CheckCircle className="w-8 h-8 text-green-500" />
              </div>
              <p className="text-gray-600">无活跃持仓</p>
            </div>
          </div>

          {/* Orders */}
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-1">活动订单</h3>
                <p className="text-gray-600 text-sm">挂单与进行中委托</p>
              </div>
              <button className="px-3 py-1.5 text-sm text-blue-600 hover:bg-blue-50 rounded-lg transition-colors">
                查看全部 →
              </button>
            </div>
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-100">
                    <th className="text-left py-3 px-2 font-medium">交易对</th>
                    <th className="text-left py-3 px-2 font-medium">类型</th>
                    <th className="text-left py-3 px-2 font-medium">方向</th>
                    <th className="text-left py-3 px-2 font-medium">价格</th>
                    <th className="text-left py-3 px-2 font-medium">数量</th>
                    <th className="text-left py-3 px-2 font-medium">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {mockOrders.map((order, i) => (
                    <tr key={i} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                      <td className="py-3 px-2 text-gray-900 font-medium">{order.symbol}</td>
                      <td className="py-3 px-2 text-gray-600">{order.type}</td>
                      <td className="py-3 px-2">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          order.side === 'BUY' 
                            ? 'bg-green-50 text-green-700' 
                            : 'bg-red-50 text-red-700'
                        }`}>
                          {order.side}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-gray-600">{order.price}</td>
                      <td className="py-3 px-2 text-gray-600">{order.amount}</td>
                      <td className="py-3 px-2">
                        <span className="px-2 py-1 rounded text-xs font-medium bg-blue-50 text-blue-700">
                          {order.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Bottom Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Trade History */}
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <div className="mb-4">
              <h3 className="text-lg font-semibold text-gray-900 mb-1">成交历史</h3>
              <p className="text-gray-600 text-sm">最近成交与盈亏分布</p>
            </div>
            <div className="flex flex-col items-center justify-center py-16">
              <div className="w-16 h-16 rounded-full bg-gray-50 flex items-center justify-center mb-4">
                <List className="w-8 h-8 text-gray-400" />
              </div>
              <p className="text-gray-600">暂无成交历史</p>
            </div>
          </div>

          {/* Risk Events */}
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <div className="mb-4">
              <h3 className="text-lg font-semibold text-gray-900 mb-1">风险事件</h3>
              <p className="text-gray-600 text-sm">预警记录与系统提示</p>
            </div>
            <div className="flex flex-col items-center justify-center py-16">
              <div className="w-16 h-16 rounded-full bg-green-50 flex items-center justify-center mb-4">
                <CheckCircle className="w-8 h-8 text-green-500" />
              </div>
              <p className="text-green-600 font-medium">系统运行正常</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}