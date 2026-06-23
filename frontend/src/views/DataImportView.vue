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
        <!-- ====== 标准化导入流程 ====== -->
        <template v-if="isStandardized">
          <div v-if="activeStep === 0" key="std-step1" class="step-content">
            <h3 class="panel-title">上传客户科目余额表</h3>
            <p class="panel-desc">选择 Excel 或 CSV 文件，系统将自动解析表头和数据行。</p>
            <div class="step1-layout">
              <div class="step1-form">
                <el-form label-width="90px" label-position="top" class="config-form">
                  <el-form-item label="客户标识">
                    <el-input v-model="stdCustomerLabel" placeholder="被审计单位名称" clearable />
                  </el-form-item>
                  <el-row :gutter="12">
                    <el-col :span="12">
                      <el-form-item label="会计年度">
                        <el-input-number v-model="stdFiscalYear" :min="2000" :max="2100" placeholder="如 2025" controls-position="right" class="form-full" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="会计期间">
                        <el-input-number v-model="stdPeriod" :min="1" :max="12" placeholder="如 12" controls-position="right" class="form-full" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                </el-form>
              </div>
              <div class="step1-upload">
                <el-upload
                  ref="stdUploadRef"
                  :auto-upload="false"
                  :limit="1"
                  :on-change="stdHandleFileChange"
                  :on-remove="stdHandleFileRemove"
                  :file-list="stdFileList"
                  drag
                  accept=".xlsx,.csv,.xls"
                  class="drag-upload"
                >
                  <el-icon class="upload-icon"><UploadFilled /></el-icon>
                  <div class="upload-text">拖拽文件到此处，或 <em>点击上传</em></div>
                </el-upload>
              </div>
            </div>
            <div v-if="stdPreviewError" class="preview-error">
              <el-alert :title="stdPreviewError" type="error" :closable="true" show-icon @close="stdPreviewError = ''" />
            </div>
            <div class="step-footer">
              <div v-if="!stdCanPreview && !stdPreviewing && !stdPreviewError" class="footer-hint">
                <el-icon :size="14"><InfoFilled /></el-icon>
                {{ stdPreviewHint }}
              </div>
              <el-button type="primary" size="large" :disabled="!stdCanPreview" :loading="stdPreviewing" @click="stdGoPreview">
                {{ stdPreviewing ? '正在解析文件...' : '下一步：字段与金额映射' }}
                <el-icon v-if="!stdPreviewing" style="margin-left: 4px;"><ArrowRight /></el-icon>
              </el-button>
            </div>
          </div>

          <div v-else-if="activeStep === 1" key="std-step2" class="step-content">
            <h3 class="panel-title">字段映射与金额列配置</h3>
            <p class="panel-desc">将文件中的列映射到标准字段，并配置金额列的拆分方式。</p>

            <!-- 字段映射表 -->
            <h4 class="sub-title">字段映射</h4>
            <div class="mapping-table-card">
              <el-table :data="stdMappings" stripe size="small">
                <el-table-column label="文件列名" width="150">
                  <template #default="{ row }">{{ row.header_text }}<span class="file-col-index">（第{{ row.column_index + 1 }}列）</span></template>
                </el-table-column>
                <el-table-column label="映射到字段" min-width="200">
                  <template #default="{ row, $index }">
                    <el-select v-model="stdMappings[$index].field_name" placeholder="选择字段" size="small" class="map-select" @change="stdOnFieldChange($index)">
                      <el-option label="⊘ 忽略此列" value="__ignore__" />
                      <el-option-group label="科目信息">
                        <el-option label="客户科目代码" value="account_code" />
                        <el-option label="客户科目名称" value="account_name" />
                        <el-option label="余额方向" value="balance_direction" />
                        <el-option label="科目类别" value="account_category" />
                      </el-option-group>
                      <el-option-group label="金额列">
                        <el-option label="期初金额" value="opening_amount" />
                        <el-option label="本期发生额" value="current_amount" />
                        <el-option label="期末金额" value="ending_amount" />
                        <el-option label="期初借方" value="opening_debit" />
                        <el-option label="期初贷方" value="opening_credit" />
                        <el-option label="本期借方" value="current_debit" />
                        <el-option label="本期贷方" value="current_credit" />
                        <el-option label="期末借方" value="ending_debit" />
                        <el-option label="期末贷方" value="ending_credit" />
                      </el-option-group>
                      <el-option-group label="其他">
                        <el-option label="会计年度（文件含）" value="fiscal_year" />
                        <el-option label="会计期间（文件含）" value="period" />
                      </el-option-group>
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="金额模式" width="180" v-if="stdHasAmountFields">
                  <template #default="{ row }">
                    <template v-if="stdIsSingleAmountField(row.field_name)">
                      <el-select v-model="stdMappings[stdMappings.indexOf(row)].split_mode" placeholder="选择拆分方式" size="small" style="width:160px">
                        <el-option label="按标准方向拆分" value="single_by_direction" />
                        <el-option label="全部记入借方" value="single_as_debit" />
                        <el-option label="全部记入贷方" value="single_as_credit" />
                      </el-select>
                    </template>
                    <template v-else-if="stdIsDualAmountField(row.field_name)">
                      <el-tag size="small" type="info">借贷双列</el-tag>
                    </template>
                    <span v-else style="color:var(--text-placeholder)">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="示例" width="120" align="center">
                  <template #default="{ row }">
                    <code class="sample-val">{{ row.sample_value || '-' }}</code>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <!-- 层级模式 -->
            <h4 class="sub-title">层级识别模式</h4>
            <el-radio-group v-model="stdHierarchyMode" class="hierarchy-mode-group">
              <el-radio value="auto">自动（代码 + 缩进综合判断）</el-radio>
              <el-radio value="code">仅按科目代码前缀</el-radio>
              <el-radio value="indent">仅按 Excel 缩进</el-radio>
              <el-radio value="flat">平铺（不识别层级）</el-radio>
            </el-radio-group>

            <!-- 年度/期间 -->
            <h4 class="sub-title">导入期间</h4>
            <div class="period-confirm">
              <span>年度：{{ stdEffectiveFiscalYear }} · 期间：{{ stdEffectivePeriod }}月</span>
              <span v-if="!stdEffectiveFiscalYear" class="field-note required">请在上方文件列中映射年度列或手动填写</span>
            </div>

            <div class="step-footer">
              <el-button size="large" @click="stdStepBack">上一步</el-button>
              <el-button type="primary" size="large" :disabled="!stdCanAnalyze" :loading="stdAnalyzing" @click="stdGoAnalyze">
                {{ stdAnalyzing ? '正在分析数据...' : '下一步：层级与科目匹配' }}
              </el-button>
            </div>
          </div>

          <div v-else-if="activeStep === 2" key="std-step3" class="step-content">
            <div class="std-review-grid">
              <!-- 左侧：层级树 -->
              <div class="std-review-left">
                <h3 class="panel-title">科目层级确认</h3>
                <div v-if="stdHasWarnings" class="warning-block">
                  <el-alert type="warning" :closable="false" show-icon>
                    <template #title>
                      共 {{ stdWarnings.length }} 条警告需确认
                    </template>
                  </el-alert>
                </div>
                <el-table :data="stdFlatHierarchy" stripe size="small" max-height="400" row-key="row_index">
                  <el-table-column label="#" width="50" align="center">
                    <template #default="{ row }">{{ row.row_index + 1 }}</template>
                  </el-table-column>
                  <el-table-column prop="client_account_code" label="科目代码" width="120" />
                  <el-table-column prop="client_account_name" label="科目名称" min-width="140" />
                  <el-table-column label="层级" width="70" align="center">
                    <template #default="{ row }">
                      <el-tag v-if="row.is_summary" size="small" type="warning">父级</el-tag>
                      <el-tag v-else-if="row.is_leaf" size="small" type="success">末级</el-tag>
                      <span v-else>-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="来源" width="80">
                    <template #default="{ row }">
                      <span class="level-source-tag">{{ levelSourceLabel(row.level_source) }}</span>
                    </template>
                  </el-table-column>
                </el-table>

                <!-- 金额预览 -->
                <h4 class="sub-title" style="margin-top:16px">金额明细预览</h4>
                <el-table :data="stdFlatAmounts" stripe size="small" max-height="300">
                  <el-table-column label="#" width="50" align="center">
                    <template #default="{ row }">{{ row.row_index + 1 }}</template>
                  </el-table-column>
                  <el-table-column label="期初借" width="110" align="right">
                    <template #default="{ row }">{{ fmtAmount(row.opening_debit) }}</template>
                  </el-table-column>
                  <el-table-column label="期初贷" width="110" align="right">
                    <template #default="{ row }">{{ fmtAmount(row.opening_credit) }}</template>
                  </el-table-column>
                  <el-table-column label="本期借" width="110" align="right">
                    <template #default="{ row }">{{ fmtAmount(row.current_debit) }}</template>
                  </el-table-column>
                  <el-table-column label="本期贷" width="110" align="right">
                    <template #default="{ row }">{{ fmtAmount(row.current_credit) }}</template>
                  </el-table-column>
                  <el-table-column label="期末借" width="110" align="right">
                    <template #default="{ row }">{{ fmtAmount(row.ending_debit) }}</template>
                  </el-table-column>
                  <el-table-column label="期末贷" width="110" align="right">
                    <template #default="{ row }">{{ fmtAmount(row.ending_credit) }}</template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- 右侧：科目匹配 -->
              <div class="std-review-right">
                <h3 class="panel-title">科目匹配</h3>
                <p class="panel-desc">为每个客户科目确认对应的标准科目</p>

                <div v-if="stdBlockingErrors.length > 0" class="error-block">
                  <el-alert type="error" :closable="false" show-icon>
                    <template #title>
                      存在 {{ stdBlockingErrors.length }} 条阻止入库的错误
                    </template>
                  </el-alert>
                  <div v-for="e in stdBlockingErrors" :key="e.message" class="blocking-error-item">
                    {{ e.message }}
                  </div>
                </div>

                <div v-for="(rec, ri) in stdMappingRecs" :key="ri" class="match-row">
                  <div class="match-row-header">
                    <span class="match-client-label">
                      {{ rec.client_account_code || '?' }} {{ rec.client_account_name || '(无名称)' }}
                    </span>
                    <!-- 手动映射后显示已选标准科目 -->
                    <span v-if="stdSelectedMapping(ri) && !rec.candidates.some(c => c.standard_account_id === stdSelectedMapping(ri)!.standard_account_id)" class="manual-selected-badge">
                      <el-tag type="success" size="small">已选</el-tag>
                      <code class="manual-selected-code">{{ stdSelectedMapping(ri)!.standard_account_code }}</code>
                      <span class="manual-selected-name">{{ stdSelectedMapping(ri)!.standard_account_name }}</span>
                      <span class="manual-selected-source">（手动选择）</span>
                    </span>
                  </div>
                  <!-- 候选列表 -->
                  <div v-if="rec.candidates.length > 0" class="match-candidates">
                    <div
                      v-for="(c, ci) in rec.candidates.slice(0, 4)"
                      :key="ci"
                      class="match-candidate"
                      :class="{
                        selected: stdSelectedMapping(ri)?.standard_account_id === c.standard_account_id,
                        warning: !!c.warning
                      }"
                      @click="stdSelectCandidate(ri, c)"
                    >
                      <div class="mc-left">
                        <span class="mc-code">{{ c.standard_account_code }}</span>
                        <span class="mc-name">{{ c.standard_account_name }}</span>
                        <span class="mc-source">{{ matchSourceLabel(c.source) }}</span>
                        <span v-if="c.warning" class="mc-warning">{{ c.warning }}</span>
                      </div>
                      <div class="mc-right">
                        <el-tag v-if="stdSelectedMapping(ri)?.standard_account_id === c.standard_account_id" type="success" size="small">已选</el-tag>
                        <span v-else class="mc-score">{{ Math.round(c.score * 100) }}%</span>
                      </div>
                    </div>
                  </div>
                  <!-- 手动搜索 -->
                  <div class="match-search">
                    <el-input
                      v-model="stdSearchQueries[ri]"
                      size="small"
                      placeholder="搜索标准科目..."
                      clearable
                      @input="stdSearchAccounts(ri)"
                      style="width:200px"
                    />
                    <div v-if="stdSearchResults[ri]?.length" class="match-search-results">
                      <div
                        v-for="sr in stdSearchResults[ri].slice(0, 5)"
                        :key="sr.id"
                        class="match-search-item"
                        :class="{ disabled: !sr.is_active }"
                        @click="stdSelectSearchedAccount(ri, sr)"
                      >
                        <span>{{ sr.account_code }} {{ sr.account_name }}</span>
                        <el-tag v-if="!sr.is_active" size="small" type="danger">停用</el-tag>
                      </div>
                    </div>
                    <!-- 已手动选择时显示当前选择 + 清除按钮 -->
                    <div v-if="stdSelectedMapping(ri) && !stdSearchResults[ri]?.length && !stdSearchQueries[ri]" class="match-current-selection">
                      <el-tag type="success" size="small" closable @close="stdClearMapping(ri)">
                        {{ stdSelectedMapping(ri)!.standard_account_code }} {{ stdSelectedMapping(ri)!.standard_account_name }}
                      </el-tag>
                    </div>
                  </div>
                  <span v-if="!rec.candidates.length && !stdSelectedMapping(ri)" class="unmapped-hint">未匹配，请搜索标准科目</span>
                </div>
              </div>
            </div>

            <div class="step-footer">
              <el-button size="large" @click="stdStepBack">上一步</el-button>
              <el-button type="primary" size="large" :disabled="!stdCanConfirm" @click="stdGoConfirm">
                下一步：校验与确认
                <el-icon style="margin-left: 4px;"><ArrowRight /></el-icon>
              </el-button>
              <div v-if="!stdCanConfirm" class="footer-hint">
                <el-icon :size="14"><InfoFilled /></el-icon>
                {{ stdConfirmHint }}
              </div>
            </div>
          </div>

          <div v-else-if="activeStep === 3" key="std-step4" class="step-content">
            <h3 class="panel-title">校验与确认</h3>
            <p class="panel-desc">检查以下警告和错误，确认无误后方可执行最终入库。</p>

            <!-- 阻止项（必须先解决） -->
            <div v-if="stdBlockingErrors.length > 0" class="confirmation-section">
              <h4 class="sub-title">
                <el-icon :size="16" color="var(--color-danger)"><CircleCloseFilled /></el-icon>
                阻止入库项（{{ stdBlockingErrors.length }} 条）
              </h4>
              <el-alert type="error" :closable="false" show-icon class="confirmation-alert">
                <template #title>以下问题必须修正才能执行入库。请返回上一步完成科目映射。</template>
              </el-alert>
              <div class="confirmation-list">
                <div v-for="(e, i) in stdBlockingErrors" :key="'be'+i" class="confirmation-item error-item">
                  <el-tag size="small" type="danger">{{ errorCategoryLabel(e.category) }}</el-tag>
                  <span>{{ e.message }}</span>
                </div>
              </div>
            </div>

            <!-- 警告项（需用户确认） -->
            <div v-if="stdWarnings.length > 0" class="confirmation-section">
              <h4 class="sub-title">
                <el-icon :size="16" color="var(--color-warning)"><WarningFilled /></el-icon>
                警告项（{{ stdWarnings.length }} 条）
              </h4>
              <el-alert type="warning" :closable="false" show-icon class="confirmation-alert">
                <template #title>以下警告需要您确认。确认后仍可继续导入，但建议先检查数据。</template>
              </el-alert>
              <div class="confirmation-list">
                <div v-for="(w, i) in stdWarnings" :key="'w'+i" class="confirmation-item warning-item">
                  <el-tag size="small" type="warning">{{ warningCategoryLabel(w.category) }}</el-tag>
                  <span>{{ w.message }}</span>
                </div>
              </div>
            </div>

            <!-- 未映射科目 -->
            <div v-if="stdUnmappedCount > 0" class="confirmation-section">
              <h4 class="sub-title">
                <el-icon :size="16" color="var(--color-danger)"><CircleCloseFilled /></el-icon>
                未映射科目（{{ stdUnmappedCount }} 个）
              </h4>
              <el-alert type="error" :closable="false" show-icon>
                <template #title>还有 {{ stdUnmappedCount }} 个科目未映射到标准科目，请返回上一步完成映射。</template>
              </el-alert>
            </div>

            <!-- 全部通过时 -->
            <div v-if="stdBlockingErrors.length === 0 && stdWarnings.length === 0 && stdUnmappedCount === 0" class="confirmation-section">
              <el-alert type="success" :closable="false" show-icon>
                <template #title>所有检查已通过，可以执行入库。</template>
              </el-alert>
            </div>

            <!-- 警告确认复选框 -->
            <div v-if="stdWarnings.length > 0 && stdBlockingErrors.length === 0 && stdUnmappedCount === 0" class="warning-confirm-box">
              <el-checkbox v-model="stdWarningsConfirmed" size="large">
                <span class="warning-confirm-text">我已确认以上 {{ stdWarnings.length }} 条警告，了解可能的数据差异风险，仍然继续入库</span>
              </el-checkbox>
            </div>

            <!-- 映射摘要 -->
            <h4 class="sub-title" style="margin-top:16px">映射摘要</h4>
            <el-table :data="stdConfirmedMappingSummary" stripe size="small" max-height="300">
              <el-table-column label="客户科目代码" width="140">
                <template #default="{ row }">{{ row.client_account_code || '—' }}</template>
              </el-table-column>
              <el-table-column label="客户科目名称" min-width="150">
                <template #default="{ row }">{{ row.client_account_name || '—' }}</template>
              </el-table-column>
              <el-table-column label="→ 标准科目" width="200">
                <template #default="{ row }">
                  <code>{{ row.standard_account_code }}</code>
                  <span style="margin-left:6px;color:var(--text-secondary)">{{ row.standard_account_name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="来源" width="90" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.warning ? 'warning' : ''">{{ matchSourceLabel(row.source) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>

            <div class="step-footer">
              <el-button size="large" @click="stdStepBack">上一步：科目匹配</el-button>
              <el-button type="primary" size="large" :disabled="!stdCanExecute" :loading="stdExecuting" @click="stdGoExecute">
                {{ stdExecuting ? '正在执行导入...' : '确认并执行入库' }}
              </el-button>
              <div v-if="!stdCanExecute && !stdExecuting" class="footer-hint">
                <el-icon :size="14"><InfoFilled /></el-icon>
                {{ stdExecuteHint }}
              </div>
            </div>
          </div>

          <div v-else key="std-step5" class="step-content">
            <div v-if="stdExecuting" class="importing">
              <el-icon :size="40" class="importing-icon is-loading"><Loading /></el-icon>
              <h3>正在执行标准化导入...</h3>
              <el-progress :percentage="progress" :stroke-width="20" :text-inside="true" class="import-progress" />
              <p class="importing-note">正在生成标准科目余额表，请勿关闭页面</p>
            </div>
            <div v-else class="result-block">
              <div class="result-header" :class="stdExecuteError ? 'error' : 'success'">
                <el-icon :size="28"><component :is="stdExecuteError ? CircleCloseFilled : CircleCheckFilled" /></el-icon>
                <div>
                  <h3>{{ stdExecuteError ? '导入失败' : '标准化导入完成' }}</h3>
                  <p v-if="!stdExecuteError">
                    生成 {{ stdExecuteResult.entry_count }} 条标准科目余额表
                    · 保存 {{ stdExecuteResult.mapping_saved_count }} 条映射经验
                  </p>
                  <p v-else>{{ stdExecuteError }}</p>
                </div>
              </div>
              <div class="result-actions">
                <el-button type="primary" @click="stdResetImport">继续导入</el-button>
                <el-button @click="$router.push('/data/view')">查看数据</el-button>
              </div>
            </div>
          </div>
        </template>

        <!-- ====== 原有三步导入流程 ====== -->
        <template v-else>
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
                    <el-option label="科目余额表标准化导入" value="standardized_trial_balance" />
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
                  <el-table-column label="文件列名" width="160">
                    <template #default="{ row, $index }">
                      <span class="file-col-name">{{ row.file_column }}</span>
                      <span class="file-col-index">（第{{ $index + 1 }}列）</span>
                      <span v-if="row.suggestion_source" class="file-col-source">{{ sourceLabel(row.suggestion_source) }}</span>
                      <span v-if="row.suggestion_confidence" class="file-col-conf">{{ confidenceText(row.suggestion_confidence) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="映射到系统字段" min-width="200">
                    <template #default="{ row, $index }">
                      <el-select
                        v-model="mappings[$index].field_key"
                        :placeholder="row.field_key ? undefined : '选择字段…'"
                        size="small"
                        class="map-select"
                        popper-class="map-select-popper"
                        :teleported="true"
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

            <!-- 模板候选（TASK-024） -->
            <div v-if="templateCandidates.length > 0" class="template-candidates">
              <div class="tc-header">
                <span class="tc-title">推荐模板</span>
                <el-button size="small" text @click="cancelTemplateApply()">
                  {{ selectedTemplateId ? '取消套用' : '' }}
                </el-button>
              </div>
              <div
                v-for="tc in templateCandidates.slice(0, 3)"
                :key="tc.template_id"
                class="tc-card"
                :class="{ selected: selectedTemplateId === tc.template_id }"
                @click="applyTemplateCandidate(tc)"
              >
                <div class="tc-card-left">
                  <div class="tc-name">{{ tc.name }}</div>
                  <div class="tc-score">
                    匹配 {{ tc.score }} 分 ·
                    命中 {{ tc.matched_fields.length }} 字段 ·
                    缺 {{ tc.missing_fields.length }} 字段
                  </div>
                  <div v-if="tc.warnings.length" class="tc-warnings">
                    <span v-for="w in tc.warnings.slice(0,2)" :key="w">{{ w }}</span>
                  </div>
                </div>
                <div class="tc-card-right">
                  <el-tag v-if="selectedTemplateId === tc.template_id" type="success" size="small">已套用</el-tag>
                  <el-tag v-else size="small">点击套用</el-tag>
                </div>
              </div>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="step-footer">
            <el-button size="large" @click="activeStep = 0">上一步</el-button>
            <div class="footer-main-action">
              <el-checkbox
                v-model="rememberMapping"
                size="small"
              >记住本次字段映射，下次自动推荐</el-checkbox>
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
        </template>
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
const steps = computed(() => {
  if (dataType.value === 'standardized_trial_balance') {
    return [
      { label: '上传文件' },
      { label: '字段与金额映射' },
      { label: '层级与科目匹配' },
      { label: '校验与确认' },
      { label: '入库完成' },
    ]
  }
  return [
    { label: '上传文件' },
    { label: '字段映射' },
    { label: '执行导入' },
  ]
})

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

// 模板候选（TASK-024）
interface TemplateCandidate {
  template_id: string
  name: string
  score: number
  matched_fields: string[]
  missing_fields: string[]
  warnings: string[]
  source_label: string | null
}
const templateCandidates = ref<TemplateCandidate[]>([])
const selectedTemplateId = ref<string | null>(null)
const columnsInfo = ref<any[]>([])
const templateDefaultValues = ref<Record<string, any> | null>(null)
const rememberMapping = ref(true)

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
  // 模板默认值也能补齐年度/期间（仅当模板仍被选中时）
  if (selectedTemplateId.value && templateDefaultValues.value?.fiscal_year && !mappedKeys.has('fiscal_year')) {
    mappedKeys.add('fiscal_year')
  }
  if (selectedTemplateId.value && templateDefaultValues.value?.period && !mappedKeys.has('period')) {
    mappedKeys.add('period')
  }
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
  const total = steps.value.length
  if (activeStep.value === 0) return '0%'
  if (activeStep.value >= total - 1) return '100%'
  return `${Math.round((activeStep.value / (total - 1)) * 100)}%`
})

// 提取后端错误详情
function extractError(e: any, defaultMsg: string): string {
  return normalizeError(e, defaultMsg)
}

// 推荐来源中文标签
function sourceLabel(s: string | undefined): string {
  const map: Record<string, string> = {
    template: '导入模板',
    company_experience: '该客户历史确认',
    global_experience: '通用历史经验',
    keyword_match: '系统字段识别',
  }
  return map[s || ''] || ''
}

// 置信度格式化
function confidenceText(c: number | undefined): string {
  if (c === undefined || c === null) return ''
  return Math.round(c * 100) + '%'
}
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
    if (selectedCompanyId.value) {
      formData.append('company_id', String(selectedCompanyId.value))
    }

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
      const colInfo = columnsInfo.value[colIndex] || { column_id: `col_${String(colIndex + 1).padStart(3, '0')}` }
      const colId = colInfo.column_id
      const suggestion = data.mapping_suggestions_v2?.[colId]
      const autoField = (suggestion && suggestion.confidence >= 0.85) ? suggestion.target_field : fieldKey
      return {
        file_column: headerName,
        field_key: autoField,
        status: autoField ? 'matched' : 'unmatched',
        sample_value: firstRow[colIndex] || '',
        column_id: colId,
        column_index: colIndex,
        suggestion_source: suggestion?.source,
        suggestion_confidence: suggestion?.confidence,
        original_field_key: autoField,  // 自动填入的推荐字段，修改前即为确认基准
      }
    })

    // 模板候选 + 列信息（TASK-024）
    templateCandidates.value = data.template_candidates || []
    columnsInfo.value = data.columns || []
    selectedTemplateId.value = null
    templateDefaultValues.value = null

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
    const columnMappingV2: Record<string, string> = {}

    for (const m of mappings.value) {
      if (m.field_key && m.field_key !== '__ignore__') {
        const resolvedKey = m.field_key.startsWith('__aux__')
          ? auxFieldDisplayName(m.field_key)
          : m.field_key
        columnMapping[m.file_column] = resolvedKey

        // v2 映射：使用 column_id 而非表头文本
        const colInfo = columnsInfo.value.find((c: any) => c.index === mappings.value.indexOf(m))
        if (colInfo) {
          columnMappingV2[colInfo.column_id] = resolvedKey
        }
      }
    }

    const formData = new FormData()
    formData.append('file', fileList.value[0].raw)
    formData.append('company_id', String(selectedCompanyId.value))
    formData.append('data_type', dataType.value)
    formData.append('column_mapping', JSON.stringify(columnMapping))
    if (Object.keys(columnMappingV2).length > 0) {
      formData.append('column_mapping_v2', JSON.stringify(columnMappingV2))
    }
    if (selectedTemplateId.value) {
      formData.append('template_id', selectedTemplateId.value)
    }
    formData.append('remember_mapping', String(rememberMapping.value))

    // mapping_confirmations (TASK-034)
    const confirmations: Record<string, any> = {}
    for (const m of mappings.value) {
      if (m.field_key && m.field_key !== '__ignore__' && m.column_id) {
        const isInTargetFields = availableFields.value.some(f => f.value === m.field_key)
        if (!isInTargetFields) continue
        confirmations[m.column_id] = {
          target_field: m.field_key,
          confirmation_type: m.original_field_key === m.field_key ? 'user_confirmed' : 'user_corrected',
        }
      }
    }
    if (Object.keys(confirmations).length > 0) {
      formData.append('mapping_confirmations', JSON.stringify(confirmations))
    }

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

