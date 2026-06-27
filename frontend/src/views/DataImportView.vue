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
                  <el-select
                    v-model="stdCustomerLabel"
                    placeholder="选择已有被审计单位，或直接输入名称"
                    filterable
                    allow-create
                    default-first-option
                    clearable
                    class="form-full"
                  >
                    <el-option
                      v-for="c in companies"
                      :key="c.id"
                      :label="c.code ? `${c.name}（${c.code}）` : c.name"
                      :value="c.name"
                    />
                  </el-select>
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
                  <template #default="{ row, $index }">
                    <template v-if="stdIsSingleAmountField(row.field_name)">
                      <el-select v-model="stdMappings[$index].split_mode" placeholder="选择拆分方式" size="small" style="width:160px">
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
            <div class="std-match-review">
              <div class="std-match-header">
                <div>
                  <h3 class="panel-title">层级与科目匹配（上级锚点 + 下级继承式映射）</h3>
                  <p class="panel-desc">普通二级、三级及以下明细默认继承最近锚点。会计性质变化时（如费用化/资本化、原值/备抵、应收/应付）建立新锚点。可对继承行单独映射为显式覆盖。</p>
                </div>
                <div class="std-match-header-actions">
                  <el-button size="small" @click="stdStepBack">上一步：字段映射</el-button>
                  <el-radio-group v-model="stdRowFilter" size="small" class="std-row-filter">
                    <el-radio-button value="all">全部 {{ stdReviewRows.length }}</el-radio-button>
                    <el-radio-button value="unmapped">未匹配 {{ stdUnmappedCount }}</el-radio-button>
                    <el-radio-button value="matched">已匹配 {{ stdMatchedCount }}</el-radio-button>
                    <el-radio-button value="ignored">已忽略 {{ stdIgnoredRowIndexes.length }}</el-radio-button>
                    <el-radio-button value="warning">有警告 {{ stdWarningRowCount }}</el-radio-button>
                  </el-radio-group>
                </div>
              </div>

              <!-- ANCHOR-INHERITANCE-MAPPING：映射计划统计 -->
              <div v-if="stdMappingSummary" class="std-anchor-stats">
                <div class="std-anchor-stat">
                  <div class="std-anchor-stat-value">{{ stdMappingSummary.anchor_count }}</div>
                  <div class="std-anchor-stat-label">映射锚点</div>
                </div>
                <div class="std-anchor-stat success">
                  <div class="std-anchor-stat-value">{{ stdMappingSummary.inherited_count }}</div>
                  <div class="std-anchor-stat-label">自动继承</div>
                </div>
                <div class="std-anchor-stat warning">
                  <div class="std-anchor-stat-value">{{ stdMappingSummary.breakpoint_count }}</div>
                  <div class="std-anchor-stat-label">继承中断点</div>
                </div>
                <div class="std-anchor-stat info">
                  <div class="std-anchor-stat-value">{{ stdMappingSummary.explicit_override_count }}</div>
                  <div class="std-anchor-stat-label">显式覆盖</div>
                </div>
                <div class="std-anchor-stat muted">
                  <div class="std-anchor-stat-value">{{ stdMappingSummary.structural_summary_count }}</div>
                  <div class="std-anchor-stat-label">结构汇总</div>
                </div>
                <div class="std-anchor-stat danger">
                  <div class="std-anchor-stat-value">{{ stdMappingSummary.unresolved_count }}</div>
                  <div class="std-anchor-stat-label">未解决</div>
                </div>
                <div class="std-anchor-stat emphasis">
                  <div class="std-anchor-stat-value">{{ stdMappingSummary.resolved_participating_leaf_count }}/{{ stdMappingSummary.participating_leaf_count }}</div>
                  <div class="std-anchor-stat-label">已解析/参与末级</div>
                </div>
              </div>

              <div v-if="stdHasWarnings || stdBlockingErrors.length > 0" class="std-table-alerts">
                <el-alert v-if="stdHasWarnings" type="warning" :closable="false" show-icon>
                  <template #title>共 {{ stdWarnings.length }} 条警告需确认，可用“有警告”筛选定位到相关行。</template>
                </el-alert>
                <el-alert v-if="stdBlockingErrors.length > 0" type="error" :closable="false" show-icon>
                  <template #title>存在 {{ stdBlockingErrors.length }} 条阻止入库的错误</template>
                </el-alert>
              </div>

              <div class="std-match-table-wrap">
                <el-table
                  :data="stdFilteredReviewRows"
                  stripe
                  size="small"
                  max-height="560"
                  row-key="row_index"
                  :row-class-name="stdReviewRowClassName"
                  scrollbar-always-on
                  class="std-match-table"
                >
                  <el-table-column label="行号" width="64" align="center" fixed="left">
                    <template #default="{ row }">{{ row.row_index + 1 }}</template>
                  </el-table-column>
                  <el-table-column label="客户科目代码" width="130" fixed="left">
                    <template #default="{ row }">
                      <code class="std-client-code">{{ row.client_account_code || '—' }}</code>
                    </template>
                  </el-table-column>
                  <el-table-column label="客户科目名称" width="180" fixed="left">
                    <template #default="{ row }">{{ row.client_account_name || '—' }}</template>
                  </el-table-column>
                  <el-table-column label="层级" width="120">
                    <template #default="{ row }">
                      <div class="std-level-cell">
                        <div class="std-level-tags">
                          <el-tag v-if="row.is_summary" size="small" type="warning">父级</el-tag>
                          <el-tag v-else-if="row.is_leaf" size="small" type="success">末级</el-tag>
                          <el-tag v-else size="small" type="info">普通行</el-tag>
                          <span>L{{ row.level ?? '—' }}</span>
                        </div>
                        <div v-if="row.parent_key" class="std-parent-key">父级：{{ row.parent_key }}</div>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="期初借方" width="140" align="right" class-name="std-amount-col">
                    <template #default="{ row }">{{ fmtAmount(row.amount?.opening_debit) }}</template>
                  </el-table-column>
                  <el-table-column label="期初贷方" width="140" align="right" class-name="std-amount-col">
                    <template #default="{ row }">{{ fmtAmount(row.amount?.opening_credit) }}</template>
                  </el-table-column>
                  <el-table-column label="本期借方" width="140" align="right" class-name="std-amount-col">
                    <template #default="{ row }">{{ fmtAmount(row.amount?.current_debit) }}</template>
                  </el-table-column>
                  <el-table-column label="本期贷方" width="140" align="right" class-name="std-amount-col">
                    <template #default="{ row }">{{ fmtAmount(row.amount?.current_credit) }}</template>
                  </el-table-column>
                  <el-table-column label="期末借方" width="140" align="right" class-name="std-amount-col">
                    <template #default="{ row }">{{ fmtAmount(row.amount?.ending_debit) }}</template>
                  </el-table-column>
                  <el-table-column label="期末贷方" width="140" align="right" class-name="std-amount-col">
                    <template #default="{ row }">{{ fmtAmount(row.amount?.ending_credit) }}</template>
                  </el-table-column>
                  <el-table-column label="匹配状态" width="110" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" :type="stdMappingRoleTagType(stdMappingRole(row))">
                        {{ stdMappingRoleLabel(stdMappingRole(row)) }}
                      </el-tag>
                      <div v-if="stdRowWarningMessages(row).length" class="std-row-warning-count">
                        {{ stdRowWarningMessages(row).length }} 条警告
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="当前标准科目" width="320">
                    <template #default="{ row }">
                      <div v-if="stdIsIgnored(row.row_index)" class="std-current-account ignored">已忽略，不导入</div>
                      <div v-else-if="!stdRowParticipates(row)" class="std-current-account muted">父级不入库</div>
                      <div v-else-if="stdMappingRole(row) === 'inherited' && !stdSelectedMapping(row.row_index)" class="std-current-account inherited">
                        <div>
                          <code>{{ row.rec?.resolved_standard_account_code }}</code>
                          <span>{{ row.rec?.resolved_standard_account_name }}</span>
                        </div>
                        <div class="std-inherit-meta" v-if="row.rec?.anchor_row_index !== null && row.rec?.anchor_row_index !== undefined">
                          继承自：
                          <code>{{ row.rec?.anchor_client_account_code || '?' }}</code>
                          {{ row.rec?.anchor_client_account_name || '?' }}
                        </div>
                        <div class="std-inherit-meta">自动继承，无需逐行确认</div>
                      </div>
                      <div v-else-if="stdMappingRole(row) === 'structural_summary'" class="std-current-account muted">
                        结构汇总节点，不参与映射
                      </div>
                      <div v-else-if="stdSelectedMapping(row.row_index)" class="std-current-account">
                        <div>
                          <code>{{ stdSelectedMapping(row.row_index)!.standard_account_code }}</code>
                          <span>{{ stdSelectedMapping(row.row_index)!.standard_account_name }}</span>
                        </div>
                        <div class="std-current-meta">
                          {{ matchSourceLabel(stdSelectedMapping(row.row_index)!.source) }} · 置信度 {{ stdConfidenceText(stdSelectedMapping(row.row_index)!.score) }}
                        </div>
                        <div v-if="stdMappingRole(row) === 'explicit_override'" class="std-inherit-meta">
                          显式覆盖继承
                        </div>
                        <div v-if="stdSelectedMapping(row.row_index)!.warning" class="std-current-warning">
                          {{ stdSelectedMapping(row.row_index)!.warning }}
                        </div>
                      </div>
                      <div v-else class="std-current-account unmapped">
                        未匹配
                        <span v-if="row.rec?.candidates.length">，有 {{ row.rec.candidates.length }} 个推荐候选</span>
                        <span v-else-if="row.rec?.resolved_standard_account_code">自动解析：{{ row.rec.resolved_standard_account_code }}</span>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="匹配操作" width="180" align="center">
                    <template #default="{ row }">
                      <template v-if="stdIsIgnored(row.row_index)">
                        <span class="std-action-muted">—</span>
                      </template>
                      <template v-else-if="stdMappingRole(row) === 'inherited' && !stdSelectedMapping(row.row_index)">
                        <el-button size="small" type="primary" plain @click="stdSetOverride(row.row_index)">单独映射</el-button>
                      </template>
                      <template v-else-if="stdMappingRole(row) === 'explicit_override' && stdSelectedMapping(row.row_index)">
                        <el-button size="small" @click="stdRestoreInheritance(row.row_index)">恢复继承</el-button>
                        <el-popover placement="left-start" trigger="click" width="360">
                          <template #reference>
                            <el-button size="small" type="primary" plain style="margin-left: 4px">更换</el-button>
                          </template>
                          <div class="std-account-picker">
                            <div class="std-picker-title">推荐候选</div>
                            <div v-if="row.rec?.candidates.length" class="std-candidate-list">
                              <button
                                v-for="c in row.rec.candidates.slice(0, 6)"
                                :key="c.standard_account_id"
                                type="button"
                                class="std-candidate-option"
                                :class="{
                                  selected: stdSelectedMapping(row.row_index)?.standard_account_id === c.standard_account_id,
                                  warning: !!c.warning
                                }"
                                @click="stdSelectCandidate(row.row_index, c)"
                              >
                                <span>
                                  <code>{{ c.standard_account_code }}</code>
                                  {{ c.standard_account_name }}
                                </span>
                                <span class="std-candidate-meta">
                                  {{ matchSourceLabel(c.source) }} · {{ stdConfidenceText(c.score) }}
                                </span>
                                <span v-if="c.warning" class="std-candidate-warning">{{ c.warning }}</span>
                              </button>
                            </div>
                            <div v-else class="std-picker-empty">暂无推荐候选，请搜索标准科目。</div>
                            <div class="std-picker-search">
                              <el-input
                                v-model="stdSearchQueries[row.row_index]"
                                size="small"
                                placeholder="搜索标准科目代码或名称"
                                clearable
                                @input="stdSearchAccounts(row.row_index)"
                              />
                              <div v-if="stdSearchResults[row.row_index]?.length" class="std-search-result-list">
                                <button
                                  v-for="sr in stdSearchResults[row.row_index].slice(0, 8)"
                                  :key="sr.id"
                                  type="button"
                                  class="std-search-result-item"
                                  :class="{ disabled: !sr.is_active }"
                                  @click="stdSelectSearchedAccount(row.row_index, sr)"
                                >
                                  <span>{{ sr.account_code }} {{ sr.account_name }}</span>
                                  <el-tag v-if="!sr.is_active" size="small" type="danger">停用</el-tag>
                                </button>
                              </div>
                            </div>
                            <el-button v-if="stdSelectedMapping(row.row_index)" size="small" type="danger" text @click="stdClearMapping(row.row_index)">
                              清除当前匹配
                            </el-button>
                          </div>
                        </el-popover>
                      </template>
                      <template v-else-if="stdRowCanSelect(row)">
                        <el-popover placement="left-start" trigger="click" width="360">
                          <template #reference>
                            <el-button size="small" type="primary" plain>
                              {{ stdSelectedMapping(row.row_index) ? '更换' : '选择' }}
                            </el-button>
                          </template>
                          <div class="std-account-picker">
                            <div class="std-picker-title">推荐候选</div>
                            <div v-if="row.rec?.candidates.length" class="std-candidate-list">
                              <button
                                v-for="c in row.rec.candidates.slice(0, 6)"
                                :key="c.standard_account_id"
                                type="button"
                                class="std-candidate-option"
                                :class="{
                                  selected: stdSelectedMapping(row.row_index)?.standard_account_id === c.standard_account_id,
                                  warning: !!c.warning
                                }"
                                @click="stdSelectCandidate(row.row_index, c)"
                              >
                                <span>
                                  <code>{{ c.standard_account_code }}</code>
                                  {{ c.standard_account_name }}
                                </span>
                                <span class="std-candidate-meta">
                                  {{ matchSourceLabel(c.source) }} · {{ stdConfidenceText(c.score) }}
                                </span>
                                <span v-if="c.warning" class="std-candidate-warning">{{ c.warning }}</span>
                              </button>
                            </div>
                            <div v-else class="std-picker-empty">暂无推荐候选，请搜索标准科目。</div>
                            <div class="std-picker-search">
                              <el-input
                                v-model="stdSearchQueries[row.row_index]"
                                size="small"
                                placeholder="搜索标准科目代码或名称"
                                clearable
                                @input="stdSearchAccounts(row.row_index)"
                              />
                              <div v-if="stdSearchResults[row.row_index]?.length" class="std-search-result-list">
                                <button
                                  v-for="sr in stdSearchResults[row.row_index].slice(0, 8)"
                                  :key="sr.id"
                                  type="button"
                                  class="std-search-result-item"
                                  :class="{ disabled: !sr.is_active }"
                                  @click="stdSelectSearchedAccount(row.row_index, sr)"
                                >
                                  <span>{{ sr.account_code }} {{ sr.account_name }}</span>
                                  <el-tag v-if="!sr.is_active" size="small" type="danger">停用</el-tag>
                                </button>
                              </div>
                            </div>
                            <el-button v-if="stdSelectedMapping(row.row_index)" size="small" type="danger" text @click="stdClearMapping(row.row_index)">
                              清除当前匹配
                            </el-button>
                          </div>
                        </el-popover>
                      </template>
                      <span v-else class="std-action-muted">无需操作</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="忽略" width="90" align="center">
                    <template #default="{ row }">
                      <template v-if="stdIsIgnored(row.row_index)">
                        <el-button size="small" @click="stdCancelIgnoreRow(row.row_index)">取消忽略</el-button>
                      </template>
                      <template v-else-if="stdRowCanSelect(row)">
                        <el-button size="small" type="warning" plain @click="stdIgnoreRow(row.row_index)">忽略</el-button>
                      </template>
                      <span v-else class="std-action-muted">—</span>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
              <div v-if="stdFilteredReviewRows.length === 0" class="std-empty-filter">当前筛选下没有行。</div>
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
                    <el-option label="科目余额表" value="standardized_trial_balance" />
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
import { isSafeCandidate, pickUniqueAutoConfirmCandidate, getAutoConfirmCandidate } from '@/utils/mappingCandidate'
import {
  rowMappingRole,
  rowRequiresMapping as utilRowRequiresMapping,
  rowCanSelectStandardAccount,
  rowShouldSubmitMapping,
  rowCanOverride as utilRowCanOverride,
  rowParticipatesInEntry as utilRowParticipates,
  rowDisplayStatus,
  buildAnchorOnlyConfirmedMappings as utilBuildAnchorOnlyConfirmed,
  applyExplicitOverride as utilApplyExplicitOverride,
  restoreInheritance as utilRestoreInheritance,
  computeStats,
  normalizeMappingRecommend,
} from '@/utils/anchorInheritanceMapping'
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
const dataType = ref('standardized_trial_balance')
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

