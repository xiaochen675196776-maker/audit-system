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
  is_leaf?: boolean
  is_summary?: boolean
  participates_in_entry?: boolean
  candidates: MappingCandidate[]
  // TASK-087：后端自动确认决策
  auto_confirm_candidate?: MappingCandidate | null
  auto_confirm_status?: 'unique_safe' | 'ambiguous' | 'none'
  auto_confirm_reason?: string
}

export interface StdAnalyzeResponse {
  batch_id: string
  status: string
  hierarchy: HierarchyInfo[]
  mapping_recommendations: MappingRecommendEntry[]
  amounts: AmountInfo[]
  errors: BlockingError[]
  warnings: WarningItem[]
}

export interface ConfirmedMapping {
  row_index: number
  client_account_code?: string | null
  client_account_name?: string | null
  standard_account_id: string
  standard_account_code: string
  standard_account_name: string
}

export interface StdExecuteRequest {
  confirmed_mappings: ConfirmedMapping[]
  ignored_rows: number[]
  warnings_confirmed: boolean
  save_mapping_experience: boolean
}

export interface MappingSavedInfo {
  client_account_code: string | null
  standard_account_code: string
  status: string
}

export interface StdExecuteResponse {
  batch_id: string
  status: string
  entry_count: number
  raw_row_count: number
  mapping_saved_count: number
  mapping_saved: MappingSavedInfo[]
}
