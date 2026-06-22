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

// 分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
}

// ===== 导入相关 =====

// 预览 API 返回的匹配结果
export interface TemplateCandidate {
  template_id: string
  name: string
  score: number
  matched_fields: string[]
  missing_fields: string[]
  warnings: string[]
  source_label: string | null
}

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
  template_candidates?: TemplateCandidate[]
  applied_mapping_v2?: Record<string, string>
  applied_template_name?: string
}

// 前端映射表格行
export interface MappingRow {
  file_column: string        // 原始表头
  field_key: string | null   // 用户选择的系统字段 value
  status: 'matched' | 'unmatched'
  sample_value: string       // 第一行示例数据
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
