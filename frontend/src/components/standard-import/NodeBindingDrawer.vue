<template>
  <div class="node-binding-drawer">
    <div class="drawer-header">
      <strong>绑定原始行明细</strong>
      <span class="drawer-meta">
        node_key: <code>{{ nodeKey }}</code>
        · 绑定 {{ boundRows.length }} 条原始行
      </span>
      <el-tag
        v-if="boundRows.length > 1"
        type="warning"
        size="small"
        effect="plain"
      >
        多行绑定
      </el-tag>
    </div>

    <table class="binding-table">
      <thead>
        <tr>
          <th width="60">行号</th>
          <th width="100">代表行</th>
          <th width="120">客户科目代码</th>
          <th>客户科目名称</th>
          <th width="60">层级</th>
          <th width="100">是否末级</th>
          <th width="100">是否汇总</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="binding in boundRows"
          :key="binding.row_index"
          :class="{
            'is-representative': binding.is_representative,
          }"
        >
          <td class="row-index">#{{ binding.row_index + 1 }}</td>
          <td>
            <el-tag
              v-if="binding.is_representative"
              size="small"
              type="primary"
              effect="plain"
            >
              代表行
            </el-tag>
            <span v-else class="muted">—</span>
          </td>
          <td>
            <code v-if="rowDataFor(binding.row_index)?.client_account_code">
              {{ rowDataFor(binding.row_index)?.client_account_code }}
            </code>
            <span v-else class="muted">—</span>
          </td>
          <td>{{ rowDataFor(binding.row_index)?.client_account_name || '—' }}</td>
          <td>
            <span v-if="rowDataFor(binding.row_index)?.level !== null">
              L{{ rowDataFor(binding.row_index)?.level }}
            </span>
            <span v-else class="muted">—</span>
          </td>
          <td>
            <el-tag
              v-if="rowDataFor(binding.row_index)?.is_leaf"
              size="small"
              type="success"
              effect="plain"
            >末级</el-tag>
            <span v-else class="muted">—</span>
          </td>
          <td>
            <el-tag
              v-if="rowDataFor(binding.row_index)?.is_summary"
              size="small"
              type="warning"
              effect="plain"
            >汇总</el-tag>
            <span v-else class="muted">—</span>
          </td>
          <td>
            <span class="muted">只读</span>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="drawer-footer">
      <p class="muted">
        绑定原始行在 NodeKey 模式下只读，不可独立修改映射。如需拆分 NodeKey，请联系后端维护。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { RowNodeBinding } from '@/types'

interface Props {
  nodeKey: string
  boundRows: RowNodeBinding[]
  rowByIndex: Map<
    number,
    { row_index: number; client_account_code: string | null; client_account_name: string | null; level: number | null; is_leaf: boolean | null; is_summary: boolean | null }
  >
}

const props = defineProps<Props>()

function rowDataFor(idx: number) {
  return props.rowByIndex.get(idx) || null
}
</script>

<style scoped>
.node-binding-drawer {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
  padding: var(--spacing-2);
  background: var(--bg-card-soft);
  border-radius: 6px;
  border: 1px solid var(--border-light);
}

.drawer-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-sm);
}

.drawer-meta {
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
}

.drawer-meta code {
  font-family: var(--font-family-mono);
  background: var(--bg-card);
  padding: 0 4px;
  border-radius: 3px;
  margin: 0 4px;
}

.binding-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.binding-table th,
.binding-table td {
  padding: 6px 8px;
  text-align: left;
  border-bottom: 1px solid var(--border-light);
}

.binding-table th {
  background: var(--bg-card);
  font-weight: var(--font-weight-bold);
  color: var(--text-secondary);
}

.binding-table tr.is-representative {
  background: var(--color-primary-50);
}

.row-index {
  font-family: var(--font-family-mono);
  color: var(--text-secondary);
}

.muted {
  color: var(--text-secondary);
  font-style: italic;
}

.drawer-footer {
  font-size: var(--font-size-xs);
}
</style>
