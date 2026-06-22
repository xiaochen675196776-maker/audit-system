<template>
  <div class="template-page">
    <PageHeader
      eyebrow="模板库"
      title="导入模板管理"
      subtitle="全局解析与映射模板 · 跨单位复用"
    >
      <template #actions>
        <el-button type="primary" @click="showUploadSample = true">
          <el-icon style="margin-right:6px"><Upload /></el-icon>
          上传样本生成模板
        </el-button>
      </template>
    </PageHeader>

    <!-- 筛选栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-select
          v-model="filterDataType"
          placeholder="数据类型"
          clearable
          style="width:160px"
          @change="fetchTemplates"
        >
          <el-option label="科目余额表" value="trial_balance" />
          <el-option label="序时账" value="journal" />
          <el-option label="辅助明细账" value="subsidiary" />
        </el-select>
        <el-select
          v-model="filterActive"
          placeholder="启用状态"
          clearable
          style="width:120px"
          @change="fetchTemplates"
        >
          <el-option label="已启用" :value="true" />
          <el-option label="已停用" :value="false" />
        </el-select>
      </div>
      <div class="toolbar-right">
        <span class="total-text">共 {{ templates.length }} 个模板</span>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && templates.length === 0" class="empty-state">
      <el-icon :size="48" color="var(--text-placeholder)"><DocumentCopy /></el-icon>
      <p class="empty-title">暂无导入模板</p>
      <p class="empty-desc">上传一份审计数据样本，系统将自动生成解析与映射模板草稿</p>
    </div>

    <!-- 模板卡片列表 -->
    <div v-else class="template-grid">
      <div
        v-for="t in templates"
        :key="t.id"
        class="template-card"
        :class="{ inactive: !t.is_active }"
      >
        <div class="card-top">
          <div class="card-name">{{ t.name }}</div>
          <el-switch
            :model-value="t.is_active"
            size="small"
            @change="toggleActive(t)"
          />
        </div>
        <div class="card-meta">
          <el-tag size="small" type="info">{{ dataTypeLabel(t.data_type) }}</el-tag>
          <span v-if="t.source_label" class="card-source">{{ t.source_label }}</span>
          <span class="card-date">{{ formatDate(t.updated_at) }}</span>
        </div>
        <div class="card-stats">
          <span>{{ mappedCount(t) }} 个字段映射</span>
          <span v-if="t.default_values && Object.keys(t.default_values).length">
            · 默认值: {{ Object.keys(t.default_values).join(', ') }}
          </span>
        </div>

        <div class="card-actions">
          <el-button size="small" @click="editTemplate(t)">编辑</el-button>
          <el-button size="small" @click="openTest(t)">测试</el-button>
          <el-popconfirm
            title="确认删除此模板？"
            confirm-button-text="删除"
            cancel-button-text="取消"
            @confirm="deleteTemplate(t)"
          >
            <template #reference>
              <el-button size="small" type="danger" text>删除</el-button>
            </template>
          </el-popconfirm>
        </div>
      </div>
    </div>

    <!-- 上传样本对话框 -->
    <el-dialog
      v-model="showUploadSample"
      title="上传样本生成模板草稿"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="数据类型">
          <el-select v-model="sampleDataType" style="width:100%">
            <el-option label="科目余额表" value="trial_balance" />
            <el-option label="序时账" value="journal" />
            <el-option label="辅助明细账" value="subsidiary" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板名称（可选）">
          <el-input v-model="sampleName" placeholder="留空则自动生成" maxlength="200" />
        </el-form-item>
        <el-form-item label="上传文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            :on-change="handleFileChange"
            :on-remove="() => (sampleFile = null)"
            accept=".xlsx,.xls,.csv"
            drag
          >
            <el-icon :size="32"><UploadFilled /></el-icon>
            <div class="upload-text">拖拽文件到此处或点击上传</div>
            <div class="upload-hint">支持 .xlsx .xls .csv</div>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showUploadSample = false">取消</el-button>
        <el-button type="primary" :loading="sampleLoading" @click="submitSample">
          生成草稿
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑模板对话框 -->
    <el-dialog
      v-model="showEdit"
      :title="editingId ? '编辑模板' : '新建模板'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form v-if="editForm" label-position="top">
        <el-form-item label="模板名称">
          <el-input v-model="editForm.name" maxlength="200" />
        </el-form-item>
        <el-form-item label="数据类型">
          <el-select v-model="editForm.data_type" style="width:100%">
            <el-option label="科目余额表" value="trial_balance" />
            <el-option label="序时账" value="journal" />
            <el-option label="辅助明细账" value="subsidiary" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源标识">
          <el-input v-model="editForm.source_label" placeholder="如：用友U8、金蝶K3" maxlength="200" />
        </el-form-item>
        <el-form-item label="字段映射 (JSON)">
          <el-input
            v-model="editForm.column_rules_str"
            type="textarea"
            :rows="6"
            placeholder='{"col_001":"voucher_no","col_002":"voucher_date"}'
          />
          <div class="form-hint">列 ID → 标准字段 / 辅助字段名 / ignore（忽略）</div>
        </el-form-item>
        <el-form-item label="默认年度/期间 (JSON)">
          <el-input
            v-model="editForm.default_values_str"
            type="textarea"
            :rows="2"
            placeholder='{"fiscal_year":2024,"period":1}'
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" :loading="editLoading" @click="submitEdit">
          {{ editingId ? '保存修改' : '创建模板' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 测试模板对话框 -->
    <el-dialog
      v-model="showTest"
      title="测试模板"
      width="520px"
      :close-on-click-modal="false"
    >
      <p class="test-info">模板：<strong>{{ testTarget?.name }}</strong></p>
      <el-upload
        :auto-upload="false"
        :limit="1"
        :on-change="handleTestFileChange"
        :on-remove="() => (testFile = null)"
        accept=".xlsx,.xls,.csv"
        drag
      >
        <el-icon :size="32"><UploadFilled /></el-icon>
        <div class="upload-text">上传测试文件</div>
      </el-upload>

      <div v-if="testResult" class="test-result">
        <el-alert
          :title="testResult.message"
          :type="testResult.applicable ? 'success' : 'warning'"
          :closable="false"
          show-icon
        />
        <div class="test-detail">
          <p v-if="testResult.hit_fields.length">
            命中字段：{{ testResult.hit_fields.join('、') }}
          </p>
          <p v-if="testResult.missing_fields.length">
            缺失字段：{{ testResult.missing_fields.join('、') }}
          </p>
          <p v-for="w in testResult.warnings" :key="w" class="test-warning">{{ w }}</p>
        </div>
      </div>
      <template #footer>
        <el-button @click="showTest = false">关闭</el-button>
        <el-button type="primary" :loading="testLoading" @click="submitTest">测试</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload, UploadFilled, DocumentCopy } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import api from '@/api'
import { normalizeError } from '@/utils/error'

// ── 数据 ──────────────────────────────────
interface Template {
  id: string
  name: string
  data_type: string
  source_label: string | null
  is_active: boolean
  header_signature: Record<string, string> | null
  parse_config: Record<string, any>
  column_rules: Record<string, string>
  default_values: Record<string, any> | null
  created_at: string
  updated_at: string
}

const templates = ref<Template[]>([])
const loading = ref(false)
const filterDataType = ref<string | null>(null)
const filterActive = ref<boolean | null>(null)

async function fetchTemplates() {
  loading.value = true
  try {
    const params: Record<string, any> = {}
    if (filterDataType.value) params.data_type = filterDataType.value
    if (filterActive.value !== null) params.is_active = filterActive.value
    const { data } = await api.get('/import-templates', { params })
    templates.value = data.items
  } catch (e: any) {
    ElMessage.error(normalizeError(e, '获取模板列表失败'))
  } finally {
    loading.value = false
  }
}

onMounted(fetchTemplates)

// ── 辅助 ──────────────────────────────────
function dataTypeLabel(t: string) {
  return { trial_balance: '科目余额表', journal: '序时账', subsidiary: '辅助明细账' }[t] || t
}
function formatDate(d: string) {
  if (!d) return ''
  return d.slice(0, 10)
}
function mappedCount(t: Template) {
  return Object.values(t.column_rules || {}).filter(v => v !== 'ignore').length
}

// ── 启停 ──────────────────────────────────
async function toggleActive(t: Template) {
  try {
    await api.put(`/import-templates/${t.id}`, { is_active: !t.is_active })
    t.is_active = !t.is_active
    ElMessage.success(t.is_active ? '已启用' : '已停用')
  } catch (e: any) {
    ElMessage.error(normalizeError(e, '操作失败'))
  }
}

// ── 删除 ──────────────────────────────────
async function deleteTemplate(t: Template) {
  try {
    await api.delete(`/import-templates/${t.id}`)
    ElMessage.success('模板已删除')
    fetchTemplates()
  } catch (e: any) {
    ElMessage.error(normalizeError(e, '删除失败'))
  }
}

// ── 上传样本 ──────────────────────────────
const showUploadSample = ref(false)
const sampleDataType = ref('journal')
const sampleName = ref('')
const sampleFile = ref<File | null>(null)
const sampleLoading = ref(false)

function handleFileChange(file: any) {
  sampleFile.value = file.raw
}

async function submitSample() {
  if (!sampleFile.value) {
    ElMessage.warning('请选择文件')
    return
  }
  sampleLoading.value = true
  try {
    const form = new FormData()
    form.append('file', sampleFile.value)
    form.append('data_type', sampleDataType.value)
    if (sampleName.value.trim()) form.append('name', sampleName.value.trim())
    form.append('save', 'true')

    const { data } = await api.post('/import-templates/from-sample', form)
    ElMessage.success('模板已生成并保存')
    showUploadSample.value = false
    sampleName.value = ''
    sampleFile.value = null
    fetchTemplates()
  } catch (e: any) {
    ElMessage.error(normalizeError(e, '生成模板失败'))
  } finally {
    sampleLoading.value = false
  }
}

// ── 编辑 ──────────────────────────────────
const showEdit = ref(false)
const editingId = ref<string | null>(null)
const editLoading = ref(false)
const editForm = reactive({
  name: '',
  data_type: 'journal',
  source_label: '',
  column_rules_str: '{}',
  default_values_str: '{}',
})

function editTemplate(t: Template) {
  editingId.value = t.id
  editForm.name = t.name
  editForm.data_type = t.data_type
  editForm.source_label = t.source_label || ''
  editForm.column_rules_str = JSON.stringify(t.column_rules || {}, null, 2)
  editForm.default_values_str = JSON.stringify(t.default_values || {}, null, 2)
  showEdit.value = true
}

async function submitEdit() {
  editLoading.value = true
  try {
    let columnRules = {}
    try { columnRules = JSON.parse(editForm.column_rules_str || '{}') } catch {
      ElMessage.warning('字段映射 JSON 格式无效')
      editLoading.value = false; return
    }
    let defaultValues = null
    if (editForm.default_values_str.trim()) {
      try { defaultValues = JSON.parse(editForm.default_values_str) } catch {
        ElMessage.warning('默认值 JSON 格式无效')
        editLoading.value = false; return
      }
    }

    const body = {
      name: editForm.name,
      data_type: editForm.data_type,
      source_label: editForm.source_label || null,
      column_rules: columnRules,
      default_values: defaultValues,
    }

    if (editingId.value) {
      await api.put(`/import-templates/${editingId.value}`, body)
      ElMessage.success('模板已更新')
    } else {
      await api.post('/import-templates', body)
      ElMessage.success('模板已创建')
    }
    showEdit.value = false
    editingId.value = null
    fetchTemplates()
  } catch (e: any) {
    ElMessage.error(normalizeError(e, '保存失败'))
  } finally {
    editLoading.value = false
  }
}

// ── 测试 ──────────────────────────────────
const showTest = ref(false)
const testTarget = ref<Template | null>(null)
const testFile = ref<File | null>(null)
const testLoading = ref(false)
const testResult = ref<any>(null)

function openTest(t: Template) {
  testTarget.value = t
  testFile.value = null
  testResult.value = null
  showTest.value = true
}

function handleTestFileChange(file: any) {
  testFile.value = file.raw
}

async function submitTest() {
  if (!testFile.value || !testTarget.value) {
    ElMessage.warning('请选择测试文件')
    return
  }
  testLoading.value = true
  try {
    const form = new FormData()
    form.append('file', testFile.value)
    const { data } = await api.post(`/import-templates/${testTarget.value.id}/test`, form)
    testResult.value = data
  } catch (e: any) {
    ElMessage.error(normalizeError(e, '模板测试失败'))
  } finally {
    testLoading.value = false
  }
}
</script>

<style scoped>
.template-page {
  max-width: var(--content-max-width);
  margin: 0 auto;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-4);
  flex-wrap: wrap;
}
.toolbar-left {
  display: flex;
  gap: var(--spacing-2);
  align-items: center;
}
.toolbar-right {
  margin-left: auto;
}
.total-text {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.empty-state {
  text-align: center;
  padding: var(--spacing-12) var(--spacing-4);
  color: var(--text-placeholder);
}
.empty-title { font-size: var(--font-size-xl); margin: var(--spacing-3) 0 var(--spacing-2); color: var(--text-secondary); }
.empty-desc { font-size: var(--font-size-sm); }

.template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--spacing-4);
}

