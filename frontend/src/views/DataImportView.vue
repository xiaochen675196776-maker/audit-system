<template>
  <div class="import-wizard">
    <!-- 紧凑步骤轨道 -->
    <div class="wizard-track">
      <div
        v-for="(step, idx) in steps"
        :key="idx"
        class="track-step"
        :class="{
          active: activeStep === idx,
          done: activeStep > idx,
        }"
      >
        <span class="step-num">{{ activeStep > idx ? '✓' : idx + 1 }}</span>
        <span class="step-label">{{ step.label }}</span>
      </div>
      <div class="track-line">
        <div class="track-line-fill" :style="{ width: trackProgress }" />
      </div>
    </div>

    <!-- 步骤面板 -->
    <div class="wizard-body">
      <transition name="step-fade" mode="out-in">
        <!-- ====== 步骤 1：上传文件 ====== -->
        <div v-if="activeStep === 0" key="step1" class="step-content">
          <div class="step1-layout">
            <!-- 左侧：配置表单 -->
            <div class="step1-form">
              <h3 class="panel-title">导入配置</h3>
              <el-form label-width="90px" label-position="top" class="config-form">
                <el-form-item label="被审计单位">
                  <el-select
                    v-model="selectedCompanyId"
                    placeholder="选择公司"
                    filterable
                    class="form-full"
                  >
                    <el-option
                      v-for="c in companies"
                      :key="c.id"
                      :label="`${c.name} (${c.code})`"
                      :value="c.id"
                    />
                  </el-select>
                </el-form-item>

                <el-form-item label="数据类型">
                  <el-select v-model="dataType" placeholder="选择数据类型" class="form-full">
                    <el-option label="科目余额表" value="trial_balance" />
                    <el-option label="序时账" value="journal" />
                    <el-option label="辅助明细账" value="subsidiary" />
                  </el-select>
                </el-form-item>

                <el-row :gutter="12">
                  <el-col :span="12">
                    <el-form-item label="会计年度" :required="previewDone && !fileHasFiscalYear">
                      <el-input-number
                        v-model="manualFiscalYear"
                        :min="2000"
                        :max="2100"
                        :placeholder="previewDone ? (fileHasFiscalYear ? '已在文件中' : '如 2025') : '上传文件后识别'"
                        controls-position="right"
                        class="form-full"
                      />
                      <div class="field-note" :class="{ required: previewDone && !fileHasFiscalYear }">
                        {{ previewDone ? (fileHasFiscalYear ? '✓ 已在文件中识别' : '文件未含年度列，必须填写') : '上传文件后自动识别' }}
                      </div>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="会计期间" :required="previewDone && !fileHasPeriod">
                      <el-input-number
                        v-model="manualPeriod"
                        :min="1"
                        :max="12"
                        :placeholder="previewDone ? (fileHasPeriod ? '已在文件中' : '如 12') : '上传文件后识别'"
                        controls-position="right"
                        class="form-full"
                      />
                      <div class="field-note" :class="{ required: previewDone && !fileHasPeriod }">
                        {{ previewDone ? (fileHasPeriod ? '✓ 已在文件中识别' : '文件未含期间列，必须填写') : '上传文件后自动识别' }}
                      </div>
                    </el-form-item>
                  </el-col>
                </el-row>
              </el-form>
            </div>

            <!-- 右侧：上传区域 -->
            <div class="step1-upload">
              <h3 class="panel-title">选择文件</h3>
              <el-upload
                ref="uploadRef"
                :auto-upload="false"
                :limit="1"
                :on-change="handleFileChange"
                :on-remove="handleFileRemove"
                :file-list="fileList"
                drag
                accept=".xlsx,.csv,.xls"
                class="drag-upload"
              >
                <el-icon class="upload-icon"><UploadFilled /></el-icon>
                <div class="upload-text">
                  拖拽文件到此处，或 <em>点击上传</em>
                </div>
                <template #tip>
                  <div class="file-requirements">
                    <div class="req-item">
                      <span class="req-dot"></span>
                      支持电子表格文件或逗号分隔文本
                    </div>
                    <div class="req-item">
                      <span class="req-dot"></span>
                      单文件不超过十兆
                    </div>
                    <div class="req-item">
                      <span class="req-dot"></span>
                      首行应为表头，数据从第 2 行开始
                    </div>
                  </div>
                </template>
              </el-upload>
            </div>
          </div>

          <!-- 错误提示 -->
          <div v-if="previewError" class="preview-error">
            <el-alert
              :title="previewError"
              type="error"
              :closable="true"
              show-icon
              @close="previewError = ''"
            />
          </div>

          <!-- 操作按钮 -->
          <div class="step-footer">
            <div v-if="!canNext && !previewing && !previewError" class="footer-hint">
              <el-icon :size="14"><InfoFilled /></el-icon>
              {{ nextButtonHint }}
            </div>
            <el-button
              type="primary"
              size="large"
              :disabled="!canNext"
              :loading="previewing"
              @click="goPreview"
            >
              {{ previewing ? '正在解析文件...' : '下一步：字段映射' }}
              <el-icon v-if="!previewing" style="margin-left: 4px;"><ArrowRight /></el-icon>
            </el-button>
          </div>
        </div>

        <!-- ====== 步骤 2：字段映射 ====== -->
        <div v-else-if="activeStep === 1" key="step2" class="step-content">
          <div class="step2-layout">
            <!-- 左侧：映射表 -->
            <div class="step2-table">
              <div class="panel-header-row">
                <h3 class="panel-title">字段映射</h3>
                <span class="panel-meta">
                  {{ mappings.length }} 列 ·
                  {{ mappedCount }} 已映射 ·
                  {{ ignoredCount }} 已忽略
                </span>
              </div>
              <div class="mapping-table-card">
                <el-table
                  :data="mappings"
                  stripe
                  class="mapping-table"
                  size="small"
                >
                  <el-table-column label="文件列名" width="140">
                    <template #default="{ row }">
                      <span class="file-col-name">{{ row.file_column }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="映射到系统字段" min-width="200">
                    <template #default="{ row, $index }">
                      <el-select
                        v-model="mappings[$index].field_key"
                        :placeholder="row.field_key ? undefined : '选择字段…'"
                        size="small"
                        class="map-select"
                        :teleported="false"
                      >
                        <el-option-group label="操作">
                          <el-option label="⊘ 忽略此列" value="__ignore__" />
                        </el-option-group>
                        <el-option-group label="系统字段">
                          <el-option
                            v-for="f in availableFields"
                            :key="f.value"
                            :label="f.label"
                            :value="f.value"
                          />
                        </el-option-group>
                        <el-option-group label="辅助字段">
                          <el-option
                            v-for="(af, ai) in auxFields"
                            :key="'aux' + ai"
                            :label="af.name || '辅助字段' + (ai + 1)"
                            :value="'__aux__' + ai"
                          />
                        </el-option-group>
                      </el-select>
                    </template>
                  </el-table-column>
                  <el-table-column label="示例" width="120" align="center">
                    <template #default="{ row }">
                      <code class="sample-val">{{ row.sample_value || '-' }}</code>
                    </template>
                  </el-table-column>
                  <el-table-column label="状态" width="72" align="center">
                    <template #default="{ row }">
                      <span v-if="row.field_key === '__ignore__'" class="status-dot ignored" title="已忽略"></span>
                      <span v-else-if="row.field_key" class="status-dot matched" title="已映射"></span>
                      <span v-else class="status-dot unmatched" title="未映射"></span>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- 数据预览 -->
              <h4 class="sub-title">数据预览（前 5 行）</h4>
              <div class="preview-card">
                <el-table :data="previewRows" stripe size="small" max-height="220">
                  <el-table-column
                    v-for="col in previewHeaders"
                    :key="col"
                    :prop="col"
                    :label="col"
                    min-width="120"
                    show-overflow-tooltip
                  />
                </el-table>
              </div>
            </div>

            <!-- 右侧：导入前检查面板 -->
            <div class="step2-check">
              <h3 class="panel-title">导入前检查</h3>

              <!-- 必填字段缺失 -->
              <div class="check-block" v-if="missingFields.length > 0">
                <div class="check-block-title danger">
                  <el-icon :size="14"><WarningFilled /></el-icon>
                  缺少必填字段 ({{ missingFields.length }})
                </div>
                <div class="check-tags">
                  <span
                    v-for="f in missingFields"
                    :key="f"
                    class="check-tag danger"
                  >{{ missingFieldLabel(f) }}</span>
                </div>
                <div class="check-hint">请在映射下拉中为以上字段分配对应列</div>
              </div>

              <!-- 手动补充信息 -->
              <div class="check-block">
                <div class="check-block-title">
                  <el-icon :size="14"><EditPen /></el-icon>
                  手动补充信息
                </div>
                <div class="check-list">
                  <div class="check-item">
                    <span class="check-dot" :class="manualFiscalYear ? 'ok' : 'warn'"></span>
                    <span>会计年度：{{ manualFiscalYear || '未填写' }}</span>
                    <span v-if="fileHasFiscalYear" class="check-note">（文件已含）</span>
                  </div>
                  <div class="check-item">
                    <span class="check-dot" :class="manualPeriod ? 'ok' : 'warn'"></span>
                    <span>会计期间：{{ manualPeriod || '未填写' }}</span>
                    <span v-if="fileHasPeriod" class="check-note">（文件已含）</span>
                  </div>
                </div>
              </div>

              <!-- 辅助字段命名 -->
              <div class="check-block">
                <div class="check-block-title">
                  <el-icon :size="14"><EditPen /></el-icon>
                  辅助字段命名（在映射中选「辅助字段」后在此命名）
                </div>
                <div class="check-list">
                  <div
                    v-for="(af, ai) in auxFields"
                    :key="'auxname' + ai"
                    class="check-item aux-name-row"
                  >
                    <span class="check-dot muted"></span>
                    <span class="aux-name-label">辅助{{ ai + 1 }}</span>
                    <el-input
                      v-model="auxFields[ai].name"
                      size="small"
                      placeholder="输入字段名"
                      class="aux-name-input"
                      clearable
                    />
                  </div>
                </div>
              </div>

              <!-- 忽略列汇总 -->
              <div class="check-block" v-if="ignoredCount > 0">
                <div class="check-block-title muted">
                  <el-icon :size="14"><Hide /></el-icon>
                  已忽略列 ({{ ignoredCount }})
                </div>
                <div class="check-list">
                  <div
                    v-for="m in ignoredColumns"
                    :key="m.file_column"
                    class="check-item"
                  >
                    <span class="check-dot muted"></span>
                    <span>{{ m.file_column }}</span>
                  </div>
                </div>
              </div>

              <!-- 全部通过 -->
              <div v-if="mappingValid" class="check-all-ok">
                <el-icon :size="16"><CircleCheckFilled /></el-icon>
                所有检查通过，可以开始导入
              </div>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="step-footer">
            <el-button size="large" @click="activeStep = 0">上一步</el-button>
            <div class="footer-main-action">
              <el-button
                type="primary"
                size="large"
                :disabled="!mappingValid"
                :loading="executing"
                @click="goExecute"
              >
                {{ executing ? '正在导入...' : '开始导入' }}
              </el-button>
              <div v-if="!mappingValid && !executing" class="footer-hint">
                <el-icon :size="14"><InfoFilled /></el-icon>
                {{ mappingButtonHint }}
              </div>
            </div>
          </div>
        </div>

        <!-- ====== 步骤 3：执行结果 ====== -->
        <div v-else key="step3" class="step-content">
          <!-- 导入中 -->
          <div v-if="executing" class="importing">
            <el-icon :size="40" class="importing-icon is-loading"><Loading /></el-icon>
            <h3>正在导入数据...</h3>
            <el-progress
              :percentage="progress"
              :stroke-width="20"
              :text-inside="true"
              class="import-progress"
            />
            <p class="importing-note">请勿关闭页面，导入完成后自动显示结果</p>
          </div>

          <!-- 系统级错误 -->
          <div v-else-if="isSystemError" class="result-block">
            <div class="result-header error">
              <el-icon :size="28"><CircleCloseFilled /></el-icon>
              <div>
                <h3>导入请求失败</h3>
                <p>{{ result.failures[0]?.reason }}</p>
              </div>
            </div>
            <div class="result-actions">
              <el-button type="primary" @click="goBackToMapping">返回修改映射</el-button>
              <el-button @click="resetImport">重新选择文件</el-button>
            </div>
          </div>

          <!-- 全部成功 -->
          <div v-else-if="result.fail_count === 0" class="result-block">
            <div class="result-header success">
              <el-icon :size="28"><CircleCheckFilled /></el-icon>
              <div>
                <h3>导入完成</h3>
                <p>全部 {{ result.success_count }} 条数据已成功导入</p>
              </div>
            </div>
            <div class="result-actions">
              <el-button type="primary" @click="resetImport">继续导入</el-button>
              <el-button @click="$router.push('/')">返回首页</el-button>
            </div>
          </div>

          <!-- 部分成功 -->
          <div v-else class="result-block">
            <div class="result-header warning">
              <el-icon :size="28"><WarningFilled /></el-icon>
              <div>
                <h3>导入完成（部分失败）</h3>
                <p>
                  共 {{ result.success_count + result.fail_count }} 条，
                  <strong class="text-success">{{ result.success_count }} 条成功</strong>，
                  <strong class="text-danger">{{ result.fail_count }} 条失败</strong>
                </p>
              </div>
            </div>

            <!-- 错误列表 -->
            <div class="error-list-card">
              <div class="error-list-header">
                <span>失败明细（{{ result.failures.length }} 条）</span>
                <span class="error-list-hint">按行号排序，可上下滚动</span>
              </div>
              <div class="error-list-body">
                <div
                  v-for="(item, idx) in result.failures"
                  :key="idx"
                  class="error-row"
                >
                  <span class="error-row-num">{{ item.row > 0 ? `#${item.row}` : '-' }}</span>
                  <span class="error-row-msg">{{ item.reason }}</span>
                </div>
              </div>
            </div>

            <div class="result-actions">
              <el-button type="primary" @click="goBackToMapping">返回修改映射</el-button>
              <el-button @click="resetImport">重新导入</el-button>
            </div>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  UploadFilled,
  ArrowRight,
  InfoFilled,
  WarningFilled,
  EditPen,
  Hide,
  CircleCheckFilled,
  CircleCloseFilled,
  Loading,
} from '@element-plus/icons-vue'
import type { UploadFile, UploadInstance } from 'element-plus'
import api from '@/api'
import { normalizeError } from '@/utils/error'
import type {
  Company,
  ImportPreviewResponse,
  ImportExecuteResponse,
  MappingRow,
  ImportResultDisplay,
} from '@/types'

