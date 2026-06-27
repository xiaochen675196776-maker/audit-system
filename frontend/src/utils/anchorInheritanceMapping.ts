/**
 * TASK-094B 锚点继承式映射前端工具函数
 *
 * 所有映射角色相关的判定与构造逻辑都集中在本文件，避免在 Vue 组件里
 * 复制内联实现。组件里只引用本文件的导出函数。
 *
 * 强制约束（TASK-094B）：
 * - 全部角色判定函数必须接收统一的 LocalMappingState；
 * - explicit_override 已开启但未选择：视为未映射、阻止确认/执行、不提交 override；
 * - override 提交目标不得使用原 inherited resolved 兜底；
 * - 恢复继承必须清除 override 与选择并恢复 inherited 角色；
 * - 非末级 anchor 仍然需要确认并提交，不得以「父级不入库」代替显示；
 * - 状态展示统一使用 rowDisplayStatus(row, localState)；
 * - confirmed_mappings 必须只包含 anchor / breakpoint / explicit_override 且
 *   explicit_override 必须有用户选择；
 * - 不允许任何 candidates[0] 兜底（不提供 candidates[0] 函数）；
 * - 后端 unconfirmed 最高分候选只能作为 suggested，不得作为 resolved；
 * - 兼容老版（mapping_role / requires_confirmation 不存在时）按 fallback 处理。
 */

import type {
  ConfirmedMapping,
  MappingCandidate,
  MappingRecommendEntry,
  MappingPlanSummary,
} from '../types'

// ── 角色与模式常量 ────────────────────────────────────────

export const MAPPING_ROLES = [
  'structural_summary',
  'anchor',
  'inherited',
  'breakpoint',
  'explicit_override',
  'unresolved',
  'ignored',
] as const

export type MappingRole = (typeof MAPPING_ROLES)[number]

export interface LocalMappingState {
  selectedByRow: Record<number, MappingCandidate | null | undefined>
  explicitOverrideRows: Record<number, boolean | undefined>
  confirmedUnresolvedRows: Record<number, boolean | undefined>
  ignoredRows: Record<number, boolean | undefined>
}

/** 需要用户确认 + 提交映射的角色集合（仅 anchor/breakpoint/explicit_override） */
export const SUBMITTABLE_ROLES: readonly MappingRole[] = [
  'anchor',
  'breakpoint',
  'explicit_override',
]

/** 不参与「未映射」统计的角色 */
export const INHERITED_LIKE_ROLES: readonly MappingRole[] = [
  'inherited',
  'structural_summary',
  'ignored',
]

// ── ReviewRow：前端组合行（hierarchy + rec + amount）─────────

export interface MappingReviewRow {
  row_index: number
  client_account_code?: string | null
  client_account_name?: string | null
  is_leaf?: boolean | null
  is_summary?: boolean | null
  participates_in_entry?: boolean | null
  /**
   * ANCHOR 解析结果（来自后端）。为简化测试 / 兼容旧版本，
   * mapping_role / mapping_mode 字段放宽为 string。
   */
  rec?: any
  /** 是否被用户忽略 */
  is_ignored?: boolean
}

// ── 行级映射辅助 ──────────────────────────────────────────

/** 安全获取 mapping_role；老版本无字段时返回 'unresolved' */
export function rowMappingRole(row: MappingReviewRow): MappingRole {
  const role = row.rec?.mapping_role
  if (!role) return 'unresolved'
  if ((MAPPING_ROLES as readonly string[]).includes(role)) {
    return role as MappingRole
  }
  return 'unresolved'
}

export function effectiveMappingRole(
  row: MappingReviewRow,
  state?: Partial<LocalMappingState> | null,
): MappingRole {
  const rowIndex = row.row_index
  if (row.is_ignored || state?.ignoredRows?.[rowIndex]) return 'ignored'
  const backendRole = rowMappingRole(row)
  if (backendRole === 'structural_summary' || backendRole === 'ignored') {
    return backendRole
  }
  if (backendRole === 'inherited' && state?.explicitOverrideRows?.[rowIndex]) {
    return 'explicit_override'
  }
  if (backendRole === 'unresolved' && state?.selectedByRow?.[rowIndex]) {
    return 'anchor'
  }
  return backendRole
}