// 套用模板候选（TASK-024）
async function applyTemplateCandidate(tc: TemplateCandidate) {
  selectedTemplateId.value = tc.template_id
  try {
    const formData = new FormData()
    formData.append('file', fileList.value[0]!.raw as File)
    formData.append('data_type', dataType.value)
    formData.append('template_id', tc.template_id)

    const { data } = await api.post('/imports/preview', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })

    if (data.applied_mapping_v2) {
      const v2 = data.applied_mapping_v2 as Record<string, string>
      // 更新映射表：col_id → index → mapping row
      const colIdToIndex: Record<string, number> = {}
      for (const c of columnsInfo.value) {
        colIdToIndex[c.column_id] = c.index
      }
      for (const [colId, fieldKey] of Object.entries(v2)) {
        const idx = colIdToIndex[colId]
        if (idx !== undefined && idx < mappings.value.length) {
          mappings.value[idx].field_key = fieldKey
          mappings.value[idx].status = fieldKey ? 'matched' : 'unmatched'
          // 模板来源元数据 (TASK-037)
          mappings.value[idx].suggestion_source = 'template'
          mappings.value[idx].suggestion_confidence = 1.0
          mappings.value[idx].original_field_key = fieldKey
        }
      }
      // 捕获模板默认值
      templateDefaultValues.value = data.template_default_values || null
      ElMessage.success(`已套用模板：${tc.name}`)
    }
  } catch (e: any) {
    ElMessage.error(normalizeError(e, '模板套用失败'))
    selectedTemplateId.value = null
    templateDefaultValues.value = null
  }
}

