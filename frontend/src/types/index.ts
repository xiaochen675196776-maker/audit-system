// 公司
export interface Company {
  id: string
  name: string
  code: string
  tax_id?: string
  address?: string
  industry?: string
  firm_id?: string
  is_active: boolean
  created_at?: string
}

// ===== 标准科目 =====

export interface StandardAccount {
  id: string
  account_code: string
  account_name: string
  account_category: string | null
  balance_direction: string | null
  level: number | null
  parent_id: string | null
  is_leaf: boolean
  is_active: boolean
  source_row_index: number | null
  created_at: string
  updated_at: string
}

export interface StandardAccountListResponse {
  items: StandardAccount[]
  total: number
}

export interface StandardAccountImportResult {
  message: string
  created_count: number
  updated_count: number
  deactivated_count: number
  warning_rows: Array<{
    row_index: number
    code?: string
    reason: string
  }>
}

// 分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
}

// ===== 导入相关 =====

export interface ColumnInfo {
  column_id: string
  index: number
  header: string
  normalized_header: string
  sample_values: string[]
  duplicate_group: {
    header: string
    occurrence: number
    total: number
  } | null
}

export interface ImportPreviewResponse {
  file_name: string
  headers: string[]
  columns: ColumnInfo[]
  matched: Record<string, string>
  unmatched: string[]
  missing: string[]
  preview_rows: string[][]
  row_count: number
  data_type: string
  mapping_suggestions_v2?: Record<string, {
    target_field: string
    source: 'company_experience' | 'global_experience' | 'keyword_match'
    confidence: number
    experience_id?: string
  }>
}

export interface MappingRow {
  file_column: string
  field_key: string | null
  status: 'matched' | 'unmatched'
  sample_value: string
  column_id: string
  column_index: number
  suggestion_source?: string
  suggestion_confidence?: number
  original_field_key?: string | null
}

// 执行 API 返回的错误项
export interface ImportErrorItem {
  row: number
  message: string
}

// 执行 API 返回结果
export interface ImportExecuteResponse {
  total: number
  success: number
  errors: ImportErrorItem[]
  file_name: string
  data_type: string
}

// 前端使用的执行结果
export interface ImportResultDisplay {
  success_count: number
  fail_count: number
  failures: { row: number; reason: string }[]
}

// ===== 数据查看：科目余额表标准化导入批次 =====

export interface ImportBatchItem {
  id: string
  file_name: string
  customer_label: string | null
  source_label: string | null
  fiscal_year: number | null
  period: number | null
  status: string
  entry_count: number
  created_at: string
  updated_at: string
}

export interface ImportBatchListResponse {
  items: ImportBatchItem[]
  total: number
}

// ===== 数据查看：树形节点 =====

// ===== 数据查看：树形节点 =====

export type TreeNodeType = 'account' | 'client_group' | 'entry'

export interface TreeNode {
  node_id: string
  node_type: TreeNodeType
  standard_account_id: string
  entry_id: string | null
  account_code: string
  account_name: string
  // entry 节点携带的标准科目快照（account 节点为 null），用于展示「标准：141101 包装物」
  standard_account_code: string | null
  standard_account_name: string | null
  client_account_code: string | null
  client_account_name: string | null
  account_category: string | null
  balance_direction: string | null
  level: number | null
  is_leaf: boolean
  opening_debit: string
  opening_credit: string
  current_debit: string
  current_credit: string
  ending_debit: string
  ending_credit: string
  children: TreeNode[]
  entry_count: number
  has_children: boolean
}

export interface TreeResponse {
  items: TreeNode[]
  total_nodes: number
}

// ===== 数据查看：明细条目 =====

export interface TrialBalanceEntry {
  id: string
  batch_id: string
  raw_row_id: string | null
  standard_account_id: string
  standard_account_code_snapshot: string
  standard_account_name_snapshot: string
  standard_account_category_snapshot: string | null
  standard_balance_direction_snapshot: string | null
  client_account_code: string | null
  client_account_name: string | null
  fiscal_year: number
  period: number
  opening_debit: string
  opening_credit: string
  current_debit: string
  current_credit: string
  ending_debit: string
  ending_credit: string
  created_at: string
}

export interface TrialBalanceEntryListResponse {
  items: TrialBalanceEntry[]
  total: number
}

// ===== 标准化导入向导 — TASK-045 =====

export interface StdColumnInfo {
  column_id: string
  header_text: string
  column_index: number
}

export interface StdPreviewResponse {
  batch_id: string
  file_name: string
  columns: StdColumnInfo[]
  sample_rows: Record<string, string>[]
  total_rows: number
  fiscal_year: number | null
  period: number | null
  customer_label: string | null
}