/** 角色展示标签与标签类型 */
export function rowMappingRoleLabel(role: MappingRole): { label: string; type: string } {
  const map: Record<MappingRole, { label: string; type: string }> = {
    anchor: { label: '映射锚点', type: 'primary' },
    inherited: { label: '自动继承', type: 'success' },
    breakpoint: { label: '继承中断点', type: 'warning' },
    explicit_override: { label: '显式覆盖', type: 'info' },
    structural_summary: { label: '结构汇总', type: 'info' },
    unresolved: { label: '未解决', type: 'danger' },
    ignored: { label: '已忽略', type: 'info' },
  }
  return map[role] ?? { label: role, type: 'info' }
}

export function rowMappingRoleTagType(role: MappingRole): string {
  const map: Record<MappingRole, string> = {
    anchor: 'primary',
    inherited: 'success',
    breakpoint: 'warning',
    explicit_override: 'info',
    structural_summary: 'info',
    unresolved: 'danger',
    ignored: 'info',
  }
  return map[role] ?? ''
}

// ── 核心判定函数 ──────────────────────────────────────────

/**
 * 该行是否需要用户在前端做映射选择（确认 / 选择标准科目）。
 *
 * 规则：
 * - 已忽略：不需要
 * - 角色是 inherited / structural_summary / ignored：不需要
 * - 角色是 unresolved：需要
 * - 角色是 explicit_override：只要本地 explicitOverrideRows 标记为 true，就必须
 *   计入未映射、阻止确认/执行（即便后端 requires_confirmation=false）。
 * - 角色是 anchor / breakpoint 且 requires_confirmation=true：需要
 *
 * 注意：is_leaf / participates_in_entry 不再决定是否需要映射，
 * 非末级 anchor（如 银行存款）依然需要确认。
 */
export function rowRequiresMapping(
  row: MappingReviewRow,
  state?: Partial<LocalMappingState> | null,
): boolean {
  if (row.is_ignored || state?.ignoredRows?.[row.row_index]) return false
  const role = effectiveMappingRole(row, state)

  if (INHERITED_LIKE_ROLES.includes(role)) return false

  if (role === 'unresolved') return true

  if (role === 'explicit_override') {
    // 用户已点击「单独映射」但未选择新标准科目：视为未映射
    if (state?.explicitOverrideRows?.[row.row_index]) return true
    return row.rec?.requires_confirmation === true || !row.rec?.resolved_standard_account_id
  }

  // anchor / breakpoint — 根据 requires_confirmation 决定
  return row.rec?.requires_confirmation === true
}

/** 该行是否允许显示标准科目选择器（与 is_leaf / participates_in_entry 无关） */
export function rowCanSelectStandardAccount(
  row: MappingReviewRow,
  state?: Partial<LocalMappingState> | null,
): boolean {
  if (row.is_ignored || state?.ignoredRows?.[row.row_index]) return false
  const role = effectiveMappingRole(row, state)
  if (INHERITED_LIKE_ROLES.includes(role)) return false
  return true
}

/**
 * 该行是否应该进入 confirmed_mappings 提交到后端 execute。
 *
 * 规则：
 * - 已忽略：不提交
 * - 角色属于 anchor / breakpoint：提交（无用户选择时由 buildAnchorOnly 兜底为 auto_confirmed）
 * - 角色属于 explicit_override：仅当用户已选择新标准科目才提交（禁止使用原
 *   inherited resolved 兜底为空选择 override）
 * - 其它（inherited / structural_summary / ignored / unresolved 无选择）：不提交
 */
export function rowShouldSubmitMapping(
  row: MappingReviewRow,
  state?: Partial<LocalMappingState> | null,
): boolean {
  if (row.is_ignored || state?.ignoredRows?.[row.row_index]) return false
  const role = effectiveMappingRole(row, state)
  if (!(SUBMITTABLE_ROLES as readonly string[]).includes(role)) return false
  // explicit_override 必须有用户选择，否则视为空 override 直接阻断
  if (role === 'explicit_override' && !state?.selectedByRow?.[row.row_index]) {
    return false
  }
  return true
}

/** 该行是否可单独映射（从前端 override 一个 inherited 子节点） */
export function rowCanOverride(row: MappingReviewRow): boolean {
  if (row.is_ignored) return false
  const role = rowMappingRole(row)
  return (
    role === 'inherited' ||
    role === 'anchor' ||
    role === 'breakpoint'
  )
}

