// 公司
export interface Company {
  id: number
  name: string
  code: string
  tax_id?: string
  address?: string
  industry?: string
  status?: string
  created_at?: string
  updated_at?: string
}

// 分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
}

// 导入相关
export interface FieldMapping {
  file_column: string
  matched_field: string | null
  sample_value: string
  status: 'matched' | 'unmatched'
}

export interface ImportPreview {
  mappings: FieldMapping[]
  preview_rows: Record<string, string>[]
}

export interface ImportResult {
  success_count: number
  fail_count: number
  failures: ImportFailure[]
}

export interface ImportFailure {
  row: number
  reason: string
}