// ===== 步骤定义 =====
const steps = [
  { label: '上传文件' },
  { label: '字段映射' },
  { label: '执行导入' },
]

// ===== 步骤状态 =====
const activeStep = ref(0)
const selectedCompanyId = ref<string | null>(null)
const dataType = ref('trial_balance')
const fileList = ref<UploadFile[]>([])
const uploadRef = ref<UploadInstance>()

const companies = ref<Company[]>([])
const manualFiscalYear = ref<number | null>(null)
const manualPeriod = ref<number | null>(null)

// 6 个辅助字段（用户可自定义名称）
const auxFields = ref<{ name: string }[]>(
  Array.from({ length: 6 }, () => ({ name: '' }))
)

// ===== 步骤 2：映射 =====
const mappings = ref<MappingRow[]>([])
const previewRows = ref<Record<string, string>[]>([])
const previewHeaders = ref<string[]>([])
const missingFields = ref<string[]>([])
const previewing = ref(false)
const previewDone = ref(false)
const previewError = ref('')

// 字段选项（value 必须与后端 TYPE_FIELDS / KEYWORD_MAP 完全一致）
const fieldOptions: Record<string, { label: string; value: string }[]> = {
  trial_balance: [
    { label: '会计年度', value: 'fiscal_year' },
    { label: '会计期间', value: 'period' },
    { label: '科目编码', value: 'account_code' },
    { label: '科目名称', value: 'account_name' },
    { label: '科目级别', value: 'account_level' },
    { label: '期初借方余额', value: 'opening_debit' },
    { label: '期初贷方余额', value: 'opening_credit' },
    { label: '本期借方发生额', value: 'current_debit' },
    { label: '本期贷方发生额', value: 'current_credit' },
    { label: '期末借方余额', value: 'ending_debit' },
    { label: '期末贷方余额', value: 'ending_credit' },
  ],
  journal: [
    { label: '会计年度', value: 'fiscal_year' },
    { label: '会计期间', value: 'period' },
    { label: '凭证号', value: 'voucher_no' },
    { label: '凭证日期', value: 'voucher_date' },
    { label: '摘要', value: 'summary' },
    { label: '科目编码', value: 'account_code' },
    { label: '科目名称', value: 'account_name' },
    { label: '借方金额', value: 'debit_amount' },
    { label: '贷方金额', value: 'credit_amount' },
    { label: '附件数', value: 'attachment_count' },
  ],
  subsidiary: [
    { label: '会计年度', value: 'fiscal_year' },
    { label: '会计期间', value: 'period' },
    { label: '凭证号', value: 'voucher_no' },
    { label: '凭证日期', value: 'voucher_date' },
    { label: '摘要', value: 'summary' },
    { label: '科目编码', value: 'account_code' },
    { label: '科目名称', value: 'account_name' },
    { label: '借方金额', value: 'debit_amount' },
    { label: '贷方金额', value: 'credit_amount' },
    { label: '辅助核算类型', value: 'auxiliary_type' },
    { label: '辅助核算编码', value: 'auxiliary_code' },
    { label: '辅助核算名称', value: 'auxiliary_name' },
    { label: '附件数', value: 'attachment_count' },
  ],
}