export function computeDynamicUnresolvedCount(
  rows: MappingReviewRow[],
  state: Partial<LocalMappingState>,
): number {
  let count = 0
  for (const row of rows) {
    const rowIndex = row.row_index
    if (row.is_ignored || state.ignoredRows?.[rowIndex]) continue
    if (rowMappingRole(row) !== 'unresolved') continue
    if (state.selectedByRow?.[rowIndex]) continue
    count += 1
  }
  return count
}

/** 该行是否参与金额入库（用于过滤 entry / 数量勾稽） */
export function rowParticipatesInEntry(row: MappingReviewRow): boolean {
  if (row.is_ignored) return false
  const role = rowMappingRole(row)
  if (role === 'structural_summary' || role === 'ignored') return false
  if (row.participates_in_entry === false) return false
  if (row.is_leaf === false) return false
  if (row.is_summary === true) return false
  return true
}

/** 该行的解析结果（resolved 后端）状态 */
export type RowDisplayStatus =
  | 'mapped'
  | 'inherited'
  | 'unresolved'
  | 'pending_confirmation'
  | 'auto_confirmed'
  | 'structural'
  | 'ignored'
  | 'overridden'
  | 'explicit_override_pending'
  | 'explicit_override_confirmed'

export interface RowDisplayInfo {
  status: RowDisplayStatus
  label: string
  type: '' | 'success' | 'warning' | 'info' | 'danger' | 'primary'
}

/**
 * 统一行级展示状态。
 *
 * 严格基于 effective role + LocalMappingState 计算，组件不再有第二套逻辑。
 * 至少区分：
 *   - 映射锚点（anchor / breakpoint 已匹配或自动确认）
 *   - 自动确认（anchor unique_safe）
 *   - 待确认（anchor / breakpoint requires_confirmation）
 *   - 自动继承（inherited 未 override）
 *   - 显式覆盖待选择（explicit_override 已开启但未选择）
 *   - 显式覆盖已确认（explicit_override / inherited + selected）
 *   - 继承中断点（breakpoint）
 *   - 结构汇总（structural_summary）
 *   - 未解决（unresolved 未选择）
 *   - 已忽略
 *
 * 非末级 anchor 一律展示「映射锚点」/「已匹配」/「待确认」等具体状态，不允许
 * 因 is_leaf=false 错误降级为「父级不入库」。
 */
export function rowDisplayStatus(
  row: MappingReviewRow,
  state: Partial<LocalMappingState> = {},
): RowDisplayInfo {
  if (row.is_ignored || state.ignoredRows?.[row.row_index]) {
    return { status: 'ignored', label: '已忽略', type: 'info' }
  }
  const role = effectiveMappingRole(row, state)
  const hasSelected = !!state.selectedByRow?.[row.row_index]

  if (role === 'structural_summary') {
    return { status: 'structural', label: '结构汇总', type: 'info' }
  }

  if (role === 'inherited') {
    if (hasSelected) {
      return {
        status: 'overridden',
        label: '显式覆盖已确认',
        type: 'primary',
      }
    }
    return { status: 'inherited', label: '自动继承', type: 'success' }
  }

  if (role === 'explicit_override') {
    if (hasSelected) {
      return {
        status: 'explicit_override_confirmed',
        label: '显式覆盖已确认',
        type: 'primary',
      }
    }
    return {
      status: 'explicit_override_pending',
      label: '显式覆盖待选择',
      type: 'warning',
    }
  }

  if (role === 'anchor' || role === 'breakpoint') {
    if (hasSelected) {
      const label =
        role === 'breakpoint' ? '继承中断点已确认' : '映射锚点'
      return {
        status: 'mapped',
        label,
        type: role === 'breakpoint' ? 'warning' : 'success',
      }
    }
    if (
      row.rec?.auto_confirm_status === 'unique_safe' &&
      row.rec?.resolved_standard_account_id
    ) {
      return { status: 'auto_confirmed', label: '自动确认', type: 'success' }
    }
    const label = role === 'breakpoint' ? '继承中断点' : '映射锚点'
    return {
      status: 'pending_confirmation',
      label: `待确认 · ${label}`,
      type: 'warning',
    }
  }

  // unresolved：selected 后 effective role 已变为 anchor，此处只处理未选
  if (role === 'unresolved') {
    return { status: 'unresolved', label: '未解决', type: 'danger' }
  }

  return { status: 'unresolved', label: '未解决', type: 'danger' }
}

