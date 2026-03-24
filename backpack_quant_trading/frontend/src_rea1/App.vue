<template>
  <div class="app-container">
    <Sidebar />
    
    <main class="main-content">
      <!-- Header -->
      <header class="header">
        <div class="header-left">
          <h1 class="page-title">量化策略矩阵</h1>
          <span class="status-badge">
            <span class="status-dot"></span>
            实时更新中
          </span>
        </div>
        
        <div class="header-right">
          <button class="icon-btn">🔔</button>
          <button class="icon-btn">🔄</button>
          <div class="user-info">
            <div class="user-avatar">zy</div>
            <div class="user-details">
              <div class="user-name">zyf</div>
              <div class="user-role">管理员</div>
            </div>
          </div>
        </div>
      </header>

      <!-- Stats Grid -->
      <div class="content-wrapper">
        <div class="stats-grid">
          <StatCard
            v-for="(stat, index) in stats"
            :key="index"
            :label="stat.label"
            :value="stat.value"
            :change="stat.change"
            :changeType="stat.changeType"
            :percentage="stat.percentage"
            :iconName="stat.iconName"
            :iconColor="stat.iconColor"
          />
        </div>

        <!-- Search and Filters -->
        <div class="search-filter-section">
          <SearchBar />
          <ViewToggle v-model:viewMode="viewMode" />
        </div>

        <!-- Strategy Cards Grid - 2 columns -->
        <div class="cards-grid">
          <StrategyCard
            v-for="strategy in strategies"
            :key="strategy.id"
            :name="strategy.name"
            :code="strategy.code"
            :status="strategy.status"
            :progress="strategy.progress"
            :description="strategy.description"
            :annualizedReturn="strategy.annualizedReturn"
            :totalReturn="strategy.totalReturn"
            :sharpeRatio="strategy.sharpeRatio"
            :riskLevel="strategy.riskLevel"
          />
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import Sidebar from './components/Sidebar.vue';
import StatCard from './components/StatCard.vue';
import StrategyCard from './components/StrategyCard.vue';
import SearchBar from './components/SearchBar.vue';
import ViewToggle from './components/ViewToggle.vue';

const viewMode = ref('grid');

const stats = ref([
  {
    label: '策略总数',
    value: '12',
    change: '+2 本月',
    changeType: 'positive',
    iconName: 'bar-chart',
    iconColor: 'bg-blue-500'
  },
  {
    label: '运行中策略',
    value: '8',
    percentage: '66.7%',
    iconName: 'trending-up',
    iconColor: 'bg-blue-400'
  },
  {
    label: '平均胜率',
    value: '79.22%',
    change: '+3.5%',
    changeType: 'positive',
    iconName: 'trending-up',
    iconColor: 'bg-blue-500'
  },
  {
    label: '累计收益',
    value: '¥1.28M',
    change: '+12.3%',
    changeType: 'positive',
    iconName: 'wallet',
    iconColor: 'bg-blue-500'
  }
]);

const strategies = ref([
  {
    id: 1,
    name: '沐龙加密波动率增强策略',
    code: 'ML-DTS',
    status: '运行中',
    progress: 98,
    description: '专注 BTC / ETH 等主流加密货币，捕捉由波动率扩张驱动的中长期趋势，通过多周期协同间的池盖汤味音...',
    annualizedReturn: 22.82,
    totalReturn: 0.00,
    sharpeRatio: 1.51,
    riskLevel: '低风险'
  },
  {
    id: 2,
    name: '沐龙黄金波动率周期捕提策略',
    code: 'ML-GVCS',
    status: '运行中',
    progress: 80,
    description: '专注 XAU/USD 波动率周期，结合宏观趋势与关键支撑区布局，坚持『低位等待、确定性介入』原则，...',
    annualizedReturn: 36.44,
    totalReturn: 0.00,
    sharpeRatio: 2.89,
    riskLevel: '低风险'
  },
  {
    id: 3,
    name: '沐龙纳指趋势追踪增强策略',
    code: 'ML-NAS',
    status: '运行中',
    progress: 60,
    description: '聚焦纳斯达克数的中长期趋势行情，结合趋势速度与回撤过滤，确核关键支撑区段行为批捷色与风控，...',
    annualizedReturn: 27.44,
    totalReturn: 0.00,
    sharpeRatio: 1.65,
    riskLevel: '低风险'
  },
  {
    id: 4,
    name: '沐龙A股动量轮动策略',
    code: 'ML-AMR',
    status: '测试中',
    progress: 72,
    description: '基于A股市场动量因子，结合市场情绪指标进行行业轮动配置，在震荡市中寻找相对强势板块进行配置，追...',
    annualizedReturn: 0,
    totalReturn: 0,
    sharpeRatio: 0,
    riskLevel: '低风险'
  },
  {
    id: 5,
    name: '沐龙商品期货套利策略',
    code: 'ML-CFA',
    status: '运行中',
    progress: 86,
    description: '利用期货市场周期，商品价格差进行统计套利，通过均值回归模型筛选价差套动机会，在控制风险的前提...',
    annualizedReturn: 0,
    totalReturn: 0,
    sharpeRatio: 0,
    riskLevel: '低风险'
  },
  {
    id: 6,
    name: '沐龙外汇波段交易策略',
    code: 'ML-FXS',
    status: '已暂停',
    progress: 68,
    description: '专注GIO货币对的中短期波段交易，结合技术分析与宏观经济周期判断，在主要货币对中寻找概率概支交易机...',
    annualizedReturn: 0,
    totalReturn: 0,
    sharpeRatio: 0,
    riskLevel: '低风险'
  }
]);
</script>

<style scoped>
.app-container {
  display: flex;
  height: 100vh;
  background: #f9fafb;
}

.main-content {
  flex: 1;
  overflow: auto;
}

/* Header */
.header {
  background: white;
  border-bottom: 1px solid #e5e7eb;
  padding: 16px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: #111827;
}

.status-badge {
  padding: 6px 12px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 14px;
  border-radius: 20px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 8px;
  height: 8px;
  background: #2563eb;
  border-radius: 50%;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.icon-btn {
  padding: 8px;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 20px;
  transition: background 0.2s;
}

.icon-btn:hover {
  background: #f3f4f6;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar {
  width: 32px;
  height: 32px;
  background: #3b82f6;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
}

.user-details {
  text-align: right;
}

.user-name {
  font-size: 14px;
  font-weight: 500;
  color: #111827;
}

.user-role {
  font-size: 12px;
  color: #6b7280;
}

/* Content */
.content-wrapper {
  padding: 24px 32px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.search-filter-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

/* Strategy Cards Grid - 2 columns */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

/* Responsive */
@media (max-width: 1280px) {
  .cards-grid {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .search-filter-section {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .header {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }
}
</style>