const availableFields = computed(() => fieldOptions[dataType.value] || [])

// 统计
const mappedCount = computed(() =>
  mappings.value.filter((m) => m.field_key && m.field_key !== '__ignore__').length
)
const ignoredCount = computed(() =>
  mappings.value.filter((m) => m.field_key === '__ignore__').length
)
const ignoredColumns = computed(() =>
  mappings.value.filter((m) => m.field_key === '__ignore__')
)

// 获取辅助字段的实际名称（用于展示）
function auxFieldDisplayName(key: string): string {
  const match = key.match(/^__aux__(\d+)$/)
  if (!match) return key
  const idx = parseInt(match[1])
  return auxFields.value[idx]?.name || `辅助字段${idx + 1}`
}

// 文件中是否已包含年度/期间列
const fileHasFiscalYear = computed(() => mappings.value.some((m) => m.field_key === 'fiscal_year'))
const fileHasPeriod = computed(() => mappings.value.some((m) => m.field_key === 'period'))

// 是否可以下一步
const canNext = computed(
  () => selectedCompanyId.value && fileList.value.length > 0 && !previewing.value
)

// 下一步按钮禁用提示
const nextButtonHint = computed(() => {
  if (previewing.value) return ''
  if (!selectedCompanyId.value && fileList.value.length === 0) return '请选择被审计单位并上传文件'
  if (!selectedCompanyId.value) return '请先选择被审计单位'
  if (fileList.value.length === 0) return '请先上传文件'
  return ''
})

