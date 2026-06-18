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
export interface ImportPreviewResponse {
  file_name: string
  headers: string[]
  matched: Record<string, string>   // { "标准字段": "原始表头" }
  unmatched: string[]               // 未匹配的原始表头列表
  missing: string[]                 // 缺少的必填字段
  preview_rows: string[][]          // 前5行原始数据
  row_count: number
  data_type: string
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
