<template>
  <div class="stat-card">
    <!-- Progress bar at bottom -->
    <div class="stat-progress">
      <div class="stat-progress-bar"></div>
    </div>
    
    <div class="stat-header">
      <div class="stat-info">
        <div class="stat-label">{{ label }}</div>
        <div class="stat-value-wrapper">
          <span class="stat-value">{{ value }}</span>
          <span v-if="percentage" class="stat-percentage">{{ percentage }}</span>
        </div>
        <div v-if="change" :class="['stat-change', changeType]">
          {{ change }}
        </div>
      </div>
      
      <div :class="['stat-icon', iconColor]">
        <component :is="getIcon(iconName)" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { defineProps } from 'vue';

defineProps({
  label: String,
  value: String,
  change: String,
  changeType: String,
  percentage: String,
  iconName: String,
  iconColor: String
});

const getIcon = (name) => {
  const icons = {
    'bar-chart': {
      template: `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 3v18h18"/>
          <path d="M18 17V9"/>
          <path d="M13 17V5"/>
          <path d="M8 17v-3"/>
        </svg>
      `
    },
    'trending-up': {
      template: `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/>
          <polyline points="17 6 23 6 23 12"/>
        </svg>
      `
    },
    'wallet': {
      template: `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/>
          <path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/>
          <path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>
        </svg>
      `
    }
  };
  return icons[name] || icons['bar-chart'];
};
</script>

<style scoped>
.stat-card {
  background: white;
  border-radius: 12px;
  padding: 20px;
  border: 1px solid #e5e7eb;
  position: relative;
  overflow: hidden;
}

.stat-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: #f3f4f6;
}

.stat-progress-bar {
  height: 100%;
  width: 60%;
  background: #3b82f6;
  transition: width 0.3s;
}

.stat-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
}

.stat-label {
  font-size: 14px;
  color: #6b7280;
  margin-bottom: 4px;
}

.stat-value-wrapper {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.stat-value {
  font-size: 30px;
  font-weight: 700;
  color: #111827;
}

.stat-percentage {
  font-size: 14px;
  color: #6b7280;
}

.stat-change {
  font-size: 14px;
  margin-top: 4px;
}

.stat-change.positive {
  color: #16a34a;
}

.stat-change.negative {
  color: #dc2626;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.stat-icon svg {
  width: 24px;
  height: 24px;
}

.stat-icon.bg-blue-500 {
  background: #3b82f6;
}

.stat-icon.bg-blue-400 {
  background: #60a5fa;
}
</style>