// 映射是否全部有效
const mappingValid = computed(() => {
  if (mappings.value.length === 0) return false
  const allDone = mappings.value.every((m) => !!m.field_key)
  if (!allDone) return false
  const mappedKeys = new Set(
    mappings.value.filter((m) => m.field_key !== '__ignore__').map((m) => m.field_key)
  )
  if (manualFiscalYear.value) mappedKeys.add('fiscal_year')
  if (manualPeriod.value) mappedKeys.add('period')
  return missingFields.value.every((f) => mappedKeys.has(f))
})

// 确认映射按钮提示
const mappingButtonHint = computed(() => {
  if (mappings.value.length === 0) return '暂无映射数据'
  if (!mappingValid.value) {
    const unmappedCount = mappings.value.filter((m) => !m.field_key).length
    return `还有 ${unmappedCount} 列未映射，请完成所有字段映射`
  }
  return ''
})

// 是否是系统级错误
const isSystemError = computed(() =>
  result.value.failures.length === 1 && result.value.failures[0].row === -1
)

// 步骤进度条宽度
const trackProgress = computed(() => {
  if (activeStep.value === 0) return '0%'
  if (activeStep.value === 1) return '50%'
  return '100%'
})

// 提取后端错误详情
function extractError(e: any, defaultMsg: string): string {
  return normalizeError(e, defaultMsg)
}