export interface StdFieldMappingEntry {
  column_id: string
  field_name: string
  period_type?: string | null   // opening | current | ending
  split_mode?: string | null    // two_column | single_by_direction | single_as_debit | single_as_credit
  debit_column_id?: string | null
  credit_column_id?: string | null
}

export interface StdAnalyzeRequest {
  field_mappings: StdFieldMappingEntry[]
  fiscal_year: number
  period: number
  customer_label?: string | null
  source_label?: string | null
  hierarchy_mode: string  // auto | code | indent | flat
}

export interface HierarchyInfo {
  row_index: number
  client_account_code: string | null
  client_account_name: string | null
  level: number | null
  parent_key: string | null
  is_leaf: boolean
  is_summary: boolean
  level_source: string
}

export interface AmountInfo {
  row_index: number
  opening_debit: string
  opening_credit: string
  current_debit: string
  current_credit: string
  ending_debit: string
  ending_credit: string
  warnings: string[]
  errors: string[]
}

export interface BlockingError {
  row_index: number | null
  code: string
  message: string
  category: string
}

export interface WarningItem {
  row_index: number | null
  code: string
  message: string
  category: string
}

export interface MappingCandidate {
  standard_account_id: string
  standard_account_code: string
  standard_account_name: string
  score: number
  source: string
  reason: string
  warning: string | null
  standard_balance_direction?: string | null
  // TASK-087：统一兼容性字段
  auto_confirmable: boolean
  compatibility_status: 'compatible' | 'conflict' | 'unknown'
  compatibility_reason?: string | null
  evidence?: string[]
}

export interface MappingRecommendEntry {
  row_index: number
  client_account_code: string | null
  client_account_name: string | null
  client_account_full_path?: string | null
  parent_row_index?: number | null
  parent_client_account_code?: string | null
  parent_client_account_name?: string | null
  is_leaf?: boolean
  is_summary?: boolean
  participates_in_entry?: boolean
  // ANCHOR-INHERITANCE-MAPPING
  mapping_role?:
    | 'structural_summary'
    | 'anchor'
    | 'inherited'
    | 'breakpoint'
    | 'explicit_override'
    | 'unresolved'
    | 'ignored'
  mapping_mode?:
    | 'direct_auto'
    | 'direct_confirmed'
    | 'inherited_ancestor'
    | 'override_confirmed'
    | 'none'
  requires_confirmation?: boolean
  anchor_row_index?: number | null
  anchor_client_account_code?: string | null
  anchor_client_account_name?: string | null
  resolved_standard_account_id?: string | null
  resolved_standard_account_code?: string | null
  resolved_standard_account_name?: string | null
  // TASK-092：suggested 是未确认的最高分候选
  suggested_standard_account_id?: string | null
  suggested_standard_account_code?: string | null
  suggested_standard_account_name?: string | null
  resolution_source?: string | null
  resolution_reason?: string | null
  inheritance_break_reason?: string | null
  inheritance_evidence?: string[]
  descendant_leaf_count?: number
  candidates: MappingCandidate[]
  // TASK-087：后端自动确认决策
  auto_confirm_candidate?: MappingCandidate | null
  auto_confirm_status?: 'unique_safe' | 'ambiguous' | 'none'
  auto_confirm_reason?: string
  node_key?: string | null
  node_type?: 'account' | 'auxiliary' | 'summary' | string | null
  node_source_row_indexes?: number[]
  node_representative_row_index?: number | null
  node_duplicate_binding?: boolean
  mapping_editable?: boolean
  deprecated?: boolean
}

export interface MappingPlanSummary {
  total_nodes: number
  structural_summary_count: number
  anchor_count: number
  inherited_count: number
  breakpoint_count: number
  explicit_override_count: number
  unresolved_count: number
  confirmation_required_count: number
  participating_leaf_count: number
  resolved_participating_leaf_count: number
  // TASK-092 性能指标
  full_recommendation_node_count?: number
  light_signal_node_count?: number
  inherited_without_recommendation_count?: number
}

export interface UniqueMappingNode {
  node_key: string
  representative_row_index: number
  source_row_count: number
  source_row_indexes: number[]
  account_code?: string | null
  account_name?: string | null
  full_path: string
  parent_node_key?: string | null
  node_type: string
  mapping_role: string
  requires_confirmation: boolean
  resolved_standard_account_id?: string | null
  suggested_standard_account_id?: string | null
  candidates: MappingCandidate[]
}

export interface RowNodeBinding {
  row_index: number
  node_key: string
  representative_row_index?: number | null
  is_representative: boolean
}

