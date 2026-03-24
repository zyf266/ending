import { useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { StatCard } from './components/StatCard';
import { StrategyCard } from './components/StrategyCard';
import { SearchBar } from './components/SearchBar';
import { ViewToggle } from './components/ViewToggle';
import { 
  BarChart3, 
  TrendingUp, 
  Percent, 
  Wallet 
} from 'lucide-react';

export default function App() {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');

  const stats = [
    {
      label: '策略总数',
      value: '12',
      change: '+2 本月',
      changeType: 'positive' as const,
      icon: BarChart3,
      iconColor: 'bg-blue-500'
    },
    {
      label: '运行中策略',
      value: '8',
      percentage: '66.7%',
      icon: TrendingUp,
      iconColor: 'bg-blue-400'
    },
    {
      label: '平均胜率',
      value: '79.22%',
      change: '+3.5%',
      changeType: 'positive' as const,
      icon: TrendingUp,
      iconColor: 'bg-blue-500'
    },
    {
      label: '累计收益',
      value: '¥1.28M',
      change: '+12.3%',
      changeType: 'positive' as const,
      icon: Wallet,
      iconColor: 'bg-blue-500'
    }
  ];

  const strategies = [
    {
      id: 1,
      name: '沐龙加密波动率增强策略',
      code: 'ML-DTS',
      status: '运行中' as const,
      progress: 98,
      description: '专注 BTC / ETH 等主流加密货币，捕捉由波动率扩张驱动的中长期趋势，通过多周期协同间的池盖汤味音...',
      annualizedReturn: 22.82,
      totalReturn: 0.00,
      sharpeRatio: 1.51,
      riskLevel: '低风险' as const
    },
    {
      id: 2,
      name: '沐龙黄金波动率周期捕提策略',
      code: 'ML-GVCS',
      status: '运行中' as const,
      progress: 80,
      description: '专注 XAU/USD 波动率周期，结合宏观趋势与关键支撑区布局，坚持『低位等待、确定性介入』原则，...',
      annualizedReturn: 36.44,
      totalReturn: 0.00,
      sharpeRatio: 2.89,
      riskLevel: '低风险' as const
    },
    {
      id: 3,
      name: '沐龙纳指趋势追踪增强策略',
      code: 'ML-NAS',
      status: '运行中' as const,
      progress: 60,
      description: '聚焦纳斯达克数的中长期趋势行情，结合趋势速度与回撤过滤，确核关键支撑区段行为批捷色与风控，...',
      annualizedReturn: 27.44,
      totalReturn: 0.00,
      sharpeRatio: 1.65,
      riskLevel: '低风险' as const
    },
    {
      id: 4,
      name: '沐龙A股动量轮动策略',
      code: 'ML-AMR',
      status: '测试中' as const,
      progress: 72,
      description: '基于A股市场动量因子，结合市场情绪指标进行行业轮动配置，在震荡市中寻找相对强势板块进行配置，追...',
      annualizedReturn: 0,
      totalReturn: 0,
      sharpeRatio: 0,
      riskLevel: '低风险' as const
    },
    {
      id: 5,
      name: '沐龙商品期货套利策略',
      code: 'ML-CFA',
      status: '运行中' as const,
      progress: 86,
      description: '利用期货市场周期，商品价格差进行统计套利，通过均值回归模型筛选价差套动机会，在控制风险的前提...',
      annualizedReturn: 0,
      totalReturn: 0,
      sharpeRatio: 0,
      riskLevel: '低风险' as const
    },
    {
      id: 6,
      name: '沐龙外汇波段交易策略',
      code: 'ML-FXS',
      status: '已暂停' as const,
      progress: 68,
      description: '专注GIO货币对的中短期波段交易，结合技术分析与宏观经济周期判断，在主要货币对中寻找概率概支交易机...',
      annualizedReturn: 0,
      totalReturn: 0,
      sharpeRatio: 0,
      riskLevel: '低风险' as const
    }
  ];

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      
      <main className="flex-1 overflow-auto">
        {/* Header */}
        <header className="bg-white border-b border-gray-200 px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-gray-900">量化策略矩阵</h1>
            <span className="px-3 py-1 bg-blue-50 text-blue-600 text-sm rounded-full flex items-center gap-1">
              <span className="w-2 h-2 bg-blue-600 rounded-full"></span>
              实时更新中
            </span>
          </div>
          
          <div className="flex items-center gap-4">
            <button className="p-2 hover:bg-gray-100 rounded-lg">
              <span className="text-gray-600">🔔</span>
            </button>
            <button className="p-2 hover:bg-gray-100 rounded-lg">
              <span className="text-gray-600">🔄</span>
            </button>
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center text-white font-semibold">
                zy
              </div>
              <div className="text-right">
                <div className="text-sm font-medium text-gray-900">zyf</div>
                <div className="text-xs text-gray-500">管理员</div>
              </div>
            </div>
          </div>
        </header>

        {/* Stats Grid */}
        <div className="px-8 py-6">
          <div className="grid grid-cols-4 gap-4 mb-6">
            {stats.map((stat, index) => (
              <StatCard key={index} {...stat} />
            ))}
          </div>

          {/* Search and Filters */}
          <div className="flex items-center justify-between mb-6">
            <SearchBar />
            <ViewToggle viewMode={viewMode} setViewMode={setViewMode} />
          </div>

          {/* Strategy Cards Grid - 2 columns */}
          <div className="grid grid-cols-2 gap-4">
            {strategies.map((strategy) => (
              <StrategyCard key={strategy.id} {...strategy} />
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