// 查找缺失字段的中文名
function missingFieldLabel(key: string): string {
  for (const opts of Object.values(fieldOptions)) {
    const found = opts.find((f) => f.value === key)
    if (found) return found.label
  }
  return key
}

// 将报错信息中的英文字段名替换为中文
function translateErrorMsg(msg: string): string {
  let result = msg
  for (const opts of Object.values(fieldOptions)) {
    for (const f of opts) {
      result = result.replace(new RegExp(`'${f.value}'`, 'g'), `「${f.label}」`)
    }
  }
  return result
}

// ===== 步骤 3 =====
const executing = ref(false)
const progress = ref(0)
const result = ref<ImportResultDisplay>({
  success_count: 0,
  fail_count: 0,
  failures: [],
})

// ===== 获取公司列表 =====
async function fetchCompanies() {
  try {
    const { data } = await api.get('/companies', { params: { page: 1, page_size: 100 } })
    companies.value = data.items
  } catch {
    ElMessage.error('获取公司列表失败')
  }
}

// ===== 文件变更 =====
function handleFileChange(file: UploadFile) {
  fileList.value = [file]
}

function handleFileRemove() {
  fileList.value = []
}

// ===== 步骤 1→2：调用预览 API =====
async function goPreview() {
  if (!fileList.value[0]?.raw) {
    ElMessage.warning('请先选择文件')
    return
  }

  previewing.value = true
  try {
    const formData = new FormData()
    formData.append('file', fileList.value[0].raw)
    formData.append('data_type', dataType.value)

    const { data } = await api.post<ImportPreviewResponse>('/imports/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })

    const matchedMap = data.matched
    const headers = data.headers
    const firstRow = data.preview_rows?.[0] || []

    const headerToField: Record<string, string> = {}
    for (const [fieldKey, headerName] of Object.entries(matchedMap)) {
      headerToField[headerName] = fieldKey
    }

    const newMappings: MappingRow[] = headers.map((headerName, colIndex) => {
      const fieldKey = headerToField[headerName] || null
      return {
        file_column: headerName,
        field_key: fieldKey,
        status: fieldKey ? 'matched' : 'unmatched',
        sample_value: firstRow[colIndex] || '',
      }
    })

    mappings.value = newMappings
    const manualFields: string[] = []
    if (manualFiscalYear.value) manualFields.push('fiscal_year')
    if (manualPeriod.value) manualFields.push('period')
    missingFields.value = (data.missing || []).filter((f) => !manualFields.includes(f))

    previewHeaders.value = headers
    previewRows.value = data.preview_rows.slice(0, 5).map((row) => {
      const obj: Record<string, string> = {}
      headers.forEach((h, i) => {
        obj[h] = row[i] ?? ''
      })
      return obj
    })

    previewError.value = ''
    previewDone.value = true
    activeStep.value = 1
  } catch (e: any) {
    const msg = extractError(e, '文件解析失败')
    previewError.value = msg
  } finally {
    previewing.value = false
  }
}

// ===== 步骤 2→3：调用执行 API =====
async function goExecute() {
  if (!fileList.value[0]?.raw || !selectedCompanyId.value) return

  executing.value = true
  activeStep.value = 2
  progress.value = 0

  const timer = setInterval(() => {
    progress.value = Math.min(92, progress.value + Math.floor(Math.random() * 8 + 3))
  }, 400)

  try {
    const columnMapping: Record<string, string> = {}
    for (const m of mappings.value) {
      if (m.field_key && m.field_key !== '__ignore__') {
        // 辅助字段 → 使用用户自定义名称
        const resolvedKey = m.field_key.startsWith('__aux__')
          ? auxFieldDisplayName(m.field_key)
          : m.field_key
        columnMapping[m.file_column] = resolvedKey
      }
    }

    const formData = new FormData()
    formData.append('file', fileList.value[0].raw)
    formData.append('company_id', String(selectedCompanyId.value))
    formData.append('data_type', dataType.value)
    formData.append('column_mapping', JSON.stringify(columnMapping))
    if (manualFiscalYear.value) formData.append('fiscal_year', String(manualFiscalYear.value))
    if (manualPeriod.value) formData.append('period', String(manualPeriod.value))

    const { data } = await api.post<ImportExecuteResponse>('/imports/execute', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })

    result.value = {
      success_count: data.success,
      fail_count: data.errors.length,
      failures: data.errors.map((e) => ({
        row: e.row,
        reason: translateErrorMsg(e.message),
      })),
    }
  } catch (e: any) {
    const msg = extractError(e, '导入失败')
    result.value = {
      success_count: 0,
      fail_count: 1,
      failures: [{ row: -1, reason: msg }],
    }
  } finally {
    clearInterval(timer)
    progress.value = 100
    executing.value = false
  }
}