// 取消套用模板（清理模板相关状态）
function cancelTemplateApply() {
  // 清除模板来源标记 (TASK-037)
  if (selectedTemplateId.value) {
    for (const m of mappings.value) {
      if (m.suggestion_source === 'template') {
        m.suggestion_source = undefined
        m.suggestion_confidence = undefined
        m.original_field_key = null  // 取消后不再以模板为基准 (TASK-038)
      }
    }
  }
  selectedTemplateId.value = null
  templateDefaultValues.value = null
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
  templateCandidates.value = []
  selectedTemplateId.value = null
  columnsInfo.value = []
  templateDefaultValues.value = null
  result.value = { success_count: 0, fail_count: 0, failures: [] }
}

onMounted(() => {
  fetchCompanies()
})

// ============================================================
// 标准化导入流程 — TASK-045
// ============================================================

const isStandardized = computed(() => dataType.value === 'standardized_trial_balance')

// 步骤 1：上传
const stdFileList = ref<UploadFile[]>([])
const stdUploadRef = ref<UploadInstance>()
const stdCustomerLabel = ref('')
const stdFiscalYear = ref<number | null>(null)
const stdPeriod = ref<number | null>(null)
const stdPreviewing = ref(false)
const stdPreviewError = ref('')
const stdBatchId = ref<string | null>(null)
const stdColumns = ref<import('@/types').StdColumnInfo[]>([])
const stdSampleRows = ref<Record<string, string>[]>([])
const stdTotalRows = ref(0)

