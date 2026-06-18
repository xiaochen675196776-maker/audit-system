<template>
  <button
    class="cmd-capsule"
    :class="{ disabled: !clickable }"
    :disabled="!clickable"
    @click="clickable && $emit('click')"
    type="button"
  >
    <span class="cmd-icon" :style="{ color: iconColor }">
      <el-icon :size="15"><component :is="icon" /></el-icon>
    </span>
    <span class="cmd-text">
      <span class="cmd-title">{{ title }}</span>
      <span class="cmd-desc">{{ description }}</span>
    </span>
    <span class="cmd-arrow" v-if="clickable">
      <el-icon :size="14"><Right /></el-icon>
    </span>
    <span v-if="badge" class="cmd-badge">{{ badge }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Right } from '@element-plus/icons-vue'

const props = defineProps<{
  icon: any
  iconColor?: string
  title: string
  description: string
  badge?: string
}>()

defineEmits<{
  click: []
}>()

const clickable = computed(() => !props.badge)
</script>

<style scoped>
/* ===== 操作入口按钮 ===== */
.cmd-capsule {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  width: 100%;
  padding: var(--spacing-3) var(--spacing-4);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  cursor: pointer;
  text-align: left;
  font-family: var(--font-family-base);
  font-size: var(--font-size-sm);
  transition: all var(--transition-fast);
  position: relative;
  color: var(--text-primary);
}

.cmd-capsule:hover:not(.disabled) {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
}

.cmd-capsule:active:not(.disabled) {
  transform: scale(0.98);
}

.cmd-capsule.disabled {
  cursor: default;
  opacity: 0.6;
}

.cmd-capsule:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

.cmd-icon {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: var(--color-gray-50);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.cmd-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.cmd-title {
  font-weight: var(--font-weight-medium);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.cmd-desc {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cmd-arrow {
  color: var(--text-placeholder);
  flex-shrink: 0;
  transition: transform var(--transition-fast);
}

.cmd-capsule:hover:not(.disabled) .cmd-arrow {
  transform: translateX(3px);
  color: var(--color-primary-500);
}

.cmd-badge {
  position: absolute;
  top: -6px;
  right: -4px;
  background: var(--color-warning-light);
  color: var(--color-warning-dark);
  font-size: 10px;
  padding: 1px 7px;
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-medium);
  white-space: nowrap;
}
</style>