const columnsInfo = ref<any[]>([])
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

    columnsInfo.value = data.columns || []

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

function resetImport() {
  activeStep.value = 0
  selectedCompanyId.value = null
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
  columnsInfo.value = []
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

// 字段映射自动识别：中文表头别名 → 标准字段名
// 命中后自动映射，用户仍可在下拉中手动修改。每个字段只分配给第一个命中的列。
const STD_HEADER_ALIASES: Record<string, string[]> = {
  account_code: ['科目编号', '科目代码', '科目编码', '编码', '代码', '科目号'],
  account_name: ['科目名称', '科目全称', '科目', '说明', '名称'],
  opening_debit: [
    '期初借方', '期初借', '本币期初借', '本币期初(借)', '本币期初借方',
    '期初借方余额', '年初借方余额', '年初借方',
    '期初余额_借方', '期初余额_借方_金额', '期初余额借方', '期初余额借方金额',
  ],
  opening_credit: [
    '期初贷方', '期初贷', '本币期初贷', '本币期初(贷)', '本币期初贷方',
    '期初贷方余额', '年初贷方余额', '年初贷方',
    '期初余额_贷方', '期初余额_贷方_金额', '期初余额贷方', '期初余额贷方金额',
  ],
  current_debit: [
    '本期借方', '本期借', '期间借方', '本币期间异动借', '本币期间异动(借)', '本期借方发生额',
    '本期发生_借方', '本期发生_借方_金额', '本期发生借方', '本期发生额_借方',
  ],
  current_credit: [
    '本期贷方', '本期贷', '期间贷方', '本币期间异动贷', '本币期间异动(贷)', '本期贷方发生额',
    '本期发生_贷方', '本期发生_贷方_金额', '本期发生贷方', '本期发生额_贷方',
  ],
  ending_debit: [
    '期末借方', '期末借', '本币期末借', '本币期末(借)', '期末借方余额',
    '期末余额_借方', '期末余额_借方_金额', '期末余额借方',
  ],
  ending_credit: [
    '期末贷方', '期末贷', '本币期末贷', '本币期末(贷)', '期末贷方余额',
    '期末余额_贷方', '期末余额_贷方_金额', '期末余额贷方',
  ],
  // 单列金额（按标准方向拆分）：常见「期初金额/本期金额/期末金额」单列格式
  opening_amount: ['期初金额', '期初余额', '本币期初金额'],
  current_amount: ['本期金额', '本期发生额', '本期发生', '本币本期金额'],
  ending_amount: ['期末金额', '期末余额', '本币期末金额'],
}

// 规范化表头用于别名匹配：去空格、NFKC、小写、去括号/分隔符
function stdNormalizeHeader(h: string): string {
  return String(h || '')
    .normalize('NFKC')
    .replace(/[\s_\-—–./\\:：;；,，()（）\[\]【】{}]/g, '')
    .toLowerCase()
}

// 根据表头文本自动推断字段名；未命中返回 ''
function stdGuessFieldByHeader(header: string, usedFields: Set<string>): string {
  const norm = stdNormalizeHeader(header)
  if (!norm) return ''
  // 优先精确匹配别名（规范化后比较）
  for (const [field, aliases] of Object.entries(STD_HEADER_ALIASES)) {
    if (usedFields.has(field)) continue
    for (const alias of aliases) {
      if (stdNormalizeHeader(alias) === norm) return field
    }
  }
  // 再做包含匹配（表头包含别名，如「本币期初借方余额」包含「期初借方」）
  for (const [field, aliases] of Object.entries(STD_HEADER_ALIASES)) {
    if (usedFields.has(field)) continue
    for (const alias of aliases) {
      const normAlias = stdNormalizeHeader(alias)
      if (normAlias && norm.includes(normAlias)) return field
    }
  }
  return ''
}

function stdInitMappings() {
  const cols = stdColumns.value
  const rows = stdSampleRows.value
  const first = rows[0] || {}
  const usedFields = new Set<string>()
  stdMappings.value = cols.map(c => {
    const field_name = stdGuessFieldByHeader(c.header_text, usedFields)
    if (field_name) usedFields.add(field_name)
    const split_mode = field_name && stdIsSingleAmountField(field_name) ? 'single_by_direction' : null
    return {
      column_id: c.column_id,
      header_text: c.header_text,
      column_index: c.column_index,
      field_name,
      split_mode,
      sample_value: String(first[c.column_id] || ''),
    }
  })
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
const stdAnalyzeResult = ref<import('@/types').StdAnalyzeResponse | null>(null)
const stdAmounts = ref<import('@/types').AmountInfo[]>([])
const stdErrors = ref<import('@/types').BlockingError[]>([])
const stdWarnings = ref<import('@/types').WarningItem[]>([])

type StdRowFilter = 'all' | 'unmapped' | 'matched' | 'ignored' | 'warning'
type StdReviewRow = {
  row_index: number
  client_account_code: string | null
  client_account_name: string | null
  level: number | null
  parent_key: string | null
  is_leaf: boolean
  is_summary: boolean
  participates_in_entry: boolean
  level_source: string
  hierarchy: import('@/types').HierarchyInfo | null
  amount: import('@/types').AmountInfo | null
  rec: import('@/types').MappingRecommendEntry | null
}

// 用户确认的映射：row_index → candidate
const stdConfirmedMap = ref<Record<number, import('@/types').MappingCandidate | null>>({})
const stdIgnoredRows = ref<Record<number, boolean>>({})
const stdRowFilter = ref<StdRowFilter>('all')

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

    // 前置校验：必须至少映射「客户科目代码」或「客户科目名称」之一，
    // 否则后端无法识别行身份，第三步会全部显示为空行（代码/名称为 —，未匹配 0）。
    const hasAccountIdentity = fieldMappings.some(
      fm => fm.field_name === 'account_code' || fm.field_name === 'account_name'
    )
    if (!hasAccountIdentity) {
      ElMessage.warning('请至少将一列映射为「客户科目代码」或「客户科目名称」，否则无法识别科目行。')
      return
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
    stdAnalyzeResult.value = data

    // TASK-087：使用后端 auto_confirm_candidate 进行安全自动选中
    stdConfirmedMap.value = {}
    stdIgnoredRows.value = {}
    stdSearchQueries.value = {}
    stdSearchResults.value = {}
    stdRowFilter.value = 'all'
    for (let i = 0; i < data.mapping_recommendations.length; i++) {
      const rec = data.mapping_recommendations[i]
      const rowIndex = stdRecommendationRowIndex(rec, i)
      // 优先使用后端决策，回退到前端安全判定
      const best = getAutoConfirmCandidate(rec.candidates, rec.auto_confirm_candidate)
      if (best) {
        stdConfirmedMap.value[rowIndex] = best
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

function stdRecommendationRowIndex(rec: import('@/types').MappingRecommendEntry, fallback: number): number {
  const maybeRec = rec as import('@/types').MappingRecommendEntry & { row_index?: number | null }
  return typeof maybeRec.row_index === 'number' ? maybeRec.row_index : fallback
}

const stdHierarchyByRow = computed(() => {
  const map = new Map<number, import('@/types').HierarchyInfo>()
  for (const item of stdHierarchy.value) map.set(item.row_index, item)
  return map
})

const stdAmountsByRow = computed(() => {
  const map = new Map<number, import('@/types').AmountInfo>()
  for (const item of stdAmounts.value) map.set(item.row_index, item)
  return map
})

const stdRecommendationsByRow = computed(() => {
  const map = new Map<number, import('@/types').MappingRecommendEntry>()
  for (let i = 0; i < stdMappingRecs.value.length; i++) {
    const rec = stdMappingRecs.value[i]
    map.set(stdRecommendationRowIndex(rec, i), rec)
  }
  return map
})

const stdWarningsByRow = computed(() => {
  const map = new Map<number, import('@/types').WarningItem[]>()
  for (const warning of stdWarnings.value) {
    if (typeof warning.row_index !== 'number') continue
    const items = map.get(warning.row_index) || []
    items.push(warning)
    map.set(warning.row_index, items)
  }
  return map
})

const stdReviewRows = computed<StdReviewRow[]>(() => {
  const rowIndexes = new Set<number>()
  for (const item of stdHierarchy.value) rowIndexes.add(item.row_index)
  for (const item of stdAmounts.value) rowIndexes.add(item.row_index)
  for (let i = 0; i < stdMappingRecs.value.length; i++) {
    rowIndexes.add(stdRecommendationRowIndex(stdMappingRecs.value[i], i))
  }

  return Array.from(rowIndexes).sort((a, b) => a - b).map((rowIndex) => {
    const hierarchy = stdHierarchyByRow.value.get(rowIndex) || null
    const amount = stdAmountsByRow.value.get(rowIndex) || null
    const rec = stdRecommendationsByRow.value.get(rowIndex) || null
    const isSummary = rec?.is_summary ?? hierarchy?.is_summary ?? false
    const isLeaf = rec?.is_leaf ?? hierarchy?.is_leaf ?? !isSummary
    const participates = rec?.participates_in_entry ?? (isLeaf && !isSummary)

    return {
      row_index: rowIndex,
      client_account_code: hierarchy?.client_account_code ?? rec?.client_account_code ?? null,
      client_account_name: hierarchy?.client_account_name ?? rec?.client_account_name ?? null,
      level: hierarchy?.level ?? null,
      parent_key: hierarchy?.parent_key ?? null,
      is_leaf: isLeaf,
      is_summary: isSummary,
      participates_in_entry: participates,
      level_source: hierarchy?.level_source ?? '',
      hierarchy,
      amount,
      rec,
    }
  })
})

const stdIgnoredRowIndexes = computed(() =>
  Object.keys(stdIgnoredRows.value)
    .map(Number)
    .filter(rowIndex => stdIgnoredRows.value[rowIndex])
    .sort((a, b) => a - b)
)

function stdRowHasIdentity(row: StdReviewRow): boolean {
  return !!(row.client_account_code || row.client_account_name)
}

/**
 * TASK-092：该行是否需要显示标准科目选择器。
 * 非末级 anchor（如 银行存款）也需要显示选择器，所以不能仅看 participates_in_entry。
 */
function stdRowCanSelect(row: StdReviewRow): boolean {
  if (stdIsIgnored(row.row_index)) return false
  return rowCanSelectStandardAccount({
    row_index: row.row_index,
    client_account_code: row.client_account_code,
    client_account_name: row.client_account_name,
    is_leaf: row.is_leaf,
    is_summary: row.is_summary,
    participates_in_entry: row.participates_in_entry,
    rec: row.rec,
    is_ignored: !!stdIgnoredRows.value[row.row_index],
  })
}

/**
 * TASK-092：该行是否参与金额入库。
 * 委托给 util.rowParticipatesInEntry — 该函数基于 mapping_role 判定，
 * 不会把非末级 anchor 错误地排除。
 */
function stdRowParticipates(row: StdReviewRow): boolean {
  return utilRowParticipates({
    row_index: row.row_index,
    client_account_code: row.client_account_code,
    client_account_name: row.client_account_name,
    is_leaf: row.is_leaf,
    is_summary: row.is_summary,
    participates_in_entry: row.participates_in_entry,
    rec: row.rec,
    is_ignored: !!stdIgnoredRows.value[row.row_index],
  })
}

function stdIsIgnored(rowIndex: number): boolean {
  return !!stdIgnoredRows.value[rowIndex]
}

/**
 * TASK-092：该行是否需要用户在前端做映射选择。
 * 委托给 util.rowRequiresMapping — 基于 mapping_role + requires_confirmation 判定，
 * inherited / structural_summary / ignored 都不计入未映射。
 */
function stdRowRequiresMapping(row: StdReviewRow): boolean {
  if (!stdRowHasIdentity(row)) return false
  return utilRowRequiresMapping({
    row_index: row.row_index,
    client_account_code: row.client_account_code,
    client_account_name: row.client_account_name,
    is_leaf: row.is_leaf,
    is_summary: row.is_summary,
    participates_in_entry: row.participates_in_entry,
    rec: row.rec,
    is_ignored: !!stdIgnoredRows.value[row.row_index],
  })
}

function stdRowWarningMessages(row: StdReviewRow): string[] {
  const messages: string[] = []
  for (const warning of stdWarningsByRow.value.get(row.row_index) || []) messages.push(warning.message)
  for (const warning of row.amount?.warnings || []) messages.push(warning)
  const selected = stdSelectedMapping(row.row_index)
  if (selected?.warning) messages.push(selected.warning)
  for (const candidate of row.rec?.candidates || []) {
    if (candidate.warning) messages.push(candidate.warning)
  }
  return Array.from(new Set(messages))
}

function stdRowStatus(row: StdReviewRow): { label: string; type: '' | 'success' | 'warning' | 'info' | 'danger' } {
  if (stdIsIgnored(row.row_index)) return { label: '已忽略', type: 'info' }
  if (!stdRowParticipates(row)) return { label: '父级不入库', type: 'warning' }
  if (stdSelectedMapping(row.row_index)) return { label: '已匹配', type: 'success' }
  return { label: '未匹配', type: 'danger' }
}

function stdConfidenceText(score: number | null | undefined): string {
  if (typeof score !== 'number' || Number.isNaN(score)) return '—'
  return `${Math.round(score * 100)}%`
}

function stdReviewRowClassName({ row }: { row: StdReviewRow }): string {
  if (stdIsIgnored(row.row_index)) return 'std-row-ignored'
  if (!stdRowParticipates(row)) return 'std-row-parent'
  if (stdRowRequiresMapping(row) && !stdSelectedMapping(row.row_index)) return 'std-row-unmapped'
  return ''
}

const stdMatchedCount = computed(() =>
  stdReviewRows.value.filter(row => stdRowRequiresMapping(row) && !!stdSelectedMapping(row.row_index)).length
)

const stdWarningRowCount = computed(() =>
  stdReviewRows.value.filter(row => stdRowWarningMessages(row).length > 0).length
)

const stdFilteredReviewRows = computed(() => {
  switch (stdRowFilter.value) {
    case 'unmapped':
      return stdReviewRows.value.filter(row => stdRowRequiresMapping(row) && !stdSelectedMapping(row.row_index))
    case 'matched':
      return stdReviewRows.value.filter(row => stdRowRequiresMapping(row) && !!stdSelectedMapping(row.row_index))
    case 'ignored':
      return stdReviewRows.value.filter(row => stdIsIgnored(row.row_index))
    case 'warning':
      return stdReviewRows.value.filter(row => stdRowWarningMessages(row).length > 0)
    default:
      return stdReviewRows.value
  }
})

function stdReviewRowByIndex(rowIndex: number | null | undefined): StdReviewRow | null {
  if (typeof rowIndex !== 'number') return null
  return stdReviewRows.value.find(row => row.row_index === rowIndex) || null
}

function stdBackendErrorStillBlocks(error: import('@/types').BlockingError): boolean {
  if (error.category === 'unmapped_account' || error.category === 'no_direction') return false
  if (typeof error.row_index !== 'number') return true
  if (stdIsIgnored(error.row_index)) return false
  const row = stdReviewRowByIndex(error.row_index)
  if (row && !stdRowParticipates(row)) return false
  return true
}

// 动态计算阻止项：基于当前确认映射状态，而非 analyze 的静态错误快照
const stdBlockingErrors = computed(() => {
  const errors: Array<{ code: string; message: string; category: string; row_index: number | null }> = []

  // 检查是否有金额列使用"按标准方向拆分"
  const hasDirectionSplit = stdMappings.value.some(m =>
    m.split_mode === 'single_by_direction' &&
    (m.field_name === 'opening_amount' || m.field_name === 'current_amount' || m.field_name === 'ending_amount')
  )

  // 遍历参与入库的当前行，动态检查方向缺失。未映射由 stdUnmappedCount 单独统计。
  for (const row of stdReviewRows.value) {
    if (!stdRowRequiresMapping(row)) continue
    const cm = stdSelectedMapping(row.row_index)
    if (!cm) continue

    // 使用"按标准方向拆分"时，标准科目必须有余额方向
    if (hasDirectionSplit) {
      const dir = cm.standard_balance_direction
      if (!dir || dir === '') {
        errors.push({
          row_index: row.row_index,
          code: 'no_direction',
          message: `标准科目「${cm.standard_account_code} ${cm.standard_account_name}」余额方向为空，无法按标准方向拆分金额，请改为显式借/贷方`,
          category: 'no_direction',
        })
      }
    }
  }

  // 保留真实数据缺陷；已忽略行和父级不入库行不再阻止。
  for (const e of stdErrors.value) {
    if (stdBackendErrorStillBlocks(e)) errors.push(e)
  }

  return errors
})

const stdHasWarnings = computed(() => stdWarnings.value.length > 0)

// 警告确认状态（步骤 3 中使用）
const stdWarningsConfirmed = ref(false)

function levelSourceLabel(s: string): string {
  const map: Record<string, string> = {
    code: '代码', code_prefix: '代码前缀', indent: '缩进',
    flat: '平铺', indent_suggested: '缩进推断', auto: '自动',
  }
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
    code_match_conflict: '代码冲突',
    name_exact: '名称精确',
    name_similarity: '名称相似',
    code_prefix_parent: '代码前缀',
    code_category_anchor: '代码类别',
    category_prefix: '类别前缀',
    name_anchor: '名称锚点',
    semantic_alias: '语义匹配',
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

// ANCHOR-INHERITANCE-MAPPING：映射角色辅助函数
function stdMappingRole(row: any): string {
  return row?.rec?.mapping_role || 'unresolved'
}

function stdMappingRoleLabel(role: string): string {
  const map: Record<string, { label: string; type: string }> = {
    anchor: { label: '映射锚点', type: 'primary' },
    inherited: { label: '自动继承', type: 'success' },
    breakpoint: { label: '继承中断点', type: 'warning' },
    explicit_override: { label: '显式覆盖', type: 'info' },
    structural_summary: { label: '结构汇总', type: 'info' },
    unresolved: { label: '未解决', type: 'danger' },
    ignored: { label: '已忽略', type: 'info' },
  }
  return map[role]?.label || role
}

function stdMappingRoleTagType(role: string): string {
  const map: Record<string, string> = {
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

// ANCHOR-INHERITANCE-MAPPING：是否允许"单独映射"（普通继承行）
function stdCanOverride(row: any): boolean {
  const role = stdMappingRole(row)
  return role === 'inherited' || role === 'anchor' || role === 'breakpoint'
}

// ANCHOR-INHERITANCE-MAPPING：恢复继承（清除单独映射）
function stdRestoreInheritance(rowIndex: number) {
  delete stdConfirmedMap.value[rowIndex]
  stdSearchQueries.value[rowIndex] = ''
  stdSearchResults.value[rowIndex] = []
  if (stdWarningsConfirmed.value) stdWarningsConfirmed.value = false
}

// ANCHOR-INHERITANCE-MAPPING：单独映射（继承行变 explicit_override）
function stdSetOverride(rowIndex: number) {
  const row = stdReviewRowByIndex(rowIndex)
  if (!row) return
  // 给当前行设为「显式覆盖」锚点标记
  // 这里通过在 stdConfirmedMap 中加入一行并标记 source
  // 后端会在 execute 阶段把它当作 explicit_override 处理
  // 弹窗让用户选标准科目
  stdSearchQueries.value[rowIndex] = ''
  stdSearchResults.value[rowIndex] = []
  // 标记为待用户选择：保留 rec 候选即可
  // 实际由用户点击「选择」后走 stdSelectCandidate
}

// 忽略行：只能忽略参与入库的末级行
function stdIgnoreRow(rowIndex: number) {
  const row = stdReviewRowByIndex(rowIndex)
  if (!row) {
    ElMessage.warning('未找到该行，无法忽略')
    return
  }
  // 只有参与入库的末级行可以忽略；父级行、无身份空行不允许忽略
  if (!stdRowParticipates(row)) {
    ElMessage.warning('该行不是参与入库的末级科目，无需忽略')
    return
  }
  // 设置忽略标记
  stdIgnoredRows.value[rowIndex] = true
  // 清除该行已确认的映射
  delete stdConfirmedMap.value[rowIndex]
  // 清除该行搜索框和搜索结果
  stdSearchQueries.value[rowIndex] = ''
  stdSearchResults.value[rowIndex] = []
  // 忽略会改变行级状态，重置警告确认
  if (stdWarningsConfirmed.value) stdWarningsConfirmed.value = false
}

// 取消忽略行
function stdCancelIgnoreRow(rowIndex: number) {
  delete stdIgnoredRows.value[rowIndex]
  // 取消忽略会改变行级状态，重置警告确认
  if (stdWarningsConfirmed.value) stdWarningsConfirmed.value = false
  // TASK-087：使用安全判定逻辑重新自动选中
  const row = stdReviewRowByIndex(rowIndex)
  if (row && !stdConfirmedMap.value[rowIndex]) {
    const best = getAutoConfirmCandidate(
      row.rec?.candidates || [],
      row.rec?.auto_confirm_candidate
    )
    if (best) {
      stdConfirmedMap.value[rowIndex] = best
    }
  }
}

// 未映射的末级科目数量（基于行级状态：参与入库且需匹配但未选择的行）
const stdUnmappedCount = computed(() => {
  let count = 0
  for (const row of stdReviewRows.value) {
    // 已忽略、父级不入库、无身份空行都不计未匹配
    if (!stdRowRequiresMapping(row)) continue
    if (!stdSelectedMapping(row.row_index)) count++
  }
  return count
})

// 确认的映射摘要（用于步骤 3 展示）：基于 stdReviewRows 按 row_index 汇总
const stdConfirmedMappingSummary = computed(() => {
  const summary: Array<{
    row_index: number
    client_account_code: string | null
    client_account_name: string | null
    standard_account_code: string
    standard_account_name: string
    source: string
    warning: string | null
  }> = []
  for (const row of stdReviewRows.value) {
    // 已忽略行不进入摘要；父级不入库行不进入摘要
    if (stdIsIgnored(row.row_index)) continue
    if (!stdRowParticipates(row)) continue
    const cm = stdSelectedMapping(row.row_index)
    if (!cm) continue
    // 使用行级 rec/client_account_code/client_account_name，不靠代码名称回找 hierarchy
    summary.push({
      row_index: row.row_index,
      client_account_code: row.rec?.client_account_code ?? row.client_account_code ?? null,
      client_account_name: row.rec?.client_account_name ?? row.client_account_name ?? null,
      standard_account_code: cm.standard_account_code,
      standard_account_name: cm.standard_account_name,
      source: cm.source,
      warning: cm.warning,
    })
  }
  return summary
})

// ANCHOR-INHERITANCE-MAPPING：映射计划统计
const stdMappingSummary = computed(() => {
  return (stdAnalyzeResult.value as any)?.mapping_summary
})

// ANCHOR-INHERITANCE-MAPPING v2：仅提交锚点 / 显式覆盖
// 普通 inherited 行不进入提交，让后端通过继承映射计划自动解析
function stdBuildAnchorOnlyConfirmedMappings(): import('@/types').ConfirmedMapping[] {
  const rows = stdReviewRows.value
  const selectedByRow: Record<number, import('@/types').MappingCandidate | null | undefined> = {}
  for (const row of rows) {
    selectedByRow[row.row_index] = stdSelectedMapping(row.row_index)
  }
  return utilBuildAnchorOnlyConfirmed(rows, selectedByRow)
}

// ANCHOR-INHERITANCE-MAPPING：未解决末级数量
const stdUnresolvedLeafCount = computed(() => {
  if (!stdMappingSummary.value) return 0
  return stdMappingSummary.value.unresolved_count
})

// ANCHOR-INHERITANCE-MAPPING：参与入库末级 = 已解析 + 未解析
const stdParticipatingLeafCount = computed(() => {
  if (!stdMappingSummary.value) return 0
  return stdMappingSummary.value.participating_leaf_count
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

// 步骤 3 最终执行启用条件：无阻止项、无未映射、无未解析末级、警告已确认（如有）
const stdCanExecute = computed(() => {
  if (stdBlockingErrors.value.length > 0) return false
  if (stdUnmappedCount.value > 0) return false
  if (stdExecuting.value) return false
  // ANCHOR-INHERITANCE-MAPPING：未解析末级必须为 0
  if (stdUnresolvedLeafCount.value > 0) return false
  // 有警告但未确认时，禁止执行
  if (stdWarnings.value.length > 0 && !stdWarningsConfirmed.value) return false
  return true
})

const stdExecuteHint = computed(() => {
  if (stdBlockingErrors.value.length > 0) return `还有 ${stdBlockingErrors.value.length} 条错误需要处理`
  if (stdUnmappedCount.value > 0) return `还有 ${stdUnmappedCount.value} 个科目未映射，请返回上一步完成映射`
  if (stdUnresolvedLeafCount.value > 0) return `还有 ${stdUnresolvedLeafCount.value} 个未解决末级，请完成对应锚点确认`
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
    auto_confirmable: false,
    compatibility_status: 'compatible',
    compatibility_reason: '用户人工确认',
    evidence: ['user_selected'],
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
    // ANCHOR-INHERITANCE-MAPPING：只提交锚点 / 中断点 / 显式覆盖
    // 普通 inherited 行不提交，由后端通过继承映射计划自动解析
    const confirmedMappings = stdBuildAnchorOnlyConfirmedMappings()

    const req: import('@/types').StdExecuteRequest = {
      confirmed_mappings: confirmedMappings,
      ignored_rows: stdIgnoredRowIndexes.value,
      warnings_confirmed: stdWarningsConfirmed.value,
      save_mapping_experience: true,
      mapping_strategy_version: 2,
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
  stdAnalyzeResult.value = null
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

/* ===== 第三步行级匹配表 ===== */
.std-match-review {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.std-match-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--spacing-3);
  flex-wrap: wrap;
}

.std-match-header-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  flex-wrap: wrap;
}

.std-table-alerts {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

/* ANCHOR-INHERITANCE-MAPPING：映射计划统计 */
.std-anchor-stats {
  display: flex;
  gap: var(--spacing-3);
  flex-wrap: wrap;
  padding: var(--spacing-3);
  background: var(--color-bg-soft, #f5f7fa);
  border-radius: var(--radius-md, 6px);
  margin-bottom: var(--spacing-3);
}

.std-anchor-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 12px;
  background: var(--color-bg-primary, #fff);
  border: 1px solid var(--color-border, #ebeef5);
  border-radius: var(--radius-sm, 4px);
  min-width: 80px;
}

.std-anchor-stat.success { border-color: var(--color-success, #67c23a); }
.std-anchor-stat.warning { border-color: var(--color-warning, #e6a23c); }
.std-anchor-stat.info { border-color: var(--color-info, #909399); }
.std-anchor-stat.muted { border-color: var(--color-border, #ebeef5); opacity: 0.7; }
.std-anchor-stat.danger { border-color: var(--color-danger, #f56c6c); }
.std-anchor-stat.emphasis {
  border-color: var(--color-primary, #409eff);
  background: var(--color-primary-light-9, #ecf5ff);
}

.std-anchor-stat-value {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.std-anchor-stat-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* 继承展示行 */
.std-inherit-meta {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.std-current-account.inherited {
  background: var(--color-success-light-9, #f0f9eb);
  padding: 4px 8px;
  border-radius: 4px;
}

.std-match-table-wrap {
  max-width: 100%;
  overflow-x: auto;
  overflow-y: visible;
  -webkit-overflow-scrolling: touch;
  /* 确保内部表格不撑破外层容器 */
  contain: layout style;
}

/* 匹配表总宽固定，列宽之和 > 容器宽度时 el-table body-wrapper 出现横向滚动条 */
.std-match-table-wrap :deep(.std-match-table) {
  min-width: 1900px;
}

/* 金额列：右对齐、不换行、等宽数字、完整显示不省略 */
.std-match-table-wrap :deep(.std-amount-col .cell) {
  text-align: right;
  white-space: nowrap;
  overflow: visible;
  text-overflow: clip;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono, 'Consolas', 'Monaco', monospace);
  color: var(--text-primary);
  padding-right: 16px;
  padding-left: 8px;
}

.std-level-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.std-level-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.std-parent-key {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

.std-row-warning-count {
  margin-top: 2px;
  font-size: var(--font-size-xs);
  color: var(--color-warning);
}

.std-current-account {
  font-size: var(--font-size-sm);
  line-height: 1.5;
}

.std-current-account code {
  margin-right: 6px;
  color: var(--color-primary);
}

.std-current-meta {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  margin-top: 2px;
}

.std-current-warning {
  font-size: var(--font-size-xs);
  color: var(--color-warning);
  margin-top: 2px;
}

.std-current-account.ignored {
  color: var(--text-placeholder);
  font-style: italic;
}

.std-current-account.muted {
  color: var(--text-placeholder);
}

.std-current-account.unmapped {
  color: var(--color-danger);
}

.std-action-muted {
  color: var(--text-placeholder);
  font-size: var(--font-size-xs);
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