// ── 构造提交映射（仅 anchor/breakpoint/explicit_override） ──

/**
 * 从前端确认状态 + analyze 响应构造 confirmed_mappings。
 *
 * 严格规则（TASK-094B）：
 * - 只为 role ∈ {anchor, breakpoint, explicit_override} 提交
 * - explicit_override 必须有用户选择；禁止使用原 inherited resolved 兜底
 *   （否则会产生一个与原继承相同的「假 override」提交）
 * - 用户已选中 → 用 selection_source=user_confirmed
 * - 自动确认（auto_confirm_status=unique_safe + resolved 已存在）→ 用
 *   selection_source=auto_confirmed；仅 anchor / breakpoint 允许该兜底
 * - 其它情况（unresolved 未选 / pending / inherited）→ 不提交
 */
export function buildAnchorOnlyConfirmedMappings(
  rows: MappingReviewRow[],
  selectedByRow: Record<number, MappingCandidate | null | undefined>,
  state?: Partial<LocalMappingState> | null,
): ConfirmedMapping[] {
  const out: ConfirmedMapping[] = []
  const effectiveState: Partial<LocalMappingState> = {
    ...(state || {}),
    selectedByRow,
  }
  for (const row of rows) {
    if (!rowShouldSubmitMapping(row, effectiveState)) continue
    const role = effectiveMappingRole(row, effectiveState)
    const sel = selectedByRow[row.row_index] || null

    let standard: MappingCandidate | null | undefined = sel
    let selectionSource: 'user_confirmed' | 'auto_confirmed' | 'user_corrected' =
      'user_confirmed'

    // explicit_override 禁止使用 backend resolved 兜底（必须用户确认选择）
    const allowAutoFallback = role === 'anchor' || role === 'breakpoint'

    if (!standard && allowAutoFallback && row.rec?.resolved_standard_account_id) {
      standard = {
        standard_account_id: row.rec.resolved_standard_account_id,
        standard_account_code: row.rec.resolved_standard_account_code || '',
        standard_account_name: row.rec.resolved_standard_account_name || '',
        score: 1.0,
        source: row.rec.resolution_source || 'auto',
        reason: row.rec.resolution_reason || '自动确认',
        warning: null,
        auto_confirmable: true,
        compatibility_status: 'compatible',
      }
      selectionSource = 'auto_confirmed'
    }

    if (!standard || !standard.standard_account_id) continue

    out.push({
      row_index: row.row_index,
      client_account_code: row.rec?.client_account_code ?? row.client_account_code ?? null,
      client_account_name: row.rec?.client_account_name ?? row.client_account_name ?? null,
      standard_account_id: standard.standard_account_id,
      standard_account_code: standard.standard_account_code,
      standard_account_name: standard.standard_account_name,
      mapping_action: role === 'explicit_override' ? 'override' : 'anchor',
      apply_to_descendants: true,
      selection_source: selectionSource,
    })
  }
  return out
}

// ── 显式覆盖 / 恢复继承（用于组件 override 操作） ──────────

/**
 * 设置某行为 override（已选中 standardAccountId）。
 *
 * 该函数仅更新 selectedByRow；explicitOverrideRows 标志由组件单独维护，
 * 二者必须配套（applyExplicitOverrideSelection + setExplicitOverrideFlag）。
 */
export function applyExplicitOverride(
  selectedByRow: Record<number, MappingCandidate | null | undefined>,
  rowIndex: number,
  candidate: MappingCandidate | null,
): Record<number, MappingCandidate | null | undefined> {
  return { ...selectedByRow, [rowIndex]: candidate }
}

/** 恢复继承（删除 override 选中） */
export function restoreInheritance(
  selectedByRow: Record<number, MappingCandidate | null | undefined>,
  rowIndex: number,
): Record<number, MappingCandidate | null | undefined> {
  const next = { ...selectedByRow }
  delete next[rowIndex]
  return next
}

/**
 * 计算开启 override 但未选择新标准科目的「空 override」行集合。
 * 仅用于诊断与统计，不参与提交。
 */
