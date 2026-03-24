import { StatCard } from './components/StatCard';
import { StrategyCard } from './components/StrategyCard';
import { BarChart3, Activity, TrendingUp, Wallet, Search, Filter, Plus, LayoutGrid, List } from 'lucide-react';

export default function App() {
  const stats = [
    {
      title: '策略总数',
      value: '12',
      change: '+2 本月',
      isPositive: true,
      icon: BarChart3,
      iconColor: 'bg-blue-100 text-blue-600',
    },
    {
      title: '运行中策略',
      value: '8',
      change: '66.7%',
      isPositive: true,
      icon: Activity,
      iconColor: 'bg-blue-100 text-blue-600',
    },
    {
      title: '平均收益',
      value: '79.22%',
      change: '+5.5%',
      isPositive: true,
      icon: TrendingUp,
      iconColor: 'bg-blue-100 text-blue-600',
    },
    {
      title: '累计总盈',
      value: '¥1.28M',
      change: '+5.3%',
      isPositive: true,
      icon: Wallet,
      iconColor: 'bg-blue-100 text-blue-600',
    },
  ];

  const strategies = [
    {
      title: '沐龙加密波动率增强策略',
      code: 'ML-DTS',
      description: '专注 BTC / ETH 等主流加密货币，捕捉由波动率扩张驱动的中长期趋势，通过多周期协同过滤震荡噪音，追求稳健的风险调整后收益。',
      status: '运行中',
      statusColor: 'bg-green-100 text-green-700',
      progress: 98,
      progressColor: '#10b981',
      annualReturn: '22.82%',
      drawdown: '0.00%',
      profitFactor: '1.51',
      riskIndex: '低风险',
      isRiskWarning: false,
    },
    {
      title: '沐龙黄金波动率周期捕捉策略',
      code: 'ML-GVCS',
      description: '专注 XAU/USD 波动率周期，结合宏观趋势与关键支撑区间布局，坚持「低位等待、确定性介入」原则，利用波动率扩张捕捉中期行情。',
      status: '运行中',
      statusColor: 'bg-green-100 text-green-700',
      progress: 80,
      progressColor: '#10b981',
      annualReturn: '36.44%',
      drawdown: '-1.81%',
      profitFactor: '2.89',
      riskIndex: '低风险',
      isRiskWarning: false,
    },
    {
      title: '沐龙纳指趋势追踪增强策略',
      code: 'ML-NAS',
      description: '聚焦纳斯达克指数的中长期趋势行情，结合趋势强度与回撤过滤，围绕关键趋势段进行分批建仓与风控，强调顺势持有与风险控制。',
      status: '运行中',
      statusColor: 'bg-green-100 text-green-700',
      progress: 60,
      progressColor: '#3b82f6',
      annualReturn: '27.44%',
      drawdown: '0.00%',
      profitFactor: '1.65',
      riskIndex: '低风险',
      isRiskWarning: false,
    },
    {
      title: '沐龙A股动量轮动策略',
      code: 'ML-AMR',
      description: '聚焦A股市场中的强势板块与个股，结合市场情绪指标与技术支撑进行动量捕捉，在震荡市依托强势因子做板块轮动，在趋势市集中持仓捕捉主升。',
      status: '测试中',
      statusColor: 'bg-blue-100 text-blue-700',
      progress: 72,
      progressColor: '#10b981',
      annualReturn: '18.29%',
      drawdown: '0.00%',
      profitFactor: '1.39',
      riskIndex: '低风险',
      isRiskWarning: false,
    },
    {
      title: '沐龙商品期货套利策略',
      code: 'ML-CFA',
      description: '利用期货市场中的跨品种套利、跨期套利与跨市场套利机会，通过统计套利模型识别价差修复机会，强调低风险稳健收益，在低波动环境下获取阿尔法。',
      status: '运行中',
      statusColor: 'bg-green-100 text-green-700',
      progress: 86,
      progressColor: '#10b981',
      annualReturn: '16.73%',
      drawdown: '-2.81%',
      profitFactor: '2.15',
      riskIndex: '低风险',
      isRiskWarning: false,
    },
    {
      title: '沐龙外汇波段交易策略',
      code: 'ML-FXS',
      description: '专注G7货币对的日内波段交易，结合央行政策预期与技术形态进行进出场，坚持「在低波动区布局，在波动扩张时获利」的核心逻辑，严控单笔风险与回撤。',
      status: '监控中',
      statusColor: 'bg-orange-100 text-orange-700',
      progress: 88,
      progressColor: '#3b82f6',
      annualReturn: '24.62%',
      drawdown: '-3.44%',
      profitFactor: '1.72',
      riskIndex: '低风险',
      isRiskWarning: false,
    },
  ];

  return (
    <div className="min-h-screen bg-[#f3f6fb]">
      <div className="max-w-[1400px] mx-auto p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 mb-1">量化策略矩阵</h1>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-medium">
                <span className="w-1.5 h-1.5 bg-blue-600 rounded-full"></span>
                实时数据中
              </span>
            </div>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {stats.map((stat, index) => (
            <StatCard
              key={index}
              title={stat.title}
              value={stat.value}
              change={stat.change}
              isPositive={stat.isPositive}
              icon={stat.icon}
              iconColor={stat.iconColor}
            />
          ))}
        </div>

        {/* Search and Filter Bar */}
        <div className="flex items-center gap-3 mb-6">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="搜索策略名称或代码..."
              className="w-full pl-10 pr-4 py-2.5 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button className="flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition-colors">
            <Filter className="w-4 h-4" />
            <span>全部筛选</span>
          </button>
          <button className="p-2.5 bg-white border border-gray-200 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors">
            <LayoutGrid className="w-4 h-4" />
          </button>
          <button className="p-2.5 bg-white border border-gray-200 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors">
            <List className="w-4 h-4" />
          </button>
          <button className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
            <Plus className="w-4 h-4" />
            <span>新建策略</span>
          </button>
        </div>

        {/* Strategies Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {strategies.map((strategy, index) => (
            <StrategyCard
              key={index}
              title={strategy.title}
              code={strategy.code}
              description={strategy.description}
              status={strategy.status}
              statusColor={strategy.statusColor}
              progress={strategy.progress}
              progressColor={strategy.progressColor}
              annualReturn={strategy.annualReturn}
              drawdown={strategy.drawdown}
              profitFactor={strategy.profitFactor}
              riskIndex={strategy.riskIndex}
              isRiskWarning={strategy.isRiskWarning}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
