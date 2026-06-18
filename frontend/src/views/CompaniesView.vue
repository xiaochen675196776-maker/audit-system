<template>
  <div class="page">
    <PageHeader
      title="被审计单位管理"
      subtitle="管理审计范围内的所有单位主体信息"
      eyebrow="单位管理"
    />

    <!-- 顶部工具栏：搜索 + 筛选 + 新建 -->
    <div class="toolbar">
      <div class="toolbar-filters">
        <el-input
          v-model="keyword"
          placeholder="搜索单位名称或编码..."
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
          <el-option label="正常" value="active" />
          <el-option label="停用" value="inactive" />
        </el-select>
        <el-select
          v-model="industryFilter"
          placeholder="全部行业"
          class="toolbar-select"
          clearable
          filterable
          @change="handleSearch"
        >
          <el-option label="全部行业" value="" />
          <el-option
            v-for="ind in industryOptions"
            :key="ind"
            :label="ind"
            :value="ind"
          />
        </el-select>
      </div>
      <div class="toolbar-right">
        <span v-if="total > 0" class="toolbar-count">共 {{ total }} 条</span>
        <el-button type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon>
          新建单位
        </el-button>
      </div>
    </div>

    <!-- 表格（有数据时） / 独立空状态（无数据时） -->
    <div class="table-card">
      <!-- 独立空状态容器：脱离 Element Plus 表格 DOM 约束 -->
      <div v-if="!loading && allCompanies.length === 0" class="standalone-empty">
        <el-empty
          :description="keyword || statusFilter || industryFilter ? '没有符合筛选条件的单位' : '暂无被审计单位数据'"
          :image-size="120"
        >
          <el-button v-if="!keyword && !statusFilter && !industryFilter" type="primary" @click="openCreateDialog">
            新建第一个单位
          </el-button>
          <el-button v-else @click="clearFilters">清除筛选</el-button>
        </el-empty>
      </div>

      <el-table
        v-else
        :data="companies"
        v-loading="loading"
        stripe
        class="data-table"
        :header-cell-style="headerCellStyle"
        row-key="id"
      >
        <!-- 筛选无结果空状态 -->
        <template #empty>
          <div class="empty-state">
            <el-empty
              description="没有符合筛选条件的单位"
              :image-size="120"
            >
              <el-button @click="clearFilters">清除筛选</el-button>
            </el-empty>
          </div>
        </template>

        <el-table-column prop="name" label="单位名称" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="cell-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="单位编码" width="130" />
        <el-table-column prop="tax_id" label="税号" width="170">
          <template #default="{ row }">
            <span :class="{ 'cell-muted': !row.tax_id }">{{ row.tax_id || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="industry" label="行业" width="120">
          <template #default="{ row }">
            <span :class="{ 'cell-muted': !row.industry }">{{ row.industry || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="90" align="center">
          <template #default="{ row }">
            <span class="status-dot" :class="row.is_active ? 'status-dot--active' : 'status-dot--inactive'" />
            {{ row.is_active ? '正常' : '停用' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="150" align="center">
          <template #default="{ row }">
            <span class="cell-muted cell-time">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="编号" width="120" align="center">
          <template #default="{ row }">
            <code class="cell-id" :title="row.id">{{ row.id.slice(0, 8) }}…</code>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="center" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openEditDialog(row)">
              编辑
            </el-button>
            <el-divider direction="vertical" />
            <el-popconfirm
              title="确认删除该单位？删除后不可恢复"
              confirm-button-text="确认删除"
              cancel-button-text="取消"
              :confirm-button-type="'danger'"
              @confirm="handleDelete(row.id)"
            >
              <template #reference>
                <el-button type="danger" link size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 分页 -->
    <div class="pagination-wrapper">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        background
        size="default"
      />
    </div>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑单位' : '新建单位'"
      width="540px"
      :close-on-click-modal="false"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="100px"
        label-position="right"
        class="company-form"
        :hide-required-asterisk="false"
      >
        <el-form-item label="单位名称" prop="name" required>
          <el-input
            v-model="form.name"
            placeholder="请输入单位全称"
            maxlength="100"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="单位编码" prop="code" required>
          <el-input
            v-model="form.code"
            placeholder="唯一编码，如 C001"
            maxlength="50"
            :disabled="isEdit"
          />
          <div v-if="isEdit" class="form-field-hint">编码创建后不可修改</div>
        </el-form-item>
        <el-form-item label="税号" prop="tax_id">
          <el-input v-model="form.tax_id" placeholder="选填" maxlength="30" />
        </el-form-item>
        <el-form-item label="地址" prop="address">
          <el-input v-model="form.address" placeholder="选填" maxlength="200" />
        </el-form-item>
        <el-form-item label="行业" prop="industry">
          <el-input v-model="form.industry" placeholder="选填，如：制造业" maxlength="50" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">
            {{ isEdit ? '保存修改' : '确认创建' }}
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import api from '@/api'
import { normalizeError } from '@/utils/error'
import type { Company } from '@/types'

// ===== 数据 =====
const allCompanies = ref<Company[]>([])
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const industryFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

// ===== 防抖搜索 =====
let debounceTimer: ReturnType<typeof setTimeout> | null = null
function handleSearchDebounced() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => handleSearch(), 300)
}

// ===== 客户端筛选 =====
const filteredCompanies = computed(() => {
  let list = allCompanies.value

  // 关键字搜索（名称 / 编码）
  if (keyword.value.trim()) {
    const kw = keyword.value.trim().toLowerCase()
    list = list.filter(
      (c) =>
        c.name.toLowerCase().includes(kw) ||
        c.code.toLowerCase().includes(kw) ||
        (c.tax_id && c.tax_id.toLowerCase().includes(kw))
    )
  }

  // 状态筛选
  if (statusFilter.value === 'active') {
    list = list.filter((c) => c.is_active)
  } else if (statusFilter.value === 'inactive') {
    list = list.filter((c) => !c.is_active)
  }

  // 行业筛选
  if (industryFilter.value) {
    list = list.filter((c) => c.industry === industryFilter.value)
  }

  return list
})

// 行业选项（从数据中提取）
const industryOptions = computed(() => {
  const industries = new Set<string>()
  allCompanies.value.forEach((c) => {
    if (c.industry) industries.add(c.industry)
  })
  return [...industries].sort()
})

// 当前页数据
const companies = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredCompanies.value.slice(start, start + pageSize.value)
})

const total = computed(() => filteredCompanies.value.length)

// ===== 表格样式 =====
const headerCellStyle = {
  background: '#f7f8fa',
  color: '#3d4148',
  fontWeight: '600',
  fontSize: '13px',
  borderBottom: '2px solid #e4e7ec',
}

// ===== 日期格式化 =====
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

// ===== 提取后端错误（委托给共享工具） =====
function extractError(e: any, defaultMsg: string): string {
  return normalizeError(e, defaultMsg)
}

// ===== 数据获取 =====
async function fetchAllCompanies() {
  loading.value = true
  try {
    const pageSize = 100
    const first = await api.get('/companies', {
      params: { page: 1, page_size: pageSize },
    })
    const items: Company[] = [...first.data.items]
    const totalPages = Math.ceil(first.data.total / pageSize)

    // 循环拉取剩余页
    const requests: Promise<any>[] = []
    for (let p = 2; p <= totalPages; p++) {
      requests.push(
        api.get('/companies', { params: { page: p, page_size: pageSize } })
      )
    }
    if (requests.length > 0) {
      const results = await Promise.all(requests)
      for (const res of results) {
        items.push(...res.data.items)
      }
    }

    allCompanies.value = items
  } catch (e: any) {
    ElMessage.error(extractError(e, '获取单位列表失败'))
    allCompanies.value = []
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
}

function clearFilters() {
  keyword.value = ''
  statusFilter.value = ''
  industryFilter.value = ''
  currentPage.value = 1
}

// ===== 对话框 =====
const dialogVisible = ref(false)
const isEdit = ref(false)
const submitting = ref(false)
const editId = ref<string | null>(null)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  code: '',
  tax_id: '',
  address: '',
  industry: '',
})

const rules: FormRules = {
  name: [
    { required: true, message: '请输入单位名称', trigger: 'blur' },
    { max: 100, message: '名称不能超过 100 个字符', trigger: 'blur' },
  ],
  code: [
    { required: true, message: '请输入单位编码', trigger: 'blur' },
    { max: 50, message: '编码不能超过 50 个字符', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_-]+$/, message: '编码只能包含字母、数字、下划线和连字符', trigger: 'blur' },
  ],
}