export function countEmptyOverrides(
  rows: MappingReviewRow[],
  state: Partial<LocalMappingState>,
): number {
  let count = 0
  for (const row of rows) {
    const rowIndex = row.row_index
    if (row.is_ignored || state.ignoredRows?.[rowIndex]) continue
    if (!state.explicitOverrideRows?.[rowIndex]) continue
    if (state.selectedByRow?.[rowIndex]) continue
    count += 1
  }
  return count
}

// ── 汇总统计（用于前端的 step 3 / 4 启用判定） ──────────────

export interface UnmappedAndUnresolvedStats {
  unmapped_count: number
  unresolved_leaf_count: number
  /** 可以进入下一步（unmapped + unresolved 都为 0） */
  can_confirm: boolean
  /** 可以执行（can_confirm + 警告已确认或无警告 + 无阻塞错误） */
  can_execute: boolean
}

export function computeStats(
  rows: MappingReviewRow[],
  selectedByRow: Record<number, MappingCandidate | null | undefined>,
  summary: MappingPlanSummary | null | undefined,
  warningsConfirmed: boolean,
  blockingErrorCount: number,
  hasWarnings: boolean,
  state?: Partial<LocalMappingState> | null,
): UnmappedAndUnresolvedStats {
  const effectiveState: Partial<LocalMappingState> = {
    ...(state || {}),
    selectedByRow,
  }
  let unmapped = 0
  for (const row of rows) {
    if (!rowRequiresMapping(row, effectiveState)) continue
    if (!selectedByRow[row.row_index]) unmapped += 1
  }
  const unresolved = rows.length > 0
    ? computeDynamicUnresolvedCount(rows, effectiveState)
    : (summary?.unresolved_count ?? 0)
  const canConfirm = unmapped === 0 && unresolved === 0 && blockingErrorCount === 0
  const canExecute =
    canConfirm &&
    (!hasWarnings || warningsConfirmed)
  return {
    unmapped_count: unmapped,
    unresolved_leaf_count: unresolved,
    can_confirm: canConfirm,
    can_execute: canExecute,
  }
}

// ── 兼容老版本映射响应（向后兼容） ──────────────────────────

/** 兼容老版本 MappingRecommendEntry：缺字段时填默认 */
export function normalizeMappingRecommend(
  raw: any,
): MappingRecommendEntry {
  const rec: MappingRecommendEntry = {
    row_index: raw?.row_index ?? null,
    client_account_code: raw?.client_account_code ?? null,
    client_account_name: raw?.client_account_name ?? null,
    client_account_full_path: raw?.client_account_full_path ?? null,
    parent_row_index: raw?.parent_row_index ?? null,
    parent_client_account_code: raw?.parent_client_account_code ?? null,
    parent_client_account_name: raw?.parent_client_account_name ?? null,
    is_leaf: raw?.is_leaf ?? null,
    is_summary: raw?.is_summary ?? null,
    participates_in_entry: raw?.participates_in_entry ?? null,
    mapping_role: raw?.mapping_role ?? 'unresolved',
    mapping_mode: raw?.mapping_mode ?? 'none',
    requires_confirmation: raw?.requires_confirmation ?? false,
    anchor_row_index: raw?.anchor_row_index ?? null,
    anchor_client_account_code: raw?.anchor_client_account_code ?? null,
    anchor_client_account_name: raw?.anchor_client_account_name ?? null,
    resolved_standard_account_id: raw?.resolved_standard_account_id ?? null,
    resolved_standard_account_code: raw?.resolved_standard_account_code ?? null,
    resolved_standard_account_name: raw?.resolved_standard_account_name ?? null,
    suggested_standard_account_id: raw?.suggested_standard_account_id ?? null,
    suggested_standard_account_code: raw?.suggested_standard_account_code ?? null,
    suggested_standard_account_name: raw?.suggested_standard_account_name ?? null,
    resolution_source: raw?.resolution_source ?? null,
    resolution_reason: raw?.resolution_reason ?? null,
    inheritance_break_reason: raw?.inheritance_break_reason ?? null,
    inheritance_evidence: raw?.inheritance_evidence ?? [],
    descendant_leaf_count: raw?.descendant_leaf_count ?? 0,
    candidates: raw?.candidates ?? [],
    auto_confirm_candidate: raw?.auto_confirm_candidate ?? null,
    auto_confirm_status: raw?.auto_confirm_status ?? null,
    auto_confirm_reason: raw?.auto_confirm_reason ?? null,
  }
  return rec
}