export interface StdAnalyzeResponse {
  batch_id: string
  status: string
  hierarchy: HierarchyInfo[]
  mapping_recommendations: MappingRecommendEntry[]
  amounts: AmountInfo[]
  errors: BlockingError[]
  warnings: WarningItem[]
  mapping_summary?: MappingPlanSummary
  mapping_strategy?: string
  unique_mapping_nodes?: UniqueMappingNode[]
  row_node_bindings?: RowNodeBinding[]
  // TASK-094D：5 类行集合计数（与 Execute 同口径）
  raw_identified_leaf_count?: number
  eligible_business_leaf_count?: number
  ignored_business_count?: number
  zero_template_count?: number
  summary_total_count?: number
  duplicate_aggregate_count?: number
  classification?: {
    eligible_business_leaf_rows: number[]
    zero_amount_template_rows: number[]
    summary_total_rows: number[]
    duplicate_aggregate_rows: number[]
    ignored_business_rows: number[]
    base_leaf_rows: number[]
    structural_rows: number[]
  }
  unique_node_count?: number
  account_node_count?: number
  auxiliary_node_count?: number
  summary_node_count?: number
  duplicate_binding_count?: number
  raw_row_compression_ratio?: number
}

export interface ConfirmedMapping {
  row_index: number
  client_account_code?: string | null
  client_account_name?: string | null
  standard_account_id: string
  standard_account_code: string
  standard_account_name: string
  // ANCHOR-INHERITANCE-MAPPING
  mapping_action?: 'anchor' | 'override'
  apply_to_descendants?: boolean
  selection_source?: 'auto_confirmed' | 'user_confirmed' | 'user_corrected'
}

export interface ConfirmedNodeMapping {
  node_key: string
  representative_row_index?: number | null
  standard_account_id: string
  standard_account_code: string
  standard_account_name: string
  mapping_action?: 'anchor' | 'override'
  apply_to_descendants?: boolean
  selection_source?: 'auto_confirmed' | 'user_confirmed' | 'user_corrected'
}

// ===== TASK-096A：唯一 NodeKey 确认列表相关类型 =====

/**
 * 前端组合的「唯一节点确认行」。
 *
 * 来源：
 * - 后端 `unique_mapping_nodes` 提供主键、代表行、绑定行集合、映射角色、推荐候选；
 * - 前端本地状态（selectedByNodeKey / explicitOverrideNodeKeys 等）补 selected_candidate / is_ignored / explicit_override。
 *
 * 注意：本接口不重复后端 UniqueMappingNode 的所有字段，
 * 仅前端展示与逻辑所需的字段；后端全量字段保留在 `UniqueMappingNode`。
 */
export interface UniqueNodeReviewRow {
  /** 后端主键：唯一节点的稳定身份 */
  node_key: string
  /** 后端建议的代表行（用于展开 binding 时高亮） */
  representative_row_index: number
  /** 绑定的原始行数量 */
  source_row_count: number
  /** 绑定的原始行 indexes（来自 row_node_bindings） */
  source_row_indexes: number[]
  /** 客户科目代码（聚合自代表行 / hierarchy） */
  account_code: string | null
  /** 客户科目名称 */
  account_name: string | null
  /** 客户层级完整路径（聚合自 hierarchy） */
  full_path: string
  /** 父节点 node_key（如有） */
  parent_node_key: string | null
  /** 后端节点类型 */
  node_type: 'account' | 'auxiliary' | 'summary' | string
  /** 后端映射角色 */
  mapping_role: string
  /** 后端是否要求用户确认 */
  requires_confirmation: boolean
  /** 后端自动解析结果 */
  resolved_standard_account_id: string | null
  resolved_standard_account_code?: string | null
  resolved_standard_account_name?: string | null
  /** 后端最高分推荐候选（未确认） */
  suggested_standard_account_id: string | null
  suggested_standard_account_code?: string | null
  suggested_standard_account_name?: string | null
  /** 推荐候选 */
  candidates: MappingCandidate[]
  /** 前端：当前用户选择的标准科目（candidate 形态） */
  selected_candidate?: MappingCandidate | null
  /** 前端：是否显式开启 override（仅对 inherited 节点有意义） */
  explicit_override?: boolean
  /** 前端：是否被业务忽略（绑定行全忽略时为 true） */
  is_ignored?: boolean
  /** 警告文本（聚合自 amounts/errors） */
  warnings?: string[]
  /** 后端解析来源（如 auto_unique_safe / unique_safe / fixture_confirmed） */
  resolution_source?: string | null
  /** 后端解析原因 */
  resolution_reason?: string | null
  /** 后端继承证据（仅 inherited） */
  inheritance_evidence?: string[]
}

/**
 * 唯一节点模式下的本地映射状态（行级 → NodeKey 级升级）。
 *
 * 严格禁止在 NodeKey 模式下把 selectedByRow / explicitOverrideRows 作为主状态。
 * 旧后端无 unique_mapping_nodes 时，组件仍可使用 selectedByRow 等行级字段，
 * 但本任务完成时，NodeKey 模式的主表与提交构造必须只依赖本结构。
 */