// ===== 导航 =====
function goBackToMapping() {
  activeStep.value = 1
}

function resetImport() {
  activeStep.value = 0
  selectedCompanyId.value = null
  dataType.value = 'trial_balance'
  manualFiscalYear.value = null
  manualPeriod.value = null
  auxFields.value = Array.from({ length: 6 }, () => ({ name: '' }))
  fileList.value = []
  uploadRef.value?.clearFiles()
  mappings.value = []
  previewRows.value = []
  previewHeaders.value = []
  missingFields.value = []
  previewError.value = ''
  previewDone.value = false
  previewing.value = false
  executing.value = false
  progress.value = 0
  result.value = { success_count: 0, fail_count: 0, failures: [] }
}

onMounted(() => {
  fetchCompanies()
})
</script>

<style scoped>
/* ============================================================
   导入向导布局
   ============================================================ */

.import-wizard {
  max-width: var(--content-max-width);
  margin: 0 auto;
}

/* ===== 步骤轨道 ===== */
.wizard-track {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: var(--spacing-3) 0 var(--spacing-3);
  position: relative;
  margin-bottom: var(--spacing-2);
}

.track-line {
  position: absolute;
  top: 50%;
  left: calc(50% - 160px);
  right: calc(50% - 160px);
  height: 2px;
  background: var(--border-light);
  transform: translateY(-18px);
  z-index: 0;
}