const stdCanPreview = computed(() => stdFileList.value.length > 0 && !stdPreviewing.value)
const stdPreviewHint = computed(() => {
  if (stdFileList.value.length === 0) return '请先上传文件'
  return ''
})

function stdHandleFileChange(file: UploadFile) { stdFileList.value = [file] }
function stdHandleFileRemove() { stdFileList.value = [] }

async function stdGoPreview() {
  if (!stdFileList.value[0]?.raw) { ElMessage.warning('请先选择文件'); return }
  stdPreviewing.value = true
  stdPreviewError.value = ''
  try {
    const fd = new FormData()
    fd.append('file', stdFileList.value[0].raw)
    if (stdFiscalYear.value) fd.append('fiscal_year', String(stdFiscalYear.value))
    if (stdPeriod.value) fd.append('period', String(stdPeriod.value))
    if (stdCustomerLabel.value) fd.append('customer_label', stdCustomerLabel.value)

    const { data } = await api.post<import('@/types').StdPreviewResponse>(
      '/standard-trial-balance-imports/preview', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
    stdBatchId.value = data.batch_id
    stdColumns.value = data.columns
    stdSampleRows.value = data.sample_rows
    stdTotalRows.value = data.total_rows
    if (data.fiscal_year && !stdFiscalYear.value) stdFiscalYear.value = data.fiscal_year
    if (data.period && !stdPeriod.value) stdPeriod.value = data.period

    // 初始化映射
    stdInitMappings()
    activeStep.value = 1
  } catch (e: any) {
    stdPreviewError.value = normalizeError(e, '文件解析失败')
  } finally {
    stdPreviewing.value = false
  }
}

// 步骤 2：字段映射
interface StdMappingRow {
  column_id: string
  header_text: string
  column_index: number
  field_name: string
  split_mode?: string | null
  sample_value: string
}
const stdMappings = ref<StdMappingRow[]>([])
const stdHierarchyMode = ref('auto')

function stdInitMappings() {
  const cols = stdColumns.value
  const rows = stdSampleRows.value
  const first = rows[0] || {}
  stdMappings.value = cols.map(c => ({
    column_id: c.column_id,
    header_text: c.header_text,
    column_index: c.column_index,
    field_name: '',
    split_mode: null,
    sample_value: String(first[c.column_id] || ''),
  }))
}

const stdEffectiveFiscalYear = computed(() => {
  if (stdFiscalYear.value) return stdFiscalYear.value
  const hasYear = stdMappings.value.some(m => m.field_name === 'fiscal_year')
  return hasYear ? '(从文件中识别)' : null
})
const stdEffectivePeriod = computed(() => {
  if (stdPeriod.value) return stdPeriod.value
  const hasPer = stdMappings.value.some(m => m.field_name === 'period')
  return hasPer ? '(从文件中识别)' : null
})

const stdHasAmountFields = computed(() =>
  stdMappings.value.some(m => stdIsSingleAmountField(m.field_name) || stdIsDualAmountField(m.field_name))
)

function stdIsSingleAmountField(fn: string): boolean {
  return ['opening_amount', 'current_amount', 'ending_amount'].includes(fn)
}
function stdIsDualAmountField(fn: string): boolean {
  return ['opening_debit', 'opening_credit', 'current_debit', 'current_credit', 'ending_debit', 'ending_credit'].includes(fn)
}

function stdOnFieldChange(idx: number) {
  const m = stdMappings.value[idx]
  if (m && stdIsSingleAmountField(m.field_name)) {
    stdMappings.value[idx].split_mode = 'single_by_direction'
  } else if (m) {
    stdMappings.value[idx].split_mode = null
  }
}

const stdCanAnalyze = computed(() => {
  if (!stdBatchId.value) return false
  if (stdAnalyzing.value) return false
  const hasField = stdMappings.value.some(m => m.field_name && m.field_name !== '__ignore__')
  if (!hasField) return false
  // need at least a fiscal year
  if (!stdFiscalYear.value && !stdMappings.value.some(m => m.field_name === 'fiscal_year')) return false
  if (!stdPeriod.value && !stdMappings.value.some(m => m.field_name === 'period')) return false
  return true
})

// 步骤 3：分析结果
const stdAnalyzing = ref(false)
const stdHierarchy = ref<import('@/types').HierarchyInfo[]>([])
const stdMappingRecs = ref<import('@/types').MappingRecommendEntry[]>([])
const stdAmounts = ref<import('@/types').AmountInfo[]>([])
const stdErrors = ref<import('@/types').BlockingError[]>([])
const stdWarnings = ref<import('@/types').WarningItem[]>([])

// 用户确认的映射：row_index → candidate
const stdConfirmedMap = ref<Record<number, import('@/types').MappingCandidate | null>>({})

// 搜索
const stdSearchQueries = ref<Record<number, string>>({})
const stdSearchResults = ref<Record<number, any[]>>({})

async function stdGoAnalyze() {
  stdAnalyzing.value = true
  try {
    const fieldMappings: import('@/types').StdFieldMappingEntry[] = []
    for (const m of stdMappings.value) {
      if (!m.field_name || m.field_name === '__ignore__') continue
      const entry: import('@/types').StdFieldMappingEntry = {
        column_id: m.column_id,
        field_name: m.field_name,
      }
      if (stdIsSingleAmountField(m.field_name)) {
        entry.period_type = m.field_name === 'opening_amount' ? 'opening' : m.field_name === 'current_amount' ? 'current' : 'ending'
        entry.split_mode = m.split_mode || 'single_by_direction'
      } else if (['opening_debit', 'opening_credit'].includes(m.field_name)) {
        entry.period_type = 'opening'
        entry.split_mode = 'two_column'
      } else if (['current_debit', 'current_credit'].includes(m.field_name)) {
        entry.period_type = 'current'
        entry.split_mode = 'two_column'
      } else if (['ending_debit', 'ending_credit'].includes(m.field_name)) {
        entry.period_type = 'ending'
        entry.split_mode = 'two_column'
      }
      fieldMappings.push(entry)
    }

    // pair debit/credit columns
    for (const fm of fieldMappings) {
      if (fm.split_mode !== 'two_column') continue
      const pair = fm.field_name?.endsWith('_debit') ? fm.field_name.replace('_debit', '_credit') : fm.field_name?.endsWith('_credit') ? fm.field_name.replace('_credit', '_debit') : ''
      if (pair) {
        const other = fieldMappings.find(f => f.field_name === pair && f.period_type === fm.period_type)
        if (other) {
          if (fm.field_name?.endsWith('_debit')) { fm.debit_column_id = fm.column_id; fm.credit_column_id = other.column_id }
          else { fm.credit_column_id = fm.column_id; fm.debit_column_id = other.column_id }
        }
      }
    }

    const req: import('@/types').StdAnalyzeRequest = {
      field_mappings: fieldMappings,
      fiscal_year: stdFiscalYear.value || 2024,
      period: stdPeriod.value || 1,
      customer_label: stdCustomerLabel.value || null,
      source_label: null,
      hierarchy_mode: stdHierarchyMode.value,
    }

    const { data } = await api.post<import('@/types').StdAnalyzeResponse>(
      `/standard-trial-balance-imports/${stdBatchId.value}/analyze`, req
    )

    stdHierarchy.value = data.hierarchy
    stdMappingRecs.value = data.mapping_recommendations
    stdAmounts.value = data.amounts
    stdErrors.value = data.errors
    stdWarnings.value = data.warnings

    // 自动选中高置信度候选（非警告）
    stdConfirmedMap.value = {}
    for (let i = 0; i < data.mapping_recommendations.length; i++) {
      const rec = data.mapping_recommendations[i]
      const best = rec.candidates.find(c => !c.warning && c.score >= 0.9)
      if (best) {
        stdConfirmedMap.value[i] = best
      }
    }

    stdWarningsConfirmed.value = false
    activeStep.value = 2
  } catch (e: any) {
    ElMessage.error(normalizeError(e, '数据分析失败'))
  } finally {
    stdAnalyzing.value = false
  }
}

// 层级
const stdFlatHierarchy = computed(() => stdHierarchy.value)
const stdFlatAmounts = computed(() => stdAmounts.value)

// 动态计算阻止项：基于当前确认映射状态，而非 analyze 的静态错误快照
const stdBlockingErrors = computed(() => {
  const errors: Array<{ code: string; message: string; category: string; row_index: number | null }> = []

  // 检查是否有金额列使用"按标准方向拆分"
  const hasDirectionSplit = stdMappings.value.some(m =>
    m.split_mode === 'single_by_direction' &&
    (m.field_name === 'opening_amount' || m.field_name === 'current_amount' || m.field_name === 'ending_amount')
  )

  // 遍历所有映射推荐，动态检查未映射和方向缺失
  for (let i = 0; i < stdMappingRecs.value.length; i++) {
    const rec = stdMappingRecs.value[i]
    // 跳过没有代码也没有名称的行（无标识行，后端已在 analyze 中忽略）
    if (!rec.client_account_code && !rec.client_account_name) continue

    const cm = stdConfirmedMap.value[i]

    // 1. 未映射检查：有代码或名称的末级行必须有确认映射
    if (!cm) {
      errors.push({
        row_index: i,
        code: 'unmapped_account',
        message: `客户科目「${rec.client_account_code || '?'} ${rec.client_account_name || ''}」未映射到标准科目，请手动选择`,
        category: 'unmapped_account',
      })
      continue // 未映射则无需检查方向
    }

    // 2. 方向缺失检查：使用"按标准方向拆分"时，标准科目必须有余额方向
    if (hasDirectionSplit) {
      const dir = cm.standard_balance_direction
      if (!dir || dir === '') {
        errors.push({
          row_index: i,
          code: 'no_direction',
          message: `标准科目「${cm.standard_account_code} ${cm.standard_account_name}」余额方向为空，无法按标准方向拆分金额，请改为显式借/贷方`,
          category: 'no_direction',
        })
      }
    }
  }

  // 3. 保留真实数据缺陷（来自 analyze 的 missing_amount / missing_code_and_name）
  for (const e of stdErrors.value) {
    if (e.category === 'missing_amount' || e.category === 'missing_code_and_name') {
      errors.push(e)
    }
  }

  return errors
})

const stdHasWarnings = computed(() => stdWarnings.value.length > 0)

// 警告确认状态（步骤 3 中使用）
const stdWarningsConfirmed = ref(false)

function levelSourceLabel(s: string): string {
  const map: Record<string, string> = { code: '代码', indent: '缩进', flat: '平铺', indent_suggested: '缩进推断', auto: '自动' }
  return map[s] || s
}

function fmtAmount(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return '0.00'
  const n = typeof v === 'string' ? parseFloat(v) : v
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function matchSourceLabel(s: string): string {
  const map: Record<string, string> = {
    company_history: '该客户历史',
    global_history: '全局历史',
    code_match: '代码匹配',
    name_similarity: '名称相似',
    user_selected: '手动选择',
  }
  return map[s] || s
}

function stdSelectedMapping(ri: number): import('@/types').MappingCandidate | null {
  return stdConfirmedMap.value[ri] || null
}

function stdSelectCandidate(ri: number, candidate: import('@/types').MappingCandidate) {
  stdConfirmedMap.value[ri] = candidate
  // 切换映射后重置警告确认
  if (stdWarningsConfirmed.value) stdWarningsConfirmed.value = false
}

function stdClearMapping(ri: number) {
  delete stdConfirmedMap.value[ri]
  stdSearchQueries.value[ri] = ''
  stdSearchResults.value[ri] = []
}

// 未映射的末级科目数量
const stdUnmappedCount = computed(() => {
  let count = 0
  for (let i = 0; i < stdMappingRecs.value.length; i++) {
    const rec = stdMappingRecs.value[i]
    if (!rec.client_account_code && !rec.client_account_name) continue
    if (!stdConfirmedMap.value[i]) count++
  }
  return count
})

// 确认的映射摘要（用于步骤 3 展示）
const stdConfirmedMappingSummary = computed(() => {
  const summary: Array<{
    client_account_code: string | null
    client_account_name: string | null
    standard_account_code: string
    standard_account_name: string
    source: string
    warning: string | null
  }> = []
  for (let i = 0; i < stdMappingRecs.value.length; i++) {
    const rec = stdMappingRecs.value[i]
    const cm = stdConfirmedMap.value[i]
    if (!cm) continue
    summary.push({
      client_account_code: rec.client_account_code,
      client_account_name: rec.client_account_name,
      standard_account_code: cm.standard_account_code,
      standard_account_name: cm.standard_account_name,
      source: cm.source,
      warning: cm.warning,
    })
  }
  return summary
})

// 步骤 2 → 步骤 3 的启用条件：全部末级已映射、无阻止项
const stdCanConfirm = computed(() => {
  if (stdBlockingErrors.value.length > 0) return false
  if (stdUnmappedCount.value > 0) return false
  return true
})

const stdConfirmHint = computed(() => {
  if (stdUnmappedCount.value > 0) return `还有 ${stdUnmappedCount.value} 个科目未映射到标准科目`
  if (stdBlockingErrors.value.length > 0) return `还有 ${stdBlockingErrors.value.length} 条错误需要处理`
  return ''
})

// 步骤 3 最终执行启用条件：无阻止项、无未映射、警告已确认（如有）
const stdCanExecute = computed(() => {
  if (stdBlockingErrors.value.length > 0) return false
  if (stdUnmappedCount.value > 0) return false
  if (stdExecuting.value) return false
  // 有警告但未确认时，禁止执行
  if (stdWarnings.value.length > 0 && !stdWarningsConfirmed.value) return false
  return true
})

const stdExecuteHint = computed(() => {
  if (stdBlockingErrors.value.length > 0) return `还有 ${stdBlockingErrors.value.length} 条错误需要处理`
  if (stdUnmappedCount.value > 0) return `还有 ${stdUnmappedCount.value} 个科目未映射，请返回上一步完成映射`
  if (stdWarnings.value.length > 0 && !stdWarningsConfirmed.value) return `请先勾选确认以上 ${stdWarnings.value.length} 条警告`
  return ''
})

function errorCategoryLabel(cat: string): string {
  const map: Record<string, string> = {
    unmapped_account: '未映射',
    no_direction: '无方向',
    missing_amount: '缺金额',
    missing_code_and_name: '缺代码名称',
  }
  return map[cat] || cat
}

function warningCategoryLabel(cat: string): string {
  const map: Record<string, string> = {
    amount_mismatch: '金额不一致',
    negative_amount: '负数金额',
    disabled_mapping: '停用映射',
    global_candidate: '全局候选',
    indent_guess: '缩进推断',
    parent_amount_mismatch: '父级差异',
  }
  return map[cat] || cat
}

async function stdSearchAccounts(ri: number) {
  const q = (stdSearchQueries.value[ri] || '').trim()
  if (q.length < 1) { stdSearchResults.value[ri] = []; return }
  try {
    const { data } = await api.get('/standard-accounts', { params: { keyword: q, page_size: 10 } })
    stdSearchResults.value[ri] = data.items || []
  } catch { stdSearchResults.value[ri] = [] }
}

function stdSelectSearchedAccount(ri: number, sa: any) {
  if (!sa.is_active) {
    ElMessage.warning('该标准科目已停用，请选择启用的科目')
    return
  }
  const candidate: import('@/types').MappingCandidate = {
    standard_account_id: sa.id,
    standard_account_code: sa.account_code,
    standard_account_name: sa.account_name,
    score: 1.0,
    source: 'user_selected',
    reason: `用户手动选择 → ${sa.account_code} ${sa.account_name}`,
    warning: null,
    standard_balance_direction: sa.balance_direction,
  }
  stdConfirmedMap.value[ri] = candidate
  stdSearchQueries.value[ri] = ''
  stdSearchResults.value[ri] = []
  if (stdWarningsConfirmed.value) stdWarningsConfirmed.value = false
}

function stdGoConfirm() {
  // 重置警告确认状态
  stdWarningsConfirmed.value = false
  activeStep.value = 3
}

// 步骤 4：执行
const stdExecuting = ref(false)
const stdExecuteResult = ref<import('@/types').StdExecuteResponse>({
  batch_id: '', status: '', entry_count: 0, raw_row_count: 0, mapping_saved_count: 0, mapping_saved: []
})
const stdExecuteError = ref('')

async function stdGoExecute() {
  stdExecuting.value = true
  stdExecuteError.value = ''
  activeStep.value = 4
  progress.value = 0
  const timer = setInterval(() => { progress.value = Math.min(92, progress.value + Math.floor(Math.random() * 8 + 3)) }, 400)

  try {
    const confirmedMappings: import('@/types').ConfirmedMapping[] = []
    for (let i = 0; i < stdMappingRecs.value.length; i++) {
      const rec = stdMappingRecs.value[i]
      const cm = stdConfirmedMap.value[i]
      if (!cm) continue
      // find the hierarchy entry for this recommendation
      const hier = stdHierarchy.value.find(h =>
        (h.client_account_code || '') === (rec.client_account_code || '') &&
        (h.client_account_name || '') === (rec.client_account_name || '')
      )
      confirmedMappings.push({
        row_index: hier?.row_index ?? i,
        client_account_code: rec.client_account_code,
        client_account_name: rec.client_account_name,
        standard_account_id: cm.standard_account_id,
        standard_account_code: cm.standard_account_code,
        standard_account_name: cm.standard_account_name,
      })
    }

    const req: import('@/types').StdExecuteRequest = {
      confirmed_mappings: confirmedMappings,
      warnings_confirmed: stdWarningsConfirmed.value,
      save_mapping_experience: true,
    }

    const { data } = await api.post<import('@/types').StdExecuteResponse>(
      `/standard-trial-balance-imports/${stdBatchId.value}/execute`, req
    )
    stdExecuteResult.value = data
  } catch (e: any) {
    stdExecuteError.value = normalizeError(e, '标准化导入失败')
  } finally {
    clearInterval(timer)
    progress.value = 100
    stdExecuting.value = false
  }
}

function stdStepBack() {
  if (activeStep.value > 0) activeStep.value--
}

function stdResetImport() {
  activeStep.value = 0
  stdFileList.value = []
  stdUploadRef.value?.clearFiles()
  stdCustomerLabel.value = ''
  stdFiscalYear.value = null
  stdPeriod.value = null
  stdPreviewError.value = ''
  stdBatchId.value = null
  stdColumns.value = []
  stdSampleRows.value = []
  stdTotalRows.value = 0
  stdMappings.value = []
  stdHierarchyMode.value = 'auto'
  stdHierarchy.value = []
  stdMappingRecs.value = []
  stdAmounts.value = []
  stdErrors.value = []
  stdWarnings.value = []
  stdConfirmedMap.value = {}
  stdSearchQueries.value = {}
  stdSearchResults.value = {}
  stdWarningsConfirmed.value = false
  stdExecuteResult.value = { batch_id: '', status: '', entry_count: 0, raw_row_count: 0, mapping_saved_count: 0, mapping_saved: [] }
  stdExecuteError.value = ''
  progress.value = 0
}

// When switching to standardized type, clear existing state
import { watch } from 'vue'
watch(dataType, (newVal, oldVal) => {
  if (newVal === 'standardized_trial_balance' && oldVal !== 'standardized_trial_balance') {
    activeStep.value = 0
    previewDone.value = false
  }
  if (newVal !== 'standardized_trial_balance' && oldVal === 'standardized_trial_balance') {
    activeStep.value = 0
    stdResetImport()
  }
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
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: var(--spacing-5);
}

.step2-table {
  min-width: 0;
  max-width: 100%;
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
  overflow-x: auto;
  overflow-y: hidden;
  max-width: 100%;
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

.file-col-index {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  white-space: nowrap;
}

.file-col-source {
  font-size: var(--font-size-xs);
  color: var(--color-primary-600);
  white-space: nowrap;
  margin-left: var(--spacing-1);
}

.file-col-conf {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  white-space: nowrap;
}

.map-select {
  width: 100%;
  max-width: 220px;
}

:global(.map-select-popper .el-select-dropdown__wrap) {
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
  min-width: 0;
  max-width: 100%;
  overflow-wrap: break-word;
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
   模板候选（TASK-024）
   ============================================================ */
.template-candidates {
  margin-top: var(--spacing-4);
  padding: var(--spacing-3);
  background: var(--color-primary-50, #f0f5ff);
  border: 1px solid var(--color-primary-200, #bdd3f0);
  border-radius: var(--radius-md);
}
.tc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--spacing-2); }
.tc-title { font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); color: var(--text-primary); }

.tc-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--spacing-3);
  margin-bottom: var(--spacing-2);
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  transition: border-color var(--transition-fast);
}
.tc-card:hover { border-color: var(--color-primary-400); }
.tc-card.selected { border-color: var(--color-success); background: rgba(103, 194, 58, 0.04); }

.tc-card-left { min-width: 0; }
.tc-name { font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); }
.tc-score { font-size: var(--font-size-xs); color: var(--text-secondary); margin-top: 2px; }
.tc-warnings { font-size: var(--font-size-xs); color: var(--color-warning); margin-top: 2px; }
.tc-card-right { flex-shrink: 0; margin-left: var(--spacing-2); }

/* ============================================================
   标准化导入样式 — TASK-045
   ============================================================ */

.panel-desc {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  margin: 0 0 var(--spacing-4);
}

.hierarchy-mode-group {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

.period-confirm {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  font-size: var(--font-size-sm);
  color: var(--text-regular);
}

.std-review-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--spacing-5);
}