// 新建
function openCreateDialog() {
  isEdit.value = false
  editId.value = null
  dialogVisible.value = true
}

// 编辑
function openEditDialog(row: Company) {
  isEdit.value = true
  editId.value = row.id
  form.name = row.name
  form.code = row.code
  form.tax_id = row.tax_id || ''
  form.address = row.address || ''
  form.industry = row.industry || ''
  dialogVisible.value = true
}

// 删除
async function handleDelete(id: string) {
  try {
    await api.delete(`/companies/${id}`)
    ElMessage.success('删除成功')
    // 从本地缓存中移除
    allCompanies.value = allCompanies.value.filter((c) => c.id !== id)
    if (companies.value.length === 0 && currentPage.value > 1) {
      currentPage.value--
    }
  } catch (e: any) {
    ElMessage.error(extractError(e, '删除失败'))
  }
}

// 提交
async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload: Record<string, any> = {
      name: form.name.trim(),
      tax_id: form.tax_id?.trim() || undefined,
      address: form.address?.trim() || undefined,
      industry: form.industry?.trim() || undefined,
    }

    if (isEdit.value && editId.value) {
      // 编辑模式不传 code（后端 CompanyUpdate 不支持）
      const { data } = await api.put<Company>(`/companies/${editId.value}`, payload)
      ElMessage.success('更新成功')
      // 更新本地缓存
      const idx = allCompanies.value.findIndex((c) => c.id === editId.value)
      if (idx !== -1) {
        allCompanies.value[idx] = { ...allCompanies.value[idx], ...data }
      }
    } else {
      // 创建模式传 code
      payload.code = form.code.trim()
      const { data } = await api.post<Company>('/companies', payload)
      ElMessage.success('创建成功')
      // 插入本地缓存
      allCompanies.value.unshift(data)
    }

    dialogVisible.value = false
    currentPage.value = 1
  } catch (e: any) {
    ElMessage.error(extractError(e, isEdit.value ? '更新失败' : '创建失败'))
  } finally {
    submitting.value = false
  }
}

