<template>
  <div class="page">
    <h2 style="margin-bottom: 24px;">数据导入</h2>

    <!-- 步骤条 -->
    <el-steps :active="activeStep" align-center finish-status="success" class="steps">
      <el-step title="上传文件" description="选择公司与文件" />
      <el-step title="字段映射" description="确认列对应关系" />
      <el-step title="执行导入" description="查看导入结果" />
    </el-steps>

    <div class="step-content">
      <!-- ====== 步骤 1：上传文件 ====== -->
      <div v-if="activeStep === 0" class="step-upload">
        <el-form label-width="100px" label-position="right" style="max-width: 520px; margin: 0 auto;">
          <!-- 选择公司 -->
          <el-form-item label="被审计单位">
            <el-select
              v-model="selectedCompanyId"
              placeholder="请选择公司"
              style="width: 100%"
              filterable
            >
              <el-option
                v-for="c in companies"
                :key="c.id"
                :label="`${c.name} (${c.code})`"
                :value="c.id"
              />
            </el-select>
          </el-form-item>

          <!-- 选择数据类型 -->
          <el-form-item label="数据类型">
            <el-select v-model="dataType" placeholder="请选择数据类型" style="width: 100%">
              <el-option label="科目余额表" value="trial_balance" />
              <el-option label="序时账" value="journal" />
              <el-option label="辅助明细账" value="subsidiary" />
            </el-select>
          </el-form-item>

          <!-- 文件上传 -->
          <el-form-item label="选择文件">
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :limit="1"
              :on-change="handleFileChange"
              :on-remove="handleFileRemove"
              :file-list="fileList"
              drag
              accept=".xlsx,.csv"
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="upload-text">
                拖拽文件到此处，或 <em>点击上传</em>
              </div>
              <template #tip>
                <div class="upload-tip">支持 .xlsx / .csv 格式，单文件最大 10MB</div>
              </template>
            </el-upload>
          </el-form-item>
        </el-form>

        <div style="text-align: center; margin-top: 32px;">
          <el-button type="primary" :disabled="!canNext" @click="goPreview">
            下一步：字段映射
            <el-icon style="margin-left: 4px;"><ArrowRight /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- ====== 步骤 2：字段映射 ====== -->
      <div v-if="activeStep === 1" class="step-mapping">
        <h3 style="margin-bottom: 16px;">字段映射</h3>
        <p class="hint">
          系统已自动匹配部分字段，请检查并手动调整未匹配的列。
          <el-tag size="small" type="success">绿色</el-tag> = 已匹配，
          <el-tag size="small" type="danger">红色</el-tag> = 需手动选择
        </p>

        <!-- 映射表 -->
        <el-table :data="mappings" stripe border style="width: 100%; margin-bottom: 24px;">
          <el-table-column prop="file_column" label="文件列名" width="180" />
          <el-table-column label="系统字段" min-width="200">
            <template #default="{ row }">
              <div v-if="row.status === 'matched'" class="matched-field">
                <el-tag type="success" size="small">{{ row.matched_field }}</el-tag>
              </div>
              <el-select
                v-else
                v-model="row.matched_field"
                placeholder="请选择对应字段"
                style="width: 100%"
                size="small"
              >
                <el-option
                  v-for="f in availableFields"
                  :key="f.value"
                  :label="f.label"
                  :value="f.value"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="示例数据" min-width="200">
            <template #default="{ row }">
              <code>{{ row.sample_value || '-' }}</code>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'matched' ? 'success' : 'danger'" size="small">
                {{ row.status === 'matched' ? '已匹配' : '未匹配' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>

        <!-- 预览前 5 行 -->
        <h3 style="margin-bottom: 12px;">数据预览（前 5 行）</h3>
        <el-table :data="previewRows" stripe border max-height="260" style="width: 100%;">
          <el-table-column
            v-for="col in previewColumns"
            :key="col"
            :prop="col"
            :label="col"
            min-width="140"
            show-overflow-tooltip
          />
        </el-table>

        <div style="text-align: center; margin-top: 24px;">
          <el-button @click="activeStep = 0" style="margin-right: 12px;">上一步</el-button>
          <el-button type="primary" :disabled="!mappingValid" @click="goExecute">
            确认映射，开始导入
          </el-button>
        </div>
      </div>

      <!-- ====== 步骤 3：执行导入 ====== -->
      <div v-if="activeStep === 2" class="step-execute">
        <!-- 进度条 -->
        <div v-if="executing" class="executing">
          <h3 style="margin-bottom: 24px; text-align: center;">正在导入数据...</h3>
          <el-progress
            :percentage="progress"
            :status="progress === 100 ? 'success' : undefined"
            :stroke-width="20"
            :text-inside="true"
          />
        </div>

        <!-- 结果 -->
        <div v-else class="result">
          <el-result
            :icon="importResult.fail_count === 0 ? 'success' : 'warning'"
            :title="importResult.fail_count === 0 ? '导入完成' : '导入完成（部分失败）'"
            :sub-title="`成功 ${importResult.success_count} 条，失败 ${importResult.fail_count} 条`"
          >
            <template #extra>
              <el-button type="primary" @click="resetImport">再次导入</el-button>
              <el-button @click="resetImport">返回首页</el-button>
            </template>
          </el-result>

          <!-- 失败详情 -->
          <div v-if="importResult.failures.length > 0" style="margin-top: 24px;">
            <h4 style="margin-bottom: 12px;">失败详情</h4>
            <el-table :data="importResult.failures" stripe border max-height="300" style="width: 100%;">
              <el-table-column prop="row" label="行号" width="80" align="center" />
              <el-table-column prop="reason" label="错误原因" show-overflow-tooltip />
            </el-table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, ArrowRight } from '@element-plus/icons-vue'
import type { UploadFile, UploadInstance } from 'element-plus'
import api from '@/api'
import type { Company, FieldMapping, ImportResult } from '@/types'

// --- 步骤状态 ---
const activeStep = ref(0)
const selectedCompanyId = ref<number | null>(null)
const dataType = ref('trial_balance')
const fileList = ref<UploadFile[]>([])
const uploadRef = ref<UploadInstance>()

// 公司列表
const companies = ref<Company[]>([])

// --- 步骤 2：映射 ---
const mappings = ref<FieldMapping[]>([])
const previewRows = ref<Record<string, string>[]>([])

// 根据数据类型提供可选字段
const fieldOptions: Record<string, { label: string; value: string }[]> = {
  trial_balance: [
    { label: '科目编码', value: 'account_code' },
    { label: '科目名称', value: 'account_name' },
    { label: '期初借方余额', value: 'begin_debit' },
    { label: '期初贷方余额', value: 'begin_credit' },
    { label: '本期借方发生额', value: 'period_debit' },
    { label: '本期贷方发生额', value: 'period_credit' },
    { label: '期末借方余额', value: 'end_debit' },
    { label: '期末贷方余额', value: 'end_credit' },
  ],
  journal: [
    { label: '凭证号', value: 'voucher_no' },
    { label: '凭证日期', value: 'voucher_date' },
    { label: '摘要', value: 'summary' },
    { label: '科目编码', value: 'account_code' },
    { label: '科目名称', value: 'account_name' },
    { label: '借方金额', value: 'debit' },
    { label: '贷方金额', value: 'credit' },
  ],
  subsidiary: [
    { label: '凭证号', value: 'voucher_no' },
    { label: '凭证日期', value: 'voucher_date' },
    { label: '摘要', value: 'summary' },
    { label: '科目编码', value: 'account_code' },
    { label: '辅助核算类型', value: 'auxiliary_type' },
    { label: '辅助核算编码', value: 'auxiliary_code' },
    { label: '辅助核算名称', value: 'auxiliary_name' },
    { label: '借方金额', value: 'debit' },
    { label: '贷方金额', value: 'credit' },
  ],
}

const availableFields = computed(() => fieldOptions[dataType.value] || [])

// 预览列名（取自第一行的 key）
const previewColumns = computed(() => {
  if (previewRows.value.length === 0) return []
  return Object.keys(previewRows.value[0])
})

// 是否可以进入下一步
const canNext = computed(() => selectedCompanyId.value && fileList.value.length > 0)

// 映射是否全部有效
const mappingValid = computed(() => {
  if (mappings.value.length === 0) return false
  return mappings.value.every((m) => !!m.matched_field)
})

// --- 步骤 3：执行 ---
const executing = ref(false)
const progress = ref(0)
const importResult = ref<ImportResult>({
  success_count: 0,
  fail_count: 0,
  failures: [],
})

// 获取公司列表
async function fetchCompanies() {
  try {
    const { data } = await api.get('/companies', { params: { page: 1, page_size: 100 } })
    companies.value = data.items
  } catch {
    ElMessage.error('获取公司列表失败')
  }
}

// 文件变更
function handleFileChange(file: UploadFile) {
  fileList.value = [file]
}

function handleFileRemove() {
  fileList.value = []
}

// ---- Mock 预览 ----
async function goPreview() {
  // TODO: 实际对接 POST /api/v1/imports/preview
  // const formData = new FormData()
  // formData.append('file', fileList.value[0].raw!)
  // formData.append('data_type', dataType.value)
  // const { data } = await api.post('/imports/preview', formData)

  await new Promise((r) => setTimeout(r, 600))

  // Mock 映射数据
  const mockMappings: FieldMapping[] = availableFields.value.map((f, i) => ({
    file_column: f.label,
    matched_field: i < availableFields.value.length - 2 ? f.value : null,
    sample_value: `示例数据${i + 1}`,
    status: i < availableFields.value.length - 2 ? 'matched' : 'unmatched',
  }))

  mappings.value = mockMappings

  // Mock 预览行
  const row: Record<string, string> = {}
  mockMappings.forEach((m) => {
    row[m.file_column] = m.sample_value
  })
  previewRows.value = [row, row, row, row, row]

  activeStep.value = 1
}

// ---- Mock 执行 ----
async function goExecute() {
  activeStep.value = 2
  executing.value = true
  progress.value = 0

  // 模拟进度
  const timer = setInterval(() => {
    progress.value = Math.min(100, progress.value + 10 + Math.floor(Math.random() * 15))
  }, 300)

  // TODO: 实际对接 POST /api/v1/imports/execute
  // await api.post('/imports/execute', { ... })

  await new Promise((r) => setTimeout(r, 3000))
  clearInterval(timer)
  progress.value = 100

  // Mock 结果
  importResult.value = {
    success_count: 98,
    fail_count: 2,
    failures: [
      { row: 5, reason: '科目编码不存在：9999' },
      { row: 42, reason: '借方金额格式错误：abc' },
    ],
  }

  executing.value = false
}

function resetImport() {
  activeStep.value = 0
  selectedCompanyId.value = null
  dataType.value = 'trial_balance'
  fileList.value = []
  uploadRef.value?.clearFiles()
  mappings.value = []
  previewRows.value = []
  executing.value = false
  progress.value = 0
  importResult.value = { success_count: 0, fail_count: 0, failures: [] }
}

onMounted(() => {
  fetchCompanies()
})
</script>

<style scoped>
.steps {
  margin-bottom: 40px;
}

.step-content {
  min-height: 360px;
}

/* 步骤 1 */
.step-upload {
  padding: 20px 0;
}

.upload-text {
  color: #999;
  margin-top: 8px;
}

.upload-text em {
  color: #409eff;
  font-style: normal;
}

.upload-tip {
  color: #c0c4cc;
  font-size: 12px;
}

/* 步骤 2 */
.step-mapping {
  padding: 0;
}

.step-mapping .hint {
  color: #666;
  margin-bottom: 16px;
  line-height: 1.8;
}

.matched-field {
  display: flex;
  align-items: center;
}

.step-mapping code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}

/* 步骤 3 */
.step-execute {
  padding: 20px 0;
}

.executing {
  max-width: 500px;
  margin: 60px auto 0;
}

.result {
  max-width: 700px;
  margin: 0 auto;
}
</style>
