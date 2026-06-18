<template>
  <div class="page">
    <div class="page-header">
      <h2>被审计单位管理</h2>
      <el-button type="primary" @click="openCreateDialog">
        <el-icon><Plus /></el-icon>
        新建单位
      </el-button>
    </div>

    <!-- 搜索栏 -->
    <div class="search-bar">
      <el-input
        v-model="keyword"
        placeholder="搜索单位名称或编码..."
        clearable
        style="width: 320px"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button type="default" @click="handleSearch" style="margin-left: 12px">
        搜索
      </el-button>
    </div>

    <!-- 表格 -->
    <el-table
      :data="companies"
      v-loading="loading"
      stripe
      border
      style="width: 100%"
      empty-text="暂无数据"
    >
      <el-table-column prop="id" label="ID" width="60" align="center" />
      <el-table-column prop="name" label="单位名称" min-width="180" show-overflow-tooltip />
      <el-table-column prop="code" label="单位编码" width="140" />
      <el-table-column prop="tax_id" label="税号" width="160">
        <template #default="{ row }">
          {{ row.tax_id || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="industry" label="行业" width="120">
        <template #default="{ row }">
          {{ row.industry || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
            {{ row.status === 'active' ? '正常' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" align="center" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="openEditDialog(row)">
            编辑
          </el-button>
          <el-divider direction="vertical" />
          <el-popconfirm
            title="确认删除该单位？"
            confirm-button-text="删除"
            cancel-button-text="取消"
            @confirm="handleDelete(row.id)"
          >
            <template #reference>
              <el-button type="danger" link size="small">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrapper">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="fetchCompanies"
        @size-change="fetchCompanies"
      />
    </div>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑单位' : '新建单位'"
      width="560px"
      :close-on-click-modal="false"
      @closed="resetForm"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="90px"
        label-position="right"
      >
        <el-form-item label="单位名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入单位名称" />
        </el-form-item>
        <el-form-item label="单位编码" prop="code">
          <el-input v-model="form.code" placeholder="请输入唯一编码，如 C001" />
        </el-form-item>
        <el-form-item label="税号" prop="tax_id">
          <el-input v-model="form.tax_id" placeholder="请输入税号（选填）" />
        </el-form-item>
        <el-form-item label="地址" prop="address">
          <el-input v-model="form.address" placeholder="请输入地址（选填）" />
        </el-form-item>
        <el-form-item label="行业" prop="industry">
          <el-input v-model="form.industry" placeholder="请输入行业（选填）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import api from '@/api'
import type { Company } from '@/types'

const companies = ref<Company[]>([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

// 对话框
const dialogVisible = ref(false)
const isEdit = ref(false)
const submitting = ref(false)
const editId = ref<number | null>(null)
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
  ],
}

// 获取公司列表
async function fetchCompanies() {
  loading.value = true
  try {
    const { data } = await api.get('/companies', {
      params: {
        page: currentPage.value,
        page_size: pageSize.value,
        keyword: keyword.value || undefined,
      },
    })
    companies.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('获取单位列表失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
  fetchCompanies()
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
async function handleDelete(id: number) {
  try {
    await api.delete(`/companies/${id}`)
    ElMessage.success('删除成功')
    // 如果当前页删空了，回退一页
    if (companies.value.length === 1 && currentPage.value > 1) {
      currentPage.value--
    }
    fetchCompanies()
  } catch {
    ElMessage.error('删除失败')
  }
}

// 提交表单
async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload = {
      name: form.name,
      code: form.code,
      tax_id: form.tax_id || undefined,
      address: form.address || undefined,
      industry: form.industry || undefined,
    }

    if (isEdit.value && editId.value) {
      await api.put(`/companies/${editId.value}`, payload)
      ElMessage.success('更新成功')
    } else {
      await api.post('/companies', payload)
      ElMessage.success('创建成功')
    }

    dialogVisible.value = false
    fetchCompanies()
  } catch {
    ElMessage.error(isEdit.value ? '更新失败' : '创建失败')
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
  fetchCompanies()
})
</script>

<style scoped>
.page {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
  color: #303133;
}

.search-bar {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