function resetForm() {
  formRef.value?.resetFields()
  form.name = ''
  form.code = ''
  form.tax_id = ''
  form.address = ''
  form.industry = ''
}

onMounted(() => {
  fetchAllCompanies()
})
</script>

<style scoped>
.page {
  max-width: var(--content-max-width);
  margin: 0 auto;
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
  width: 260px;
}

.toolbar-select {
  width: 140px;
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

/* 单元格样式 */
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

.cell-id {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  color: var(--color-gray-400);
  background: var(--color-gray-50);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  cursor: default;
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

/* 空状态（表格内筛选无结果用） */
.empty-state {
  padding: var(--spacing-10) 0;
}

/* 独立空状态（无数据时脱离表格渲染） */
.standalone-empty {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 320px;
  padding: var(--spacing-6);
}

/* 分页 */
.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--spacing-4);
}

/* ===== 对话框 ===== */
.company-form {
  padding-top: var(--spacing-2);
}

.form-field-hint {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  margin-top: var(--spacing-1);
  line-height: var(--line-height-base);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-3);
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
    justify-content: space-between;
  }
}

@media (max-width: 480px) {
  /* 对话框全宽 */
  :deep(.el-dialog) {
    width: calc(100vw - var(--spacing-8)) !important;
    margin: 0 auto;
  }

  /* 表单 label 换行 */
  :deep(.el-form-item) {
    display: block;
    margin-bottom: var(--spacing-3);
  }

  :deep(.el-form-item__label) {
    width: auto !important;
    margin-bottom: var(--spacing-1);
  }

  /* 分页简化 */
  .pagination-wrapper :deep(.el-pagination) {
    justify-content: center;
  }

  /* 表格横向滚动（有数据时） */
  .table-card {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .data-table {
    min-width: 800px;
  }

  /* 独立空状态容器：撑满可视区域 */
  .standalone-empty {
    min-height: 240px;
    padding: var(--spacing-4);
  }

  .standalone-empty :deep(.el-empty__description) {
    max-width: calc(100vw - var(--spacing-10));
    white-space: normal;
    word-break: break-word;
  }
}
</style>
