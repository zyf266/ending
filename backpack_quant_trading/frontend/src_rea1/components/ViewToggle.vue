<template>
  <div class="view-toggle-container">
    <!-- Tabs -->
    <button
      v-for="tab in tabs"
      :key="tab.id"
      :class="['style-tab', { active: tab.active, yellow: tab.color === 'yellow' }]"
    >
      <svg v-if="tab.active" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 2a1 1 0 0 1 1 1v4h4a1 1 0 1 1 0 2H9v4a1 1 0 1 1-2 0V9H3a1 1 0 0 1 0-2h4V3a1 1 0 0 1 1-1z"/>
      </svg>
      <span>{{ tab.label }}</span>
    </button>

    <!-- View Mode Toggle -->
    <div class="view-mode-toggle">
      <button
        :class="['view-btn', { active: modelValue === 'grid' }]"
        @click="$emit('update:viewMode', 'grid')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="7"/>
          <rect x="14" y="3" width="7" height="7"/>
          <rect x="14" y="14" width="7" height="7"/>
          <rect x="3" y="14" width="7" height="7"/>
        </svg>
      </button>
      <button
        :class="['view-btn', { active: modelValue === 'list' }]"
        @click="$emit('update:viewMode', 'list')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="8" y1="6" x2="21" y2="6"/>
          <line x1="8" y1="12" x2="21" y2="12"/>
          <line x1="8" y1="18" x2="21" y2="18"/>
          <line x1="3" y1="6" x2="3.01" y2="6"/>
          <line x1="3" y1="12" x2="3.01" y2="12"/>
          <line x1="3" y1="18" x2="3.01" y2="18"/>
        </svg>
      </button>
    </div>

    <!-- Add Button -->
    <button class="add-btn">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="12" y1="5" x2="12" y2="19"/>
        <line x1="5" y1="12" x2="19" y2="12"/>
      </svg>
      <span>新建策略</span>
    </button>
  </div>
</template>

<script setup>
import { ref, defineProps, defineEmits } from 'vue';

defineProps({
  modelValue: {
    type: String,
    default: 'grid'
  }
});

defineEmits(['update:viewMode']);

const tabs = ref([
  { id: 'tab1', label: '风格一', active: true },
  { id: 'tab2', label: '风格二', active: false },
  { id: 'tab3', label: '风格三', active: false, color: 'yellow' },
  { id: 'tab4', label: '风格四', active: false }
]);
</script>

<style scoped>
.view-toggle-container {
  display: flex;
  align-items: center;
  gap: 8px;
}

.style-tab {
  padding: 10px 16px;
  border-radius: 8px;
  border: none;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f3f4f6;
  color: #6b7280;
}

.style-tab.active {
  background: #3b82f6;
  color: white;
}

.style-tab.yellow {
  background: #fef3c7;
  color: #d97706;
}

.style-tab.yellow:hover {
  background: #fde68a;
}

.style-tab:hover:not(.active):not(.yellow) {
  background: #e5e7eb;
}

.style-tab svg {
  width: 16px;
  height: 16px;
}

.view-mode-toggle {
  display: flex;
  gap: 4px;
  background: #f3f4f6;
  padding: 4px;
  border-radius: 8px;
  margin-left: 8px;
}

.view-btn {
  padding: 8px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  color: #6b7280;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.view-btn svg {
  width: 16px;
  height: 16px;
}

.view-btn.active {
  background: #3b82f6;
  color: white;
}

.view-btn:hover:not(.active) {
  background: #e5e7eb;
}

.add-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.add-btn:hover {
  background: #2563eb;
}

.add-btn svg {
  width: 16px;
  height: 16px;
}
</style>