export interface NodeMappingLocalState {
  /** 按 node_key 维度的标准科目选择 */
  selectedByNodeKey: Record<string, MappingCandidate | null | undefined>
  /** 按 node_key 维度的显式覆盖开关（仅 inherited 节点允许） */
  explicitOverrideNodeKeys: Record<string, boolean | undefined>
  /** 按 node_key 维度的是否业务忽略 */
  ignoredNodeKeys: Record<string, boolean | undefined>
  /** 按 node_key 维度的展开状态 */
  expandedNodeKeys: Record<string, boolean | undefined>
}

/**
 * 旧行级模式下，同 node_key 不同目标时的冲突描述。
 *
 * 用于：
 * - 阻止确认 / 执行（canConfirm=false / canExecute=false）
 * - 渲染冲突提示（节点 + 两个原始行 + 两个目标）
 */
export interface NodeSelectionConflict {
  node_key: string
  representative_row_index: number | null
  bound_row_indexes: number[]
  conflicting_selections: Array<{
    row_index: number
    standard_account_id: string
    standard_account_code: string
    standard_account_name: string
    client_account_code: string | null
    client_account_name: string | null
  }>
}

/**
 * NodeKey 模式下的统计指标。
 *
 * 所有计数均按唯一节点计算，不按绑定原始行重复计算。
 */
export interface NodeMappingStats {
  /** 唯一节点总数 */
  total_node_count: number
  /** 唯一节点中需要用户确认的数量 */
  confirmation_required_count: number
  /** 已映射节点（已选 candidate 或自动 unique_safe） */
  mapped_count: number
  /** 未映射节点（需要选择但尚未选择） */
  unmapped_count: number
  /** 警告节点（聚合自 analyze warnings） */
  warning_count: number
  /** 显式覆盖节点（inherited + explicit_override 开启） */
  explicit_override_count: number
  /** 自动继承节点（inherited 且未 override） */
  inherited_count: number
  /** 待确认锚点（anchor/breakpoint + requires_confirmation + 未选） */
  anchor_pending_count: number
  /** 绑定原始行总数 */
  bound_raw_row_count: number
}

export interface StdExecuteRequest {
  confirmed_mappings: ConfirmedMapping[]
  confirmed_node_mappings?: ConfirmedNodeMapping[]
  ignored_rows: number[]
  warnings_confirmed: boolean
  save_mapping_experience: boolean
  mapping_strategy_version?: number  // TASK-092：默认 2
}

export interface MappingSavedInfo {
  client_account_code: string | null
  standard_account_code: string
  status: string
  mapping_kind?: string
  client_account_full_path?: string | null
}

export interface StdExecuteResponse {
  batch_id: string
  status: string
  entry_count: number
  // TASK-094D：5 类行集合计数（与 Analyze 同口径）
  raw_identified_leaf_count?: number
  eligible_business_leaf_count?: number
  ignored_business_count?: number
  zero_template_count?: number
  summary_total_count?: number
  duplicate_aggregate_count?: number
  business_amount_reconciliation?: Record<string, {
    source: string
    entry: string
    eligible: string
    ignored: string
    difference: string
    ok: string
  }>
  summary_amount_reconciliation?: Record<string, {
    fields: Record<string, {
      self: string
      children_sum: string
      difference: string
      ok: string
    }>
    mismatch_count: number
    warning: string | null
  }>
  // 兼容旧字段（标记 deprecated）
  participating_leaf_count?: number
  ignored_leaf_count?: number
  zero_amount_skipped_leaf_count?: number
  amount_reconciliation?: Record<string, {
    source: string
    entry: string
    ignored: string
    zero_skip: string
    difference: string
    deprecated?: string
    use_business_amount_reconciliation?: string
  }>
  amount_reconciliation_deprecated?: boolean
  classification?: {
    eligible_business_leaf_rows: number[]
    zero_amount_template_rows: number[]
    summary_total_rows: number[]
    duplicate_aggregate_rows: number[]
    ignored_business_rows: number[]
    base_leaf_rows: number[]
    structural_rows: number[]
  }
  raw_row_count: number
  mapping_saved_count: number
  mapping_experience_saved_count?: number
  mapping_saved: MappingSavedInfo[]
  anchor_count?: number
  breakpoint_count?: number
  inherited_count?: number
  explicit_override_count?: number
  unresolved_leaf_count?: number
  mapping_strategy_version?: number
  confirmed_node_mapping_count?: number
  auto_confirmed_node_count?: number
  manual_confirmed_node_count?: number
  duplicate_row_submit_count?: number
  row_level_confirmed_mapping_count?: number
  unresolved_node_count?: number
}