.std-review-left,
.std-review-right {
  min-width: 0;
}

.warning-block {
  margin-bottom: var(--spacing-3);
}

.error-block {
  margin-bottom: var(--spacing-3);
}

.blocking-error-item {
  font-size: var(--font-size-sm);
  color: var(--color-danger);
  padding: var(--spacing-1) 0;
  border-bottom: 1px solid var(--border-lighter);
}

.level-source-tag {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

.match-row {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--spacing-3);
  margin-bottom: var(--spacing-3);
}

.match-row-header {
  margin-bottom: var(--spacing-2);
}

.match-client-label {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.match-candidates {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: var(--spacing-2);
}

.match-candidate {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px var(--spacing-2);
  border: 1px solid var(--border-lighter);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color var(--transition-fast);
}
.match-candidate:hover { border-color: var(--color-primary-400); background: var(--color-primary-50); }
.match-candidate.selected { border-color: var(--color-success); background: rgba(103, 194, 58, 0.06); }
.match-candidate.warning { border-color: var(--color-warning); }

.mc-left { min-width: 0; }
.mc-code { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--text-primary); margin-right: var(--spacing-2); }
.mc-name { font-size: var(--font-size-sm); color: var(--text-regular); }
.mc-source { font-size: var(--font-size-xs); color: var(--text-placeholder); margin-left: var(--spacing-2); }
.mc-warning { font-size: var(--font-size-xs); color: var(--color-warning); display: block; margin-top: 2px; }
.mc-right { flex-shrink: 0; display: flex; align-items: center; gap: var(--spacing-2); }
.mc-score { font-size: var(--font-size-xs); color: var(--text-placeholder); }

.match-search {
  margin-top: var(--spacing-1);
  position: relative;
}

.match-search-results {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 10;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  max-height: 200px;
  overflow-y: auto;
  min-width: 240px;
}

.match-search-item {
  padding: 6px var(--spacing-3);
  font-size: var(--font-size-sm);
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.match-search-item:hover { background: var(--color-primary-50); }
.match-search-item.disabled { opacity: 0.5; cursor: not-allowed; }

.unmapped-hint {
  font-size: var(--font-size-xs);
  color: var(--color-danger);
}

.manual-selected-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-left: var(--spacing-3);
}

.manual-selected-code {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  color: var(--color-primary-600);
  background: rgba(59, 110, 165, 0.06);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
}

.manual-selected-name {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.manual-selected-source {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

.match-current-selection {
  margin-top: var(--spacing-1);
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

  .std-review-grid {
    grid-template-columns: 1fr;
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
