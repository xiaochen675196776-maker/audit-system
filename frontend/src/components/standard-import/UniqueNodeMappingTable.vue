<template>
  <div class="unique-node-mapping-table" :class="{ 'has-conflicts': conflicts.length > 0 }">
    <!-- 冲突提示条：旧行级模式下，同 node_key 不同目标必须显示 -->
    <el-alert
      v-if="conflicts.length > 0"
      type="error"
      :closable="false"
      show-icon
      class="unique-node-conflict-alert"
    >
      <template #title>
        检测到 {{ conflicts.length }} 个 NodeKey 存在冲突选择（同一节点被映射到不同标准科目），已阻止确认与执行。
      </template>
      <ul class="unique-node-conflict-list">
        <li v-for="conflict in conflicts" :key="conflict.node_key">
          <code class="conflict-node-key">{{ conflict.node_key }}</code>
          涉及行：
          <span
            v-for="sel in conflict.conflicting_selections"
            :key="sel.row_index"
            class="conflict-row"
          >
            #{{ sel.row_index + 1 }} → {{ sel.standard_account_code }} {{ sel.standard_account_name }}
            <span v-if="sel.client_account_code || sel.client_account_name" class="conflict-client">
              （{{ sel.client_account_code || '?' }} {{ sel.client_account_name || '?' }}）
            </span>
          </span>
        </li>
      </ul>
    </el-alert>

    <!-- 节点概览统计条 -->
    <div class="unique-node-summary">
      <div class="unique-node-summary-item">
        <div class="unique-node-summary-value">{{ stats.total_node_count }}</div>
        <div class="unique-node-summary-label">唯一节点</div>
      </div>
      <div class="unique-node-summary-item">
        <div class="unique-node-summary-value">{{ stats.bound_raw_row_count }}</div>
        <div class="unique-node-summary-label">绑定原始行</div>
      </div>
      <div class="unique-node-summary-item success">
        <div class="unique-node-summary-value">{{ stats.mapped_count }}</div>
        <div class="unique-node-summary-label">已映射</div>
      </div>
      <div class="unique-node-summary-item danger">
        <div class="unique-node-summary-value">{{ stats.unmapped_count }}</div>
        <div class="unique-node-summary-label">未映射</div>
      </div>
      <div class="unique-node-summary-item warning">
        <div class="unique-node-summary-value">{{ stats.warning_count }}</div>
        <div class="unique-node-summary-label">有警告</div>
      </div>
      <div class="unique-node-summary-item info">
        <div class="unique-node-summary-value">{{ stats.explicit_override_count }}</div>
        <div class="unique-node-summary-label">显式覆盖</div>
      </div>
      <div class="unique-node-summary-item emphasis">
        <div class="unique-node-summary-value">{{ stats.anchor_pending_count }}</div>
        <div class="unique-node-summary-label">待确认锚点</div>
      </div>
    </div>

    <!-- 主表：row-key 必须是 node_key，绝不允许 row_index -->
    <el-table
      :data="filteredRows"
      :row-key="rowKey"
      :default-expand-all="false"
      :tree-props="{ children: 'bound_rows_inline' }"
      stripe
      size="small"
      max-height="560"
      :expand-row-keys="expandedKeys"
      @expand-change="onExpandChange"
      class="unique-node-table"
    >
      <el-table-column type="expand" width="48">
        <template #default="{ row }">
          <NodeBindingDrawer
            :node-key="row.node_key"
            :bound-rows="getBoundRowsForNode(row)"
            :row-by-index="rowByIndex"
          />
        </template>
      </el-table-column>

      <el-table-column label="客户科目代码" width="130" fixed="left">
        <template #default="{ row }">
          <code class="unique-node-code">{{ row.account_code || '—' }}</code>
        </template>
      </el-table-column>
      <el-table-column label="客户科目名称" width="180" fixed="left">
        <template #default="{ row }">{{ row.account_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="完整路径" min-width="220">
        <template #default="{ row }">
          <span class="unique-node-path">{{ row.full_path || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="节点类型" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="nodeTypeTagType(row.node_type)" effect="plain">
            {{ nodeTypeLabel(row.node_type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="映射角色" width="120" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="roleTagType(roleOf(row))">
            {{ roleLabel(roleOf(row)) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="绑定原始行" width="110" align="center">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="row.source_row_count > 1 ? 'warning' : 'info'"
            effect="plain"
          >
            {{ row.source_row_count }} 行
          </el-tag>
          <div v-if="row.source_row_count > 1" class="unique-node-dup-hint">展开查看明细</div>
        </template>
      </el-table-column>
      <el-table-column label="匹配状态" width="140" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="displayOf(row).type">
            {{ displayOf(row).label }}
          </el-tag>
          <div
            v-if="warningCountFor(row) > 0"
            class="unique-node-warning-count"
          >
            {{ warningCountFor(row) }} 条警告
          </div>
        </template>
      </el-table-column>
      <el-table-column label="当前标准科目" min-width="280">
        <template #default="{ row }">
          <template v-if="row.is_ignored">
            <div class="unique-node-current ignored">节点已忽略（绑定行全忽略时）</div>
          </template>
          <template v-else-if="row.node_type === 'summary' || roleOf(row) === 'structural_summary'">
            <div class="unique-node-current muted">结构汇总节点，不参与映射</div>
          </template>
          <template v-else-if="roleOf(row) === 'inherited' && !row.selected_candidate && !row.explicit_override">
            <div class="unique-node-current inherited">
              <div v-if="row.resolved_standard_account_code">
                <code>{{ row.resolved_standard_account_code }}</code>
                <span>{{ row.resolved_standard_account_name }}</span>
              </div>
              <div class="unique-node-inherit-meta">自动继承，无需逐行确认</div>
            </div>
          </template>
          <template v-else-if="row.selected_candidate">
            <div class="unique-node-current">
              <div>
                <code>{{ row.selected_candidate.standard_account_code }}</code>
                <span>{{ row.selected_candidate.standard_account_name }}</span>
              </div>
              <div class="unique-node-current-meta">
                来源：{{ row.selected_candidate.source }} · 置信度 {{ formatScore(row.selected_candidate.score) }}
              </div>
              <div
                v-if="roleOf(row) === 'explicit_override'"
                class="unique-node-inherit-meta"
              >
                显式覆盖继承（手动指定）
              </div>
            </div>
          </template>
          <template v-else>
              <div class="unique-node-current unmapped">
              <div>未匹配</div>
              <span v-if="(row.candidates || []).length">推荐候选：{{ (row.candidates || []).length }} 个</span>
              <span v-else-if="row.suggested_standard_account_code">
                自动解析：{{ row.suggested_standard_account_code }}
              </span>
            </div>
          </template>
        </template>
      </el-table-column>
      <el-table-column label="匹配操作" width="320" align="center" fixed="right">
        <template #default="{ row }">
          <div class="unique-node-actions">
            <template v-if="row.is_ignored">
              <span class="unique-node-muted">—</span>
            </template>
            <template v-else-if="row.node_type === 'summary' || roleOf(row) === 'structural_summary'">
              <span class="unique-node-muted">结构汇总</span>
            </template>
            <template v-else-if="roleOf(row) === 'inherited' && !row.selected_candidate && !row.explicit_override">
              <el-button size="small" type="primary" plain @click="onSetOverride(row)">单独映射</el-button>
            </template>
            <template v-else-if="roleOf(row) === 'explicit_override' && row.selected_candidate">
              <el-button size="small" @click="onRestoreInheritance(row)">恢复继承</el-button>
              <el-button size="small" type="primary" plain @click="onOpenPicker(row)">更换</el-button>
            </template>
            <template v-else-if="requiresMapping(row)">
              <el-button
                size="small"
                type="primary"
                :plain="!row.selected_candidate"
                @click="onOpenPicker(row)"
              >
                {{ row.selected_candidate ? '更换' : '选择' }}
              </el-button>
              <el-button
                v-if="row.selected_candidate"
                size="small"
                type="danger"
                text
                @click="onClear(row)"
              >
                清除
              </el-button>
            </template>
            <template v-else>
              <span class="unique-node-muted">无需操作</span>
            </template>
          </div>
          <el-popover
            v-if="pickerNodeKey === row.node_key"
            placement="left-start"
            trigger="manual"
            :model-value="true"
            width="360"
          >
            <template #reference>
              <span class="picker-anchor" />
            </template>
            <div class="unique-node-picker">
              <div class="picker-title">推荐候选</div>
              <div v-if="(row.candidates || []).length" class="candidate-list">
                <button
                  v-for="c in (row.candidates || []).slice(0, 6)"
                  :key="c.standard_account_id"
                  type="button"
                  class="candidate-option"
                  :class="{
                    selected: row.selected_candidate?.standard_account_id === c.standard_account_id,
                    warning: !!c.warning,
                  }"
                  @click="onSelectCandidate(row, c)"
                >
                  <span>
                    <code>{{ c.standard_account_code }}</code>
                    {{ c.standard_account_name }}
                  </span>
                  <span class="candidate-meta">
                    {{ c.source }} · {{ formatScore(c.score) }}
                  </span>
                  <span v-if="c.warning" class="candidate-warning">{{ c.warning }}</span>
                </button>
              </div>
              <div v-else class="picker-empty">暂无推荐候选，请搜索标准科目。</div>
              <div class="picker-search">
                <el-input
                  :model-value="searchQueries[row.node_key] || ''"
                  size="small"
                  placeholder="搜索标准科目代码或名称"
                  clearable
                  @update:model-value="onSearchInput(row, $event)"
                />
                <div
                  v-if="searchResults[row.node_key]?.length"
                  class="search-result-list"
                >
                  <button
                    v-for="sr in searchResults[row.node_key].slice(0, 8)"
                    :key="sr.id"
                    type="button"
                    class="search-result-item"
                    :class="{ disabled: !sr.is_active }"
                    @click="onSelectSearched(row, sr)"
                  >
                    <span>{{ sr.account_code }} {{ sr.account_name }}</span>
                    <el-tag v-if="!sr.is_active" size="small" type="danger">停用</el-tag>
                  </button>
                </div>
              </div>
            </div>
          </el-popover>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="filteredRows.length === 0" class="unique-node-empty">
      当前筛选下没有唯一节点。
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import NodeBindingDrawer from './NodeBindingDrawer.vue'
import type {
  MappingCandidate,
  NodeSelectionConflict,
  RowNodeBinding,
  StdAnalyzeResponse,
  UniqueNodeReviewRow,
} from '@/types'
import type { NodeMappingStats, NodeDisplayInfo } from '@/composables/useUniqueNodeMapping'

interface Props {
  rows: UniqueNodeReviewRow[]
  stats: NodeMappingStats
  conflicts: NodeSelectionConflict[]
  expandedKeys: string[]
  searchQueries: Record<string, string>
  searchResults: Record<string, any[]>
  rowByIndex: Map<
    number,
    { row_index: number; client_account_code: string | null; client_account_name: string | null; level: number | null; is_leaf: boolean | null; is_summary: boolean | null }
  >
  /** 角色 / 状态判定函数（由 composable 传入） */
  roleOf: (node: UniqueNodeReviewRow) => string
  displayOf: (node: UniqueNodeReviewRow) => NodeDisplayInfo
  requiresMapping: (node: UniqueNodeReviewRow) => boolean
  warningCountFor: (node: UniqueNodeReviewRow) => number
  /** 绑定原始行索引（由 composable 传入的 Map<nodeKey, RowNodeBinding[]>） */
  getBoundRowIndexes: (node: UniqueNodeReviewRow) => RowNodeBinding[]
  /** 过滤模式（all / unmapped / mapped / warning） */
  filterMode: 'all' | 'unmapped' | 'mapped' | 'warning'
  /** 事件 */
  onSelectCandidate: (node: UniqueNodeReviewRow, candidate: MappingCandidate) => void
  onSelectSearched: (node: UniqueNodeReviewRow, sa: any) => void
  onClear: (node: UniqueNodeReviewRow) => void
  onSetOverride: (node: UniqueNodeReviewRow) => void
  onRestoreInheritance: (node: UniqueNodeReviewRow) => void
  onSearchInput: (node: UniqueNodeReviewRow, keyword: string) => void
  onToggleExpand: (node: UniqueNodeReviewRow) => void
  /** 当前打开 picker 的 node_key（仅一个） */
  pickerNodeKey: string | null
  onOpenPicker: (node: UniqueNodeReviewRow) => void
}

const props = defineProps<Props>()

const filteredRows = computed<UniqueNodeReviewRow[]>(() => {
  switch (props.filterMode) {
    case 'unmapped':
      return props.rows.filter((r) => props.requiresMapping(r) && !r.selected_candidate)
    case 'mapped':
      return props.rows.filter((r) => props.requiresMapping(r) && !!r.selected_candidate)
    case 'warning':
      return props.rows.filter((r) => props.warningCountFor(r) > 0)
    default:
      return props.rows
  }
})

function rowKey(row: UniqueNodeReviewRow): string {
  return row.node_key
}

function getBoundRowsForNode(node: UniqueNodeReviewRow) {
  return props.getBoundRowIndexes(node)
}

function onExpandChange(_row: UniqueNodeReviewRow, expandedRows: UniqueNodeReviewRow[]) {
  // 单选展开：保留最后一个展开的 node_key
  const last = expandedRows[expandedRows.length - 1]
  if (last) {
    if (!props.expandedKeys.includes(last.node_key)) {
      props.onToggleExpand(last)
    }
  } else {
    // 全部收起
    if (props.expandedKeys.length > 0) {
      props.onToggleExpand(props.rows.find((r) => r.node_key === props.expandedKeys[0])!)
    }
  }
}

function nodeTypeLabel(t: string): string {
  const map: Record<string, string> = {
    account: '科目',
    auxiliary: '辅助',
    summary: '汇总',
  }
  return map[t] || t
}

function nodeTypeTagType(t: string): '' | 'success' | 'warning' | 'info' | 'danger' | 'primary' {
  const map: Record<string, '' | 'success' | 'warning' | 'info' | 'danger' | 'primary'> = {
    account: 'success',
    auxiliary: 'info',
    summary: 'warning',
  }
  return map[t] || 'info'
}

function roleLabel(role: string): string {
  const map: Record<string, string> = {
    anchor: '映射锚点',
    inherited: '自动继承',
    breakpoint: '继承中断点',
    explicit_override: '显式覆盖',
    structural_summary: '结构汇总',
    unresolved: '未解决',
    ignored: '已忽略',
  }
  return map[role] || role
}

function roleTagType(role: string): '' | 'success' | 'warning' | 'info' | 'danger' | 'primary' {
  const map: Record<string, '' | 'success' | 'warning' | 'info' | 'danger' | 'primary'> = {
    anchor: 'primary',
    inherited: 'success',
    breakpoint: 'warning',
    explicit_override: 'info',
    structural_summary: 'info',
    unresolved: 'danger',
    ignored: 'info',
  }
  return map[role] || ''
}

function formatScore(s: number | undefined): string {
  if (s === undefined || s === null) return '—'
  return s.toFixed(2)
}
</script>

<style scoped>
.unique-node-mapping-table {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

.unique-node-conflict-alert {
  margin-bottom: var(--spacing-2);
}

.unique-node-conflict-list {
  margin: var(--spacing-1) 0 0 0;
  padding-left: var(--spacing-3);
  font-size: var(--font-size-sm);
}

.conflict-node-key {
  font-family: var(--font-family-mono);
  background: var(--bg-card);
  padding: 0 4px;
  border-radius: 3px;
  margin-right: var(--spacing-1);
}

.conflict-row {
  display: inline-block;
  margin-right: var(--spacing-2);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
}

.conflict-client {
  color: var(--text-secondary);
  font-family: var(--font-family-base);
}

.unique-node-summary {
  display: flex;
  gap: var(--spacing-3);
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--bg-card-soft);
  border-radius: 6px;
  border: 1px solid var(--border-light);
}

.unique-node-summary-item {
  flex: 1;
  text-align: center;
}

.unique-node-summary-item .unique-node-summary-value {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
}

.unique-node-summary-item .unique-node-summary-label {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  margin-top: 2px;
}

.unique-node-summary-item.success .unique-node-summary-value {
  color: var(--color-success);
}
.unique-node-summary-item.danger .unique-node-summary-value {
  color: var(--color-danger);
}
.unique-node-summary-item.warning .unique-node-summary-value {
  color: var(--color-warning);
}
.unique-node-summary-item.info .unique-node-summary-value {
  color: var(--color-info);
}
.unique-node-summary-item.emphasis .unique-node-summary-value {
  color: var(--color-primary);
}

.unique-node-table {
  margin-top: var(--spacing-1);
}

.unique-node-code {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-sm);
}

.unique-node-path {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.unique-node-dup-hint {
  font-size: var(--font-size-xs);
  color: var(--color-warning);
  margin-top: 2px;
}

.unique-node-warning-count {
  font-size: var(--font-size-xs);
  color: var(--color-warning);
  margin-top: 2px;
}

.unique-node-current {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--font-size-sm);
}

.unique-node-current code {
  font-family: var(--font-family-mono);
  margin-right: 4px;
}

.unique-node-current.ignored,
.unique-node-current.muted {
  color: var(--text-secondary);
  font-style: italic;
}

.unique-node-current.inherited {
  color: var(--color-success);
}

.unique-node-current.unmapped {
  color: var(--color-danger);
}

.unique-node-current-meta {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.unique-node-inherit-meta {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.unique-node-actions {
  display: flex;
  gap: 4px;
  align-items: center;
  flex-wrap: wrap;
}

.unique-node-muted {
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
}

.picker-anchor {
  display: none;
}

.unique-node-picker {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

.picker-title {
  font-weight: var(--font-weight-bold);
  font-size: var(--font-size-sm);
}

.candidate-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 240px;
  overflow-y: auto;
}

.candidate-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: left;
  padding: 6px 8px;
  border: 1px solid var(--border-light);
  border-radius: 4px;
  background: var(--bg-card);
  cursor: pointer;
  font-size: var(--font-size-sm);
}

.candidate-option:hover {
  border-color: var(--color-primary);
}

.candidate-option.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-50);
}

.candidate-option.warning {
  border-color: var(--color-warning);
}

.candidate-meta {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.candidate-warning {
  font-size: var(--font-size-xs);
  color: var(--color-warning);
}

.picker-empty {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  font-style: italic;
}

.picker-search {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.search-result-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 180px;
  overflow-y: auto;
}

.search-result-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  border: 1px solid var(--border-light);
  border-radius: 3px;
  background: var(--bg-card);
  cursor: pointer;
  font-size: var(--font-size-sm);
}

.search-result-item:hover {
  border-color: var(--color-primary);
}

.search-result-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.unique-node-empty {
  padding: var(--spacing-3);
  text-align: center;
  color: var(--text-secondary);
  font-style: italic;
}
</style>
