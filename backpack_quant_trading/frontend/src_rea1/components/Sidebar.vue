<template>
  <aside class="sidebar">
    <!-- Logo -->
    <div class="logo-section">
      <div class="logo-wrapper">
        <div class="logo-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/>
            <path d="M2 17l10 5 10-5"/>
            <path d="M2 12l10 5 10-5"/>
          </svg>
        </div>
        <div>
          <div class="logo-text">沐龙量化</div>
          <div class="logo-subtext">Admin · v1.0</div>
        </div>
      </div>
    </div>

    <!-- Menu -->
    <nav class="menu">
      <button
        v-for="(item, index) in menuItems"
        :key="index"
        :class="['menu-item', { active: item.active }]"
      >
        <component :is="getIconComponent(item.icon)" class="menu-icon" />
        <span>{{ item.label }}</span>
      </button>
    </nav>

    <!-- Footer -->
    <div class="sidebar-footer">
      <div class="footer-content">
        <div class="footer-avatar">ML</div>
        <div class="footer-info">
          <div class="footer-status">
            <span class="status-indicator"></span>
            <span class="status-text">运行正常</span>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref } from 'vue';

const menuItems = ref([
  { icon: 'zap', label: '实盘交易', active: false },
  { icon: 'bar-chart', label: '数据大屏', active: false },
  { icon: 'flask', label: 'AI 实验室', active: false },
  { icon: 'grid', label: '合约网格', active: false },
  { icon: 'bell', label: '币种监视', active: false },
  { icon: 'trending-up', label: 'A股 AI 选股', active: false },
  { icon: 'layers', label: '量化策略矩阵', active: true },
  { icon: 'repeat', label: 'OKX AI 交易', active: false },
  { icon: 'chevron-right', label: 'OKX 操作台', active: false }
]);

const getIconComponent = (iconName) => {
  const icons = {
    'zap': ZapIcon,
    'bar-chart': BarChartIcon,
    'flask': FlaskIcon,
    'grid': GridIcon,
    'bell': BellIcon,
    'trending-up': TrendingUpIcon,
    'layers': LayersIcon,
    'repeat': RepeatIcon,
    'chevron-right': ChevronRightIcon
  };
  return icons[iconName];
};

// Icon Components
const ZapIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
    </svg>
  `
};

const BarChartIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <line x1="18" y1="20" x2="18" y2="10"/>
      <line x1="12" y1="20" x2="12" y2="4"/>
      <line x1="6" y1="20" x2="6" y2="14"/>
    </svg>
  `
};

const FlaskIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M9 3h6v7l5 8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2l5-8V3z"/>
    </svg>
  `
};

const GridIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="3" y="3" width="7" height="7"/>
      <rect x="14" y="3" width="7" height="7"/>
      <rect x="14" y="14" width="7" height="7"/>
      <rect x="3" y="14" width="7" height="7"/>
    </svg>
  `
};

const BellIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
      <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
    </svg>
  `
};

const TrendingUpIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/>
      <polyline points="17 6 23 6 23 12"/>
    </svg>
  `
};

const LayersIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polygon points="12 2 2 7 12 12 22 7 12 2"/>
      <polyline points="2 17 12 22 22 17"/>
      <polyline points="2 12 12 17 22 12"/>
    </svg>
  `
};

const RepeatIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polyline points="17 1 21 5 17 9"/>
      <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
      <polyline points="7 23 3 19 7 15"/>
      <path d="M21 13v2a4 4 0 0 1-4 4H3"/>
    </svg>
  `
};

const ChevronRightIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polyline points="9 18 15 12 9 6"/>
    </svg>
  `
};
</script>

<style scoped>
.sidebar {
  width: 240px;
  background: white;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
}

/* Logo Section */
.logo-section {
  padding: 24px;
  border-bottom: 1px solid #e5e7eb;
}

.logo-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  width: 40px;
  height: 40px;
  background: #3b82f6;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.logo-icon svg {
  width: 24px;
  height: 24px;
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  color: #2563eb;
}

.logo-subtext {
  font-size: 12px;
  color: #6b7280;
}

/* Menu */
.menu {
  flex: 1;
  padding: 12px;
  overflow-y: auto;
}

.menu-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 4px;
  font-size: 14px;
  text-align: left;
  border: none;
  background: transparent;
  color: #374151;
  cursor: pointer;
  transition: all 0.2s;
}

.menu-item:hover {
  background: #f9fafb;
}

.menu-item.active {
  background: #eff6ff;
  color: #2563eb;
}

.menu-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.menu-icon svg {
  width: 100%;
  height: 100%;
}

/* Footer */
.sidebar-footer {
  padding: 16px;
  border-top: 1px solid #e5e7eb;
}

.footer-content {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.footer-avatar {
  width: 32px;
  height: 32px;
  background: #dbeafe;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #2563eb;
  font-weight: 600;
  font-size: 12px;
}

.footer-info {
  flex: 1;
}

.footer-status {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-indicator {
  width: 8px;
  height: 8px;
  background: #16a34a;
  border-radius: 50%;
}

.status-text {
  color: #6b7280;
  font-size: 12px;
}
</style>
