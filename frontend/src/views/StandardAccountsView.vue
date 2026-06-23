<template>
  <div class="page">
    <PageHeader
      title="标准科目表查看"
      subtitle="系统内置全局统一标准科目，由系统维护人员初始化与同步"
      eyebrow="科目管理"
    />

    <!-- 顶部说明 -->
    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="page-notice"
    >
      <template #title>
        标准科目表为系统内置模板，由系统维护人员统一管理。普通用户无需、也不能上传标准科目模板。
      </template>
    </el-alert>

    <!-- 搜索 + 筛选工具栏 -->
    <div class="toolbar">
      <div class="toolbar-filters">
        <el-input
          v-model="keyword"
          placeholder="搜索科目代码或名称..."
          clearable
          class="toolbar-search"
          @input="handleSearchDebounced"
          @clear="handleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select
          v-model="statusFilter"
          placeholder="全部状态"
          class="toolbar-select"
          clearable
          @change="handleSearch"
        >
          <el-option label="全部状态" value="" />
          <el-option label="启用" value="active" />
          <el-option label="停用" value="inactive" />
        </el-select>
        <el-select
          v-model="categoryFilter"
          placeholder="全部类别"
          class="toolbar-select"
          clearable
          @change="handleSearch"
        >
          <el-option label="全部类别" value="" />
          <el-option
            v-for="cat in categoryOptions"
            :key="cat.value"
            :label="cat.label"
            :value="cat.value"
          />
        </el-select>
        <el-select
          v-model="directionFilter"
          placeholder="全部方向"
          class="toolbar-select"
          clearable
          @change="handleSearch"
        >
          <el-option label="全部方向" value="" />
          <el-option label="借方" value="debit" />
          <el-option label="贷方" value="credit" />
        </el-select>
      </div>
      <div class="toolbar-right">
        <span v-if="total > 0" class="toolbar-count">共 {{ total }} 条</span>
      </div>
    </div>

    <!-- 表格 / 空状态 -->
    <div class="table-card">
      <div v-if="!loading && accounts.length === 0" class="standalone-empty">
        <el-empty
          :description="keyword || statusFilter || categoryFilter || directionFilter ? '没有符合筛选条件的科目' : '系统内置标准科目未初始化，请联系系统维护人员'"
          :image-size="120"
        >
          <el-button v-if="keyword || statusFilter || categoryFilter || directionFilter" @click="clearFilters">清除筛选</el-button>
        </el-empty>
      </div>

      <el-table
        v-else
        :data="pagedAccounts"
        v-loading="loading"
        stripe
        class="data-table"
        :header-cell-style="headerCellStyle"
        row-key="id"
      >
        <template #empty>
          <div class="empty-state">
            <el-empty
              description="没有符合筛选条件的科目"
              :image-size="120"
            >
              <el-button @click="clearFilters">清除筛选</el-button>
            </el-empty>
          </div>
        </template>

        <el-table-column prop="account_code" label="科目代码" width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <code class="cell-code">{{ row.account_code }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="account_name" label="科目名称" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="cell-name">{{ row.account_name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="account_category" label="科目类别" width="110" align="center">
          <template #default="{ row }">
            <span :class="{ 'cell-muted': !row.account_category }">
              {{ row.account_category ? categoryLabel(row.account_category) : '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="balance_direction" label="余额方向" width="90" align="center">
          <template #default="{ row }">
            <span :class="{ 'cell-muted': !row.balance_direction }">
              {{ row.balance_direction === 'debit' ? '借方' : row.balance_direction === 'credit' ? '贷方' : '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="level" label="层级" width="70" align="center">
          <template #default="{ row }">
            <span :class="{ 'cell-muted': row.level == null }">{{ row.level ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="is_leaf" label="末级" width="70" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_leaf ? '' : 'info'" size="small" effect="plain">
              {{ row.is_leaf ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="80" align="center">
          <template #default="{ row }">
            <span class="status-dot" :class="row.is_active ? 'status-dot--active' : 'status-dot--inactive'" />
            {{ row.is_active ? '启用' : '停用' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="150" align="center">
          <template #default="{ row }">
            <span class="cell-muted cell-time">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 分页 -->
    <div class="pagination-wrapper">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        background
        size="default"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import api from '@/api'
import { normalizeError } from '@/utils/error'
import type { StandardAccount } from '@/types'

// ===== 数据 =====
const accounts = ref<StandardAccount[]>([])
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const categoryFilter = ref('')
const directionFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(50)

// ===== 类别中文映射 =====
const categoryMap: Record<string, string> = {
  asset: '资产',
  liability: '负债',
  equity: '权益',
  revenue: '收入',
  expense: '费用',
  profit_loss: '损益',
}

function categoryLabel(value: string): string {
  return categoryMap[value] || value
}

// 类别选项（固定枚举）
const categoryOptions = [
  { value: 'asset', label: '资产' },
  { value: 'liability', label: '负债' },
  { value: 'equity', label: '权益' },
  { value: 'revenue', label: '收入' },
  { value: 'expense', label: '费用' },
  { value: 'profit_loss', label: '损益' },
]

// ===== 防抖搜索 =====
let debounceTimer: ReturnType<typeof setTimeout> | null = null
function handleSearchDebounced() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => handleSearch(), 300)
}

// ===== 客户端筛选 =====
const filteredAccounts = computed(() => {
  let list = accounts.value

  if (keyword.value.trim()) {
    const kw = keyword.value.trim().toLowerCase()
    list = list.filter(
      (a) =>
        a.account_code.toLowerCase().includes(kw) ||
        a.account_name.toLowerCase().includes(kw)
    )
  }

  if (statusFilter.value === 'active') {
    list = list.filter((a) => a.is_active)
  } else if (statusFilter.value === 'inactive') {
    list = list.filter((a) => !a.is_active)
  }

  if (categoryFilter.value) {
    list = list.filter((a) => a.account_category === categoryFilter.value)
  }

  if (directionFilter.value) {
    list = list.filter((a) => a.balance_direction === directionFilter.value)
  }

  return list
})

const pagedAccounts = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredAccounts.value.slice(start, start + pageSize.value)
})

const total = computed(() => filteredAccounts.value.length)

// ===== 表格样式 =====
const headerCellStyle = {
  background: '#f7f8fa',
  color: '#3d4148',
  fontWeight: '600' as const,
  fontSize: '13px',
  borderBottom: '2px solid #e4e7ec',
}

function formatDate(iso?: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  } catch {
    return iso.slice(0, 10)
  }
}

function handleSearch() {
  currentPage.value = 1
}

function clearFilters() {
  keyword.value = ''
  statusFilter.value = ''
  categoryFilter.value = ''
  directionFilter.value = ''
  currentPage.value = 1
}

// ===== 数据获取 =====
async function fetchAccounts() {
  loading.value = true
  try {
    const { data } = await api.get('/standard-accounts', {
      params: { is_active: undefined },
    })
    accounts.value = data.items ?? []
  } catch (e: any) {
    ElMessage.error(normalizeError(e, '获取标准科目列表失败'))
    accounts.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchAccounts()
})
</script>

<style scoped>
.page {
  max-width: var(--content-max-width);
  margin: 0 auto;
}

/* ===== 页面说明 ===== */
.page-notice {
  margin-bottom: var(--spacing-4);
}

/* ===== 工具栏 ===== */
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-4);
}

.toolbar-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--spacing-2);
}

.toolbar-search {
  width: 240px;
}

.toolbar-select {
  width: 120px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  margin-left: auto;
}

.toolbar-count {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}

/* ===== 表格 ===== */
.table-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.data-table {
  width: 100%;
  --el-table-border-color: var(--border-lighter);
}

.data-table :deep(.el-table__header th) {
  height: 42px;
}

.data-table :deep(.el-table__body td) {
  height: 42px;
  color: var(--text-regular);
}

.cell-code {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-sm);
  color: var(--color-primary-600);
  background: rgba(59, 110, 165, 0.06);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
}

.cell-name {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.cell-muted {
  color: var(--text-placeholder);
}

.cell-time {
  font-size: var(--font-size-sm);
  font-variant-numeric: tabular-nums;
}

/* 状态指示 */
.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 5px;
  vertical-align: middle;
  position: relative;
  top: -1px;
}

.status-dot--active {
  background: var(--color-success);
}

.status-dot--inactive {
  background: var(--color-gray-400);
}

/* 空状态 */
.empty-state {
  padding: var(--spacing-10) 0;
}

.standalone-empty {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 320px;
  padding: var(--spacing-6);
}

/* ===== 分页 ===== */
.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--spacing-4);
}

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-filters {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-search,
  .toolbar-select {
    width: 100%;
  }

  .toolbar-right {
    margin-left: 0;
    justify-content: flex-start;
  }
}

@media (max-width: 480px) {
  .table-card {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .data-table {
    min-width: 800px;
  }

  .standalone-empty {
    min-height: 240px;
    padding: var(--spacing-4);
  }

  .standalone-empty :deep(.el-empty__description) {
    max-width: calc(100vw - var(--spacing-10));
    white-space: normal;
    word-break: break-word;
  }

  .pagination-wrapper :deep(.el-pagination) {
    justify-content: center;
  }
}
</style>