.track-line-fill {
  height: 100%;
  background: var(--color-primary-500);
  transition: width var(--transition-slow);
  border-radius: 1px;
}

.track-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-1);
  z-index: 1;
  min-width: 80px;
}

.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  background: var(--bg-card);
  border: 2px solid var(--border-light);
  color: var(--text-placeholder);
  transition: all var(--transition-base);
}

.track-step.active .step-num {
  border-color: var(--color-primary-500);
  background: var(--color-primary-500);
  color: #fff;
}

.track-step.done .step-num {
  border-color: var(--color-success);
  background: var(--color-success);
  color: #fff;
}

.step-label {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  font-weight: var(--font-weight-medium);
}

.track-step.active .step-label {
  color: var(--color-primary-600);
}

.track-step.done .step-label {
  color: var(--color-success);
}

/* ===== 步骤面板 ===== */
.wizard-body {
  min-height: 360px;
}

.step-content {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
}

/* 步骤过渡 */
.step-fade-enter-active,
.step-fade-leave-active {
  transition: opacity var(--transition-base), transform var(--transition-base);
}

.step-fade-enter-from {
  opacity: 0;
  transform: translateX(16px);
}

.step-fade-leave-to {
  opacity: 0;
  transform: translateX(-16px);
}

/* ============================================================
   步骤 1：上传 + 配置
   ============================================================ */

.step1-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--spacing-6);
}

.panel-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0 0 var(--spacing-4);
}

.config-form {
  margin-top: var(--spacing-1);
}

.form-full {
  width: 100%;
}

.field-note {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  margin-top: 2px;
}

.field-note.required {
  color: var(--color-danger);
  font-weight: var(--font-weight-medium);
}

/* 文件要求 */
.file-requirements {
  margin-top: var(--spacing-3);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.req-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.req-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--color-primary-400);
  flex-shrink: 0;
}

/* 拖拽上传 */
.drag-upload {
  width: 100%;
}

.drag-upload :deep(.el-upload-dragger) {
  border: 2px dashed var(--border-base);
  border-radius: var(--radius-lg);
  padding: var(--spacing-8) var(--spacing-6);
  transition: border-color var(--transition-base), background var(--transition-base);
}

.drag-upload :deep(.el-upload-dragger:hover) {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.upload-icon {
  font-size: 36px;
  color: var(--color-primary-400);
  margin-bottom: var(--spacing-3);
}

.upload-text {
  color: var(--text-secondary);
  font-size: var(--font-size-base);
}

.upload-text em {
  color: var(--color-primary-500);
  font-style: normal;
  font-weight: var(--font-weight-medium);
}

/* 预览错误 */
.preview-error {
  margin-top: var(--spacing-5);
}

/* 操作按钮 */
.step-footer {
  margin-top: var(--spacing-6);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-3);
}

.footer-main-action {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.footer-hint {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  margin-bottom: var(--spacing-2);
}

/* ============================================================
   步骤 2：映射
   ============================================================ */

.step2-layout {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: var(--spacing-5);
}

.panel-header-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: var(--spacing-3);
}

.panel-meta {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

/* 映射表 */
.mapping-table-card,
.preview-card {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-bottom: var(--spacing-4);
}

.mapping-table :deep(.el-table__header th) {
  font-size: var(--font-size-xs);
  padding: 8px 0;
}

.mapping-table :deep(.el-table__body td) {
  padding: 6px 0;
}

.file-col-name {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  font-size: var(--font-size-sm);
}

.map-select {
  width: 100%;
}

.map-select :deep(.el-select-dropdown__wrap) {
  max-height: 200px !important;
}

.sample-val {
  background: var(--color-gray-100);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-family: var(--font-family-mono);
  color: var(--text-secondary);
}

/* 状态点 */
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.matched {
  background: var(--color-success);
}

.status-dot.unmatched {
  background: var(--color-warning);
}

.status-dot.ignored {
  background: var(--color-gray-400);
}

.sub-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0 0 var(--spacing-3);
}

/* ===== 右侧检查面板 ===== */
.step2-check {
  background: var(--color-gray-50);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  height: fit-content;
}

.check-block {
  margin-bottom: var(--spacing-4);
}

.check-block:last-child {
  margin-bottom: 0;
}

.check-block-title {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-regular);
  margin-bottom: var(--spacing-2);
}

.check-block-title.danger {
  color: var(--color-danger);
}

.check-block-title.muted {
  color: var(--text-placeholder);
}

.check-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-1);
  margin-bottom: var(--spacing-1);
}