.template-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
  transition: box-shadow var(--transition-fast);
}
.template-card:hover { box-shadow: var(--shadow-md); }
.template-card.inactive { opacity: 0.6; }

.card-top { display: flex; justify-content: space-between; align-items: flex-start; }
.card-name { font-size: var(--font-size-md); font-weight: var(--font-weight-semibold); color: var(--text-primary); }

.card-meta { display: flex; gap: var(--spacing-2); align-items: center; flex-wrap: wrap; }
.card-source { font-size: var(--font-size-sm); color: var(--text-secondary); }
.card-date { font-size: var(--font-size-xs); color: var(--text-placeholder); margin-left: auto; }

.card-stats { font-size: var(--font-size-sm); color: var(--text-secondary); }

.card-actions { display: flex; gap: var(--spacing-1); padding-top: var(--spacing-2); border-top: 1px solid var(--border-light); }

.upload-text { margin-top: var(--spacing-2); font-size: var(--font-size-sm); color: var(--text-secondary); }
.upload-hint { font-size: var(--font-size-xs); color: var(--text-placeholder); }

.form-hint { font-size: var(--font-size-xs); color: var(--text-placeholder); margin-top: var(--spacing-1); }

.test-info { margin-bottom: var(--spacing-3); }
.test-result { margin-top: var(--spacing-4); }
.test-detail { margin-top: var(--spacing-3); font-size: var(--font-size-sm); color: var(--text-secondary); }
.test-warning { color: var(--color-warning); }

@media (max-width: 768px) {
  .toolbar { flex-direction: column; align-items: stretch; }
  .toolbar-right { margin-left: 0; }
  .template-grid { grid-template-columns: 1fr; }
}
</style>
