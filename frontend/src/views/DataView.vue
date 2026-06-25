<template>
  <div class="data-view-page">
    <div class="page-header">
      <div class="header-left">
        <h2 class="header-title">数据查看</h2>
        <p class="header-desc">查看标准化导入后的科目余额表数据</p>
      </div>
    </div>

    <!-- 页签 -->
    <el-tabs v-model="activeTab" class="view-tabs">
      <el-tab-pane label="科目余额表" name="trial_balance" />
      <el-tab-pane label="序时账" name="journal" />
      <el-tab-pane label="辅助明细账" name="subsidiary" />
    </el-tabs>

    <!-- 科目余额表 -->
    <div v-if="activeTab === 'trial_balance'" class="tab-content">
      <!-- 筛选栏 -->
      <div class="filter-bar">
        <div class="filter-left">
          <el-select
            v-model="selectedBatchId"
            placeholder="选择导入批次"
            clearable
            style="width: 260px"
            @change="onBatchChange"
            :loading="batchesLoading"
          >
            <el-option
              v-for="b in batches"
              :key="b.id"
              :label="batchLabel(b)"
              :value="b.id"
            />
          </el-select>
          <el-select
            v-model="filterFiscalYear"
            placeholder="年度"
            clearable
            style="width: 120px"
            @change="onFilterChange"
          >
            <el-option
              v-for="y in availableYears"
              :key="y"
              :label="String(y)"
              :value="y"
            />
          </el-select>
          <el-select
            v-model="filterPeriod"
            placeholder="期间"
            clearable
            style="width: 100px"
            @change="onFilterChange"
          >
            <el-option
              v-for="p in 12"
              :key="p"
              :label="`${p}月`"
              :value="p"
            />
          </el-select>
        </div>
        <div class="filter-right">
          <el-switch
            v-model="onlyWithAmounts"
            active-text="只看有金额科目"
            @change="onFilterChange"
          />
          <span class="node-count" v-if="totalNodes > 0">
            共 {{ totalNodes }} 个节点
          </span>
          <el-popconfirm
            v-if="selectedBatchId"
            title="确认删除当前导入批次？删除后该批次的科目余额表数据不可在查询页查看。"
            confirm-button-text="删除"
            cancel-button-text="取消"
            confirm-button-type="danger"
            @confirm="deleteSelectedBatch"
          >
            <template #reference>
              <el-button type="danger" plain :loading="deleteLoading">
                删除当前导入数据
              </el-button>
            </template>
          </el-popconfirm>
        </div>
      </div>

      <!-- 空状态：未选批次 -->
      <div v-if="!selectedBatchId && batches.length === 0 && !batchesLoading" class="empty-state">
        <el-icon :size="48" color="var(--text-placeholder)"><DataAnalysis /></el-icon>
        <p class="empty-title">暂无导入批次</p>
        <p class="empty-desc">请先在数据导入中完成「科目余额表标准化导入」，再查看数据</p>
      </div>

      <!-- 树形表格 -->
      <div v-else-if="treeData.length > 0" class="tree-table-wrap">
        <el-table
          class="trial-balance-tree-table"
          :data="treeData"
          row-key="node_id"
          :tree-props="{ children: 'children', hasChildren: 'has_children' }"
          :default-expand-all="false"
          border
          stripe
          v-loading="treeLoading"
          size="small"
          :fit="false"
          style="width: 100%"
          :max-height="tableMaxHeight"
        >
          <el-table-column
            prop="account_code"
            label="科目代码"
            width="150"
            fixed="left"
          />
          <el-table-column
            prop="account_name"
            label="科目名称 / 客户明细"
            width="360"
            fixed="left"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <template v-if="row.node_type === 'entry'">
                <span class="name-inline entry-row-text" :title="customerTitle(row)">
                  <el-tag size="small" type="info" effect="plain">客户</el-tag>
                  <span class="single-line-text">{{ clientLabel(row) }}</span>
                </span>
              </template>
              <template v-else-if="row.node_type === 'client_group'">
                <span class="name-inline entry-row-text" :title="customerTitle(row)">
                  <el-tag size="small" type="warning" effect="plain">客户层级</el-tag>
                  <span class="single-line-text">{{ clientLabel(row) }}</span>
                </span>
              </template>
              <template v-else>
                <span class="single-line-text" :title="`${row.account_code || ''} ${row.account_name || ''}`">
                  {{ row.account_name }}
                </span>
              </template>
            </template>
          </el-table-column>
          <el-table-column
            label="标准科目"
            width="280"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <span v-if="row.node_type === 'entry'" class="standard-inline" :title="standardTitle(row)">
                {{ standardLabel(row) }}
              </span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="balance_direction" label="方向" width="70" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.balance_direction === 'debit'" size="small" type="success">借</el-tag>
              <el-tag v-else-if="row.balance_direction === 'credit'" size="small" type="danger">贷</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="期初借方余额" width="150" align="right">
            <template #default="{ row }">
              <span
                class="amount-cell"
                :class="{ 'zero-amount': !hasAmount(row.opening_debit) }"
              >
                {{ formatAmount(row.opening_debit) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="期初贷方余额" width="150" align="right">
            <template #default="{ row }">
              <span
                class="amount-cell"
                :class="{ 'zero-amount': !hasAmount(row.opening_credit) }"
              >
                {{ formatAmount(row.opening_credit) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="本期借方发生额" width="150" align="right">
            <template #default="{ row }">
              <span
                class="amount-cell"
                :class="{ 'zero-amount': !hasAmount(row.current_debit) }"
              >
                {{ formatAmount(row.current_debit) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="本期贷方发生额" width="150" align="right">
            <template #default="{ row }">
              <span
                class="amount-cell"
                :class="{ 'zero-amount': !hasAmount(row.current_credit) }"
              >
                {{ formatAmount(row.current_credit) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="期末借方余额" width="150" align="right">
            <template #default="{ row }">
              <span
                class="amount-cell"
                :class="{ 'zero-amount': !hasAmount(row.ending_debit) }"
              >
                {{ formatAmount(row.ending_debit) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="期末贷方余额" width="150" align="right">
            <template #default="{ row }">
              <span
                class="amount-cell"
                :class="{ 'zero-amount': !hasAmount(row.ending_credit) }"
              >
                {{ formatAmount(row.ending_credit) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="条目数" width="80" align="center">
            <template #default="{ row }">
              <span v-if="row.node_type === 'account'">{{ row.entry_count || '-' }}</span>
              <span v-else-if="row.node_type === 'client_group'">{{ row.entry_count || '-' }}</span>
              <span v-else class="entry-count-dot">明细</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 空状态：有筛选条件但无数据 -->
      <div v-else-if="!treeLoading && selectedBatchId" class="empty-state">
        <el-icon :size="48" color="var(--text-placeholder)"><FolderOpened /></el-icon>
        <p class="empty-title">暂无数据</p>
        <p class="empty-desc">当前筛选条件下没有科目余额表数据</p>
      </div>
    </div>

    <!-- 序时账占位 -->
    <div v-if="activeTab === 'journal'" class="tab-content">
      <div class="placeholder-view">
        <el-icon :size="56" color="var(--text-placeholder)"><Clock /></el-icon>
        <p class="placeholder-title">序时账</p>
        <p class="placeholder-desc">序时账数据查看功能正在开发中，后续版本接入</p>
      </div>
    </div>

    <!-- 辅助明细账占位 -->
    <div v-if="activeTab === 'subsidiary'" class="tab-content">
      <div class="placeholder-view">
        <el-icon :size="56" color="var(--text-placeholder)"><Grid /></el-icon>
        <p class="placeholder-title">辅助明细账</p>
        <p class="placeholder-desc">辅助明细账数据查看功能正在开发中，后续版本接入</p>
      </div>
    </div>

    </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  DataAnalysis,
  FolderOpened,
  Clock,
  Grid,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '@/api'
import { normalizeError } from '@/utils/error'
import type {
  ImportBatchItem,
  ImportBatchListResponse,
  TreeNode,
  TreeResponse,
} from '@/types'

// ===== 页签 =====
const activeTab = ref('trial_balance')

// ===== 批次 =====
const batches = ref<ImportBatchItem[]>([])
const batchesLoading = ref(false)
const selectedBatchId = ref<string | null>(null)

// ===== 筛选 =====
const filterFiscalYear = ref<number | null>(null)
const filterPeriod = ref<number | null>(null)
const onlyWithAmounts = ref(false)
const deleteLoading = ref(false)

// ===== 树 =====
const treeData = ref<TreeNode[]>([])
const treeLoading = ref(false)
const totalNodes = ref(0)

// ===== 表格高度 =====
const tableMaxHeight = computed(() => window.innerHeight - 380)

// ===== 可用年度（从批次列表提取） =====
const availableYears = computed(() => {
  const years = new Set<number>()
  for (const b of batches.value) {
    if (b.fiscal_year) years.add(b.fiscal_year)
  }
  return Array.from(years).sort((a, b) => b - a)
})

// ===== 方法 =====

function batchLabel(b: ImportBatchItem): string {
  const parts: string[] = []
  if (b.customer_label) parts.push(b.customer_label)
  parts.push(b.file_name)
  if (b.fiscal_year) parts.push(`${b.fiscal_year}年`)
  if (b.period) parts.push(`${b.period}月`)
  if (b.entry_count !== undefined) parts.push(`${b.entry_count}条`)
  return parts.join(' · ')
}

function clientLabel(row: TreeNode): string {
  if (row.node_type === 'client_group') {
    return `${row.client_account_code || row.account_code || ''} ${row.client_account_name || row.account_name || ''}`.trim()
  }
  const code = row.client_account_code || ''
  const name = row.client_account_name || ''
  return `${code} ${name}`.trim()
}

function standardLabel(row: TreeNode): string {
  const code = row.standard_account_code || row.account_code || ''
  const name = row.standard_account_name || row.account_name || ''
  return `${code} ${name}`.trim()
}

function customerTitle(row: TreeNode): string {
  return `客户：${clientLabel(row)}\n标准：${standardLabel(row)}`
}

function standardTitle(row: TreeNode): string {
  return `标准科目：${standardLabel(row)}`
}

function hasAmount(val: string | number | null | undefined): boolean {
  if (val === null || val === undefined) return false
  const n = typeof val === 'string' ? parseFloat(val) : val
  return n !== 0
}

function formatAmount(val: string | number | null | undefined): string {
  if (val === null || val === undefined) return '0.00'
  const n = typeof val === 'string' ? parseFloat(val) : val
  if (n === 0) return '0.00'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function fetchBatches() {
  batchesLoading.value = true
  try {
    const res = await api.get<ImportBatchListResponse>('/standard-trial-balances/batches')
    batches.value = res.data.items || []
    // 自动选中最新批次
    if (batches.value.length > 0 && !selectedBatchId.value) {
      selectedBatchId.value = batches.value[0].id
    }
  } catch (e) {
    console.error('获取批次列表失败', e)
    batches.value = []
  } finally {
    batchesLoading.value = false
  }
}

async function fetchTree() {
  if (!selectedBatchId.value) {
    treeData.value = []
    totalNodes.value = 0
    return
  }
  treeLoading.value = true
  try {
    const params: Record<string, any> = {
      batch_id: selectedBatchId.value,
      only_with_amounts: onlyWithAmounts.value,
    }
    if (filterFiscalYear.value) params.fiscal_year = filterFiscalYear.value
    if (filterPeriod.value) params.period = filterPeriod.value

    const res = await api.get<TreeResponse>('/standard-trial-balances/tree', { params })
    treeData.value = res.data.items || []
    totalNodes.value = res.data.total_nodes || 0
  } catch (e) {
    console.error('获取树形数据失败', e)
    treeData.value = []
    totalNodes.value = 0
  } finally {
    treeLoading.value = false
  }
}

async function deleteSelectedBatch() {
  if (!selectedBatchId.value) return
  deleteLoading.value = true
  try {
    await api.delete(`/standard-trial-balances/batches/${selectedBatchId.value}`)
    ElMessage.success('已删除当前导入数据')
    selectedBatchId.value = null
    treeData.value = []
    totalNodes.value = 0
    await fetchBatches()
    if (batches.value.length > 0) {
      selectedBatchId.value = batches.value[0].id
      await fetchTree()
    }
  } catch (e) {
    console.error('删除导入数据失败', e)
    ElMessage.error(normalizeError(e, '删除导入数据失败'))
  } finally {
    deleteLoading.value = false
  }
}

function onBatchChange() {
  filterFiscalYear.value = null
  filterPeriod.value = null
  fetchTree()
}

function onFilterChange() {
  fetchTree()
}

onMounted(() => {
  fetchBatches().then(() => {
    if (selectedBatchId.value) {
      fetchTree()
    }
  })
})
</script>

<style scoped>
.data-view-page {
  max-width: 100%;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--spacing-4);
}

.header-left {
  flex: 1;
}

.header-title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  margin: 0 0 4px;
}

.header-desc {
  font-size: var(--font-size-sm);
  color: var(--text-placeholder);
  margin: 0;
}

/* 页签 */
.view-tabs {
  margin-bottom: var(--spacing-4);
}

.view-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--spacing-3);
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-4);
}

.filter-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  flex-wrap: wrap;
}

.filter-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
}

.node-count {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px var(--spacing-4);
  text-align: center;
}

.empty-state.small {
  padding: 32px var(--spacing-4);
}

.empty-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
  margin: var(--spacing-4) 0 var(--spacing-1);
}

.empty-desc {
  font-size: var(--font-size-sm);
  color: var(--text-placeholder);
  margin: 0;
}

/* 占位视图 */
.placeholder-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px var(--spacing-4);
  text-align: center;
}

.placeholder-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-secondary);
  margin: var(--spacing-4) 0 var(--spacing-2);
}

.placeholder-desc {
  font-size: var(--font-size-md);
  color: var(--text-placeholder);
  margin: 0;
  line-height: 1.6;
}

/* 树形表格 */
.tree-table-wrap {
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.trial-balance-tree-table {
  width: 100%;
}

/* 不要给 .el-table__inner-wrapper 设 min-width，否则滚动容器被撑出可视区域，
   导致横向滚动条不可用。列宽由各 el-table-column width 属性决定，让 Element Plus
   自己在 100% 宽度的 el-scrollbar__wrap 内产生横向滚动。 */
.trial-balance-tree-table :deep(.el-scrollbar__wrap) {
  overflow-x: auto !important;
}

/* 冻结列单元格内容防止撑坏 */
.trial-balance-tree-table :deep(.el-table__fixed .cell) {
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 标准科目列 / 冻结列统一单行 */
.name-inline,
.standard-inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
}

.single-line-text {
  display: inline-block;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.entry-row-text {
  color: var(--text-secondary);
}

.muted {
  color: var(--text-placeholder);
}

.entry-count-dot {
  color: var(--text-placeholder);
  font-size: var(--font-size-xs);
}

/* 金额单元格 —— 大金额不省略，强制单行 */
.amount-cell {
  display: inline-block;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.tab-content {
  min-height: 400px;
}

/* 金额零值淡色 */
.zero-amount {
  color: var(--text-placeholder);
}
</style>