.check-tag {
  font-size: var(--font-size-xs);
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  font-weight: var(--font-weight-medium);
}

.check-tag.danger {
  background: var(--color-danger-light);
  color: var(--color-danger-dark);
}

.check-hint {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

.check-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.check-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.check-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.check-dot.ok {
  background: var(--color-success);
}

.check-dot.warn {
  background: var(--color-warning);
}

.check-dot.muted {
  background: var(--color-gray-400);
}

.check-note {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

/* 辅助字段命名 */
.aux-name-row {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.aux-name-label {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  flex-shrink: 0;
  min-width: 42px;
}

.aux-name-input {
  flex: 1;
}

.aux-name-input :deep(.el-input__inner) {
  height: 28px;
  font-size: var(--font-size-xs);
}

.check-all-ok {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-sm);
  color: var(--color-success);
  font-weight: var(--font-weight-medium);
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--border-light);
}

/* ============================================================
   步骤 3：结果
   ============================================================ */

.importing {
  max-width: 420px;
  margin: var(--spacing-10) auto 0;
  text-align: center;
}

.importing-icon {
  color: var(--color-primary-400);
  margin-bottom: var(--spacing-4);
  animation: spin 1.4s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.importing h3 {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin-bottom: var(--spacing-5);
}

.import-progress {
  margin-bottom: var(--spacing-4);
}

.importing-note {
  font-size: var(--font-size-sm);
  color: var(--text-placeholder);
}

/* 结果区块 */
.result-block {
  max-width: 600px;
  margin: 0 auto;
}

.result-header {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-4);
  padding: var(--spacing-6);
  border-radius: var(--radius-lg);
  margin-bottom: var(--spacing-5);
}

.result-header h3 {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  margin: 0 0 var(--spacing-1);
  color: var(--text-primary);
}

.result-header p {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  margin: 0;
}

.result-header.success {
  background: #f0f9eb;
  border: 1px solid #b7e4a8;
}

.result-header.success .el-icon {
  color: var(--color-success);
}

.result-header.warning {
  background: #fdf6ec;
  border: 1px solid #f5dab1;
}

.result-header.warning .el-icon {
  color: var(--color-warning);
}

.result-header.error {
  background: #fef0f0;
  border: 1px solid #fbc4c4;
}

.result-header.error .el-icon {
  color: var(--color-danger);
}

.text-success { color: var(--color-success); }
.text-danger { color: var(--color-danger); }

/* 错误列表 */
.error-list-card {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-bottom: var(--spacing-5);
}

.error-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-2) var(--spacing-4);
  background: var(--color-gray-50);
  border-bottom: 1px solid var(--border-light);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-regular);
}

.error-list-hint {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

.error-list-body {
  max-height: 280px;
  overflow-y: auto;
}

.error-row {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-3);
  padding: var(--spacing-2) var(--spacing-4);
  font-size: var(--font-size-sm);
  border-bottom: 1px solid var(--border-lighter);
}

.error-row:last-child {
  border-bottom: none;
}

.error-row-num {
  flex-shrink: 0;
  min-width: 40px;
  font-family: var(--font-family-mono);
  color: var(--text-placeholder);
  font-size: var(--font-size-xs);
}

.error-row-msg {
  color: var(--text-regular);
  word-break: break-all;
}

/* 结果操作按钮 */
.result-actions {
  display: flex;
  justify-content: center;
  gap: var(--spacing-3);
}

/* ============================================================
   响应式
   ============================================================ */

@media (max-width: 1024px) {
  .step1-layout {
    grid-template-columns: 1fr;
  }

  .step2-layout {
    grid-template-columns: 1fr;
  }

  .step2-check {
    order: -1;
  }
}

@media (max-width: 768px) {
  .step-content {
    padding: var(--spacing-4);
  }

  .track-step {
    min-width: 60px;
  }

  .step-num {
    width: 24px;
    height: 24px;
    font-size: 11px;
  }

  .step-label {
    font-size: 10px;
  }

  .track-line {
    left: calc(50% - 120px);
    right: calc(50% - 120px);
  }

  .result-header {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
}

@media (max-width: 480px) {
  .step-content {
    padding: var(--spacing-3);
  }

  .step-footer {
    flex-direction: column;
  }

  .result-actions {
    flex-direction: column;
    align-items: center;
  }

  .result-actions .el-button {
    width: 100%;
    max-width: 240px;
  }

  /* 映射表/预览表横向滚动 */
  .mapping-table-card,
  .preview-card {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .mapping-table {
    min-width: 600px;
  }
}
</style>
