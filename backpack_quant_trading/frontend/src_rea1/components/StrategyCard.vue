<template>
  <div class="strategy-card">
    <!-- Header -->
    <div class="card-header">
      <div class="card-title-section">
        <div class="card-title-row">
          <h3 class="card-title">{{ name }}</h3>
          <span :class="['status-badge', statusClass]">
            {{ status }}
          </span>
        </div>
        <div class="card-code">{{ code }}</div>
      </div>
      
      <!-- Circular Progress -->
      <div class="progress-circle">
        <svg class="progress-ring" viewBox="0 0 64 64">
          <circle
            class="progress-ring-bg"
            cx="32"
            cy="32"
            r="28"
            fill="none"
            stroke="#f3f4f6"
            stroke-width="4"
          />
          <circle
            :class="['progress-ring-fill', progressColor]"
            cx="32"
            cy="32"
            r="28"
            fill="none"
            stroke-width="4"
            :stroke-dasharray="circumference"
            :stroke-dashoffset="progressOffset"
            stroke-linecap="round"
            transform="rotate(-90 32 32)"
          />
        </svg>
        <div :class="['progress-text', progressColor]">{{ progress }}%</div>
      </div>
    </div>

    <!-- Description -->
    <p class="card-desc">{{ description }}</p>

    <!-- Metrics -->
    <div class="metrics-grid">
      <!-- Annualized Return -->
      <div class="metric-card bg-blue">
        <div class="metric-header">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/>
            <polyline points="17 6 23 6 23 12"/>
          </svg>
          <span>平均年化</span>
        </div>
        <div class="metric-value positive">{{ annualizedReturn.toFixed(2) }}%</div>
      </div>

      <!-- Total Return -->
      <div class="metric-card bg-red">
        <div class="metric-header">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/>
            <polyline points="17 18 23 18 23 12"/>
          </svg>
          <span>本金回撤</span>
        </div>
        <div class="metric-value negative">{{ totalReturn.toFixed(2) }}%</div>
      </div>
    </div>

    <!-- Bottom Info -->
    <div class="card-footer">
      <div class="footer-item">
        <div class="footer-icon bg-teal">
          <div class="footer-dot"></div>
        </div>
        <div class="footer-info">
          <div class="footer-label">盈利因子</div>
          <div class="footer-value">{{ sharpeRatio.toFixed(2) }}</div>
        </div>
      </div>

      <div class="footer-item">
        <div class="footer-icon bg-green">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
        </div>
        <div class="footer-info">
          <div class="footer-label">风险评级</div>
          <div class="footer-value risk">{{ riskLevel }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { defineProps, computed } from 'vue';

const props = defineProps({
  name: String,
  code: String,
  status: String,
  progress: Number,
  description: String,
  annualizedReturn: Number,
  totalReturn: Number,
  sharpeRatio: Number,
  riskLevel: String
});

const statusClass = computed(() => {
  const statusMap = {
    '运行中': 'running',
    '测试中': 'testing',
    '已暂停': 'paused'
  };
  return statusMap[props.status] || '';
});

const progressColor = computed(() => {
  if (props.progress >= 80) return 'green';
  if (props.progress >= 60) return 'blue';
  return 'orange';
});

const circumference = computed(() => 2 * Math.PI * 28);

const progressOffset = computed(() => {
  return circumference.value * (1 - props.progress / 100);
});
</script>

<style scoped>
.strategy-card {
  background: white;
  border-radius: 12px;
  padding: 24px;
  border: 1px solid #e5e7eb;
  transition: all 0.2s;
  cursor: pointer;
}

.strategy-card:hover {
  transform: translateY(-2px);
  border-color: #3b82f6;
  box-shadow: 0 10px 25px rgba(59, 130, 246, 0.15);
}

/* Header */
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}

.card-title-section {
  flex: 1;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.card-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #111827;
}

.status-badge {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.status-badge.running {
  background: #dcfce7;
  color: #16a34a;
}

.status-badge.testing {
  background: #dbeafe;
  color: #2563eb;
}

.status-badge.paused {
  background: #fed7aa;
  color: #ea580c;
}

.card-code {
  font-size: 14px;
  color: #6b7280;
}

/* Circular Progress */
.progress-circle {
  position: relative;
  width: 64px;
  height: 64px;
  flex-shrink: 0;
}

.progress-ring {
  width: 64px;
  height: 64px;
}

.progress-ring-fill.green {
  stroke: #10b981;
}

.progress-ring-fill.blue {
  stroke: #3b82f6;
}

.progress-ring-fill.orange {
  stroke: #f59e0b;
}

.progress-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 14px;
  font-weight: 700;
}

.progress-text.green {
  color: #16a34a;
}

.progress-text.blue {
  color: #2563eb;
}

.progress-text.orange {
  color: #ea580c;
}

/* Description */
.card-desc {
  margin: 0 0 16px;
  font-size: 14px;
  color: #6b7280;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Metrics */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.metric-card {
  padding: 12px;
  border-radius: 8px;
}

.metric-card.bg-blue {
  background: #eff6ff;
}

.metric-card.bg-red {
  background: #fef2f2;
}

.metric-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.metric-header svg {
  width: 16px;
  height: 16px;
}

.metric-card.bg-blue .metric-header svg {
  color: #3b82f6;
}

.metric-card.bg-red .metric-header svg {
  color: #ef4444;
}

.metric-header span {
  font-size: 12px;
  color: #6b7280;
}

.metric-value {
  font-size: 18px;
  font-weight: 700;
}

.metric-value.positive {
  color: #16a34a;
}

.metric-value.negative {
  color: #dc2626;
}

/* Footer */
.card-footer {
  display: flex;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid #f3f4f6;
}

.footer-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.footer-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.footer-icon.bg-teal {
  background: #ccfbf1;
}

.footer-icon.bg-green {
  background: #dcfce7;
}

.footer-icon svg {
  width: 16px;
  height: 16px;
}

.footer-icon.bg-green svg {
  color: #16a34a;
}

.footer-dot {
  width: 12px;
  height: 12px;
  background: #14b8a6;
  border-radius: 50%;
}

.footer-label {
  font-size: 12px;
  color: #6b7280;
}

.footer-value {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}

.footer-value.risk {
  color: #16a34a;
}
</style>
