<template>
  <div class="metric-card">
    <div class="metric-body">
      <div class="metric-icon" :style="{ color: iconColor }">
        <el-icon :size="18"><component :is="icon" /></el-icon>
      </div>
      <div class="metric-info">
        <span class="metric-value">{{ formattedValue }}</span>
        <span class="metric-label">{{ label }}</span>
      </div>
    </div>
    <div v-if="trend !== undefined" class="metric-trend" :class="trend >= 0 ? 'up' : 'down'">
      <el-icon :size="12"><component :is="trend >= 0 ? Top : Bottom" /></el-icon>
      <span>{{ Math.abs(trend) }}%</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Top, Bottom } from '@element-plus/icons-vue'

const props = defineProps<{
  icon: any
  iconColor?: string
  value: number | string
  label: string
  trend?: number
  format?: 'number' | 'text'
}>()

const formattedValue = computed(() => {
  if (props.format === 'text') return props.value
  const num = typeof props.value === 'string' ? parseInt(props.value, 10) : props.value
  if (isNaN(num)) return '0'
  if (num >= 10000) {
    return (num / 10000).toFixed(1) + 'w'
  }
  return num.toLocaleString()
})
</script>

<style scoped>
/* ===== 紧凑指标卡 ===== */
.metric-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-4) var(--spacing-5);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  min-height: 64px;
}

.metric-body {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  min-width: 0;
}

.metric-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: var(--color-gray-50);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.metric-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.metric-value {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  line-height: var(--line-height-tight);
  font-variant-numeric: tabular-nums;
}

.metric-label {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  white-space: nowrap;
}

/* ===== 趋势 ===== */
.metric-trend {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  flex-shrink: 0;
}

.metric-trend.up {
  color: var(--color-success);
}

.metric-trend.down {
  color: var(--color-danger);
}
</style>
