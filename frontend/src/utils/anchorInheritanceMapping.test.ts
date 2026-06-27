/**
 * TASK-093 前端锚点继承式映射工具函数测试
 *
 * 直接从生产模块导入函数，禁止复制实现。
 * 运行方式：npx tsx src/utils/anchorInheritanceMapping.test.ts
 */

import {
  rowMappingRole,
  rowRequiresMapping,
  rowCanSelectStandardAccount,
  rowShouldSubmitMapping,
  rowCanOverride,
  rowParticipatesInEntry,
  rowDisplayStatus,
  buildAnchorOnlyConfirmedMappings,
  applyExplicitOverride,
  restoreInheritance,
  computeStats,
  normalizeMappingRecommend,
  MAPPING_ROLES,
  SUBMITTABLE_ROLES,
  INHERITED_LIKE_ROLES,
} from './anchorInheritanceMapping'
import { test } from 'vitest'

import type {
  ConfirmedMapping,
  MappingCandidate,
  MappingRecommendEntry,
  MappingPlanSummary,
} from '../types'

// 测试辅助：将测试中的对象 cast 成 MappingReviewRow
const asRow = (obj: any) => obj as import('./anchorInheritanceMapping').MappingReviewRow
const asRows = (arr: any[]) => arr.map(asRow)

// ── 测试断言 ──

let pass = 0
let fail = 0

function assert(condition: boolean, label: string): void {
  if (condition) {
    pass++
    console.log(`  PASS  ${label}`)
  } else {
    fail++
    console.error(`  FAIL  ${label}`)
  }
}

console.log('\n=== TASK-093 前端锚点继承式映射工具验证 ===\n')

const baseRec: MappingRecommendEntry = {
  row_index: 0,
  client_account_code: '1002',
  client_account_name: '银行存款',
  candidates: [],
  mapping_role: 'anchor',
  mapping_mode: 'direct_auto',
  requires_confirmation: false,
  resolved_standard_account_id: 'sa-001',
  resolved_standard_account_code: '1002',
  resolved_standard_account_name: '银行存款',
}

const baseCandidate: MappingCandidate = {
  standard_account_id: 'sa-001',
  standard_account_code: '1002',
  standard_account_name: '银行存款',
  score: 0.95,
  source: 'code_match',
  reason: '代码精确匹配',
  warning: null,
  auto_confirmable: true,
  compatibility_status: 'compatible',
}

// ─────────── §1 角色与状态判定 ───────────

console.log('--- §1 角色与状态判定 ---')

// 1. inherited 不要求确认
{
  const row = { row_index: 0, rec: { ...baseRec, mapping_role: 'inherited' } }
  assert(rowRequiresMapping(row) === false, 'inherited 不要求确认')
  assert(rowCanSelectStandardAccount(row) === false, 'inherited 不显示选择器')
  assert(rowShouldSubmitMapping(row) === false, 'inherited 不提交映射')
}

// 2. structural_summary 不参与任何确认
{
  const row = { row_index: 0, rec: { ...baseRec, mapping_role: 'structural_summary' } }
  assert(rowRequiresMapping(row) === false, 'structural_summary 不要求确认')
  assert(rowShouldSubmitMapping(row) === false, 'structural_summary 不提交')
}

// 3. anchor（unique_safe + 已 resolved）不要求确认
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'anchor', requires_confirmation: false },
  }
  assert(rowRequiresMapping(row) === false, 'anchor unique_safe 不要求确认')
  assert(rowCanSelectStandardAccount(row) === true, 'anchor 可显示选择器')
  assert(rowShouldSubmitMapping(row) === true, 'anchor 提交映射')
}

// 4. anchor（requires_confirmation=true）要求确认
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'anchor', requires_confirmation: true },
  }
  assert(rowRequiresMapping(row) === true, 'anchor 待确认要求确认')
  assert(rowCanSelectStandardAccount(row) === true, 'anchor 待确认显示选择器')
  assert(rowShouldSubmitMapping(row) === true, 'anchor 待确认提交')
}

// 5. breakpoint 要求确认
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'breakpoint', requires_confirmation: true },
  }
  assert(rowRequiresMapping(row) === true, 'breakpoint 要求确认')
  assert(rowShouldSubmitMapping(row) === true, 'breakpoint 提交')
}

// 6. explicit_override 要求确认
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'explicit_override', requires_confirmation: true },
  }
  assert(rowRequiresMapping(row) === true, 'explicit_override 要求确认')
  assert(rowShouldSubmitMapping(row) === true, 'explicit_override 提交')
}

// 7. unresolved 要求确认
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'unresolved', requires_confirmation: true },
  }
  assert(rowRequiresMapping(row) === true, 'unresolved 要求确认')
  assert(rowShouldSubmitMapping(row) === false, 'unresolved 不提交（需先确认）')
}

// 8. 非末级 anchor（银行存款）能确认能提交（TASK-092 P0-2.4）
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'anchor', requires_confirmation: true },
    is_leaf: false,
    is_summary: true,
    participates_in_entry: false,
  }
  assert(rowRequiresMapping(row) === true, '非末级 anchor 仍要求确认（TASK-092）')
  assert(rowCanSelectStandardAccount(row) === true, '非末级 anchor 显示选择器（TASK-092）')
  assert(rowShouldSubmitMapping(row) === true, '非末级 anchor 提交（TASK-092）')
}

// 9. 已忽略行所有判定都为 false
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'anchor' },
    is_ignored: true,
  }
  assert(rowRequiresMapping(row) === false, '已忽略不要求确认')
  assert(rowShouldSubmitMapping(row) === false, '已忽略不提交')
}

// 10. rowCanOverride 仅对 inherited / anchor / breakpoint 为 true
{
  assert(rowCanOverride({ row_index: 0, rec: { ...baseRec, mapping_role: 'inherited' } }) === true, 'inherited 可单独映射')
  assert(rowCanOverride({ row_index: 0, rec: { ...baseRec, mapping_role: 'anchor' } }) === true, 'anchor 可单独映射')
  assert(rowCanOverride({ row_index: 0, rec: { ...baseRec, mapping_role: 'breakpoint' } }) === true, 'breakpoint 可单独映射')
  assert(rowCanOverride({ row_index: 0, rec: { ...baseRec, mapping_role: 'unresolved' } }) === false, 'unresolved 不可单独映射')
  assert(rowCanOverride({ row_index: 0, rec: { ...baseRec, mapping_role: 'explicit_override' } }) === false, 'explicit_override 不可再 override')
}

// 11. rowParticipatesInEntry 与 is_leaf / participates_in_entry 一致
{
  assert(
    rowParticipatesInEntry({
      row_index: 0,
      rec: { ...baseRec, mapping_role: 'anchor' },
      is_leaf: true,
      is_summary: false,
      participates_in_entry: true,
    }) === true,
    '末级 anchor 参与入库',
  )
  assert(
    rowParticipatesInEntry({
      row_index: 0,
      rec: { ...baseRec, mapping_role: 'anchor' },
      is_leaf: false,
      is_summary: true,
      participates_in_entry: false,
    }) === false,
    '非末级 anchor 不参与入库（但不阻止确认）',
  )
  assert(
    rowParticipatesInEntry({
      row_index: 0,
      rec: { ...baseRec, mapping_role: 'inherited' },
      is_leaf: true,
      is_summary: false,
      participates_in_entry: true,
    }) === true,
    'inherited 末级参与入库',
  )
}

// ─────────── §2 行级展示状态 ───────────

console.log('\n--- §2 行级展示状态 ---')

{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'inherited' } },
    false,
  )
  assert(info.status === 'inherited', 'inherited 未 override → inherited 状态')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'inherited' } },
    true,
  )
  assert(info.status === 'overridden', 'inherited 已 override → overridden')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'anchor', requires_confirmation: false, resolved_standard_account_id: 'sa-001', auto_confirm_status: 'unique_safe' as any } },
    false,
  )
  assert(info.status === 'auto_confirmed', 'anchor unique_safe + 无 selection → auto_confirmed')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'anchor', requires_confirmation: true } },
    false,
  )
  assert(info.status === 'pending_confirmation', 'anchor 待确认 → pending_confirmation')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'unresolved' } },
    false,
  )
  assert(info.status === 'unresolved', 'unresolved → unresolved')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'structural_summary' } },
    false,
  )
  assert(info.status === 'structural', 'structural_summary → structural')
}

// ─────────── §3 构造 confirmed_mappings ───────────

console.log('\n--- §3 构造 confirmed_mappings ---')

// 1. 提交 anchor/breakpoint/explicit_override，以及已选择的 unresolved
{
  const rows = [
    { row_index: 0, rec: { ...baseRec, row_index: 0, mapping_role: 'anchor' } },
    { row_index: 1, rec: { ...baseRec, row_index: 1, mapping_role: 'inherited', client_account_code: '100201', client_account_name: '工商银行' } },
    { row_index: 2, rec: { ...baseRec, row_index: 2, mapping_role: 'structural_summary' } },
    { row_index: 3, rec: { ...baseRec, row_index: 3, mapping_role: 'breakpoint' } },
    { row_index: 4, rec: { ...baseRec, row_index: 4, mapping_role: 'explicit_override' } },
    { row_index: 5, rec: { ...baseRec, row_index: 5, mapping_role: 'unresolved' } },
  ]
  const selected: Record<number, MappingCandidate | null> = {
    0: baseCandidate,
    1: baseCandidate,
    3: baseCandidate,
    4: baseCandidate,
    5: baseCandidate,
  }
  const confirmed = buildAnchorOnlyConfirmedMappings(rows, selected)
  assert(confirmed.length === 4, '提交 anchor/breakpoint/explicit_override/已选择 unresolved')
  assert(confirmed[0].row_index === 0, '提交 anchor')
  assert(confirmed[1].row_index === 3, '提交 breakpoint')
  assert(confirmed[2].row_index === 4, '提交 explicit_override')
  assert(confirmed[3].row_index === 5, '已选择 unresolved 提交为 anchor')
  assert(confirmed[2].mapping_action === 'override', 'explicit_override 标记为 override')
  assert(confirmed[3].mapping_action === 'anchor', 'unresolved 选择后标记为 anchor')
  assert(confirmed[0].selection_source === 'user_confirmed', '有选中 → user_confirmed')
}

// 2. 无选中但后端 resolved（unique_safe）→ 自动确认提交
{
  const rows = [
    {
      row_index: 0,
      rec: {
        ...baseRec,
        mapping_role: 'anchor',
        mapping_mode: 'direct_auto',
        requires_confirmation: false,
        resolved_standard_account_id: 'sa-001',
        resolved_standard_account_code: '1002',
        resolved_standard_account_name: '银行存款',
      },
    },
  ]
  const confirmed = buildAnchorOnlyConfirmedMappings(rows, {})
  assert(confirmed.length === 1, '后端 unique_safe → 自动提交')
  assert(confirmed[0].selection_source === 'auto_confirmed', 'selection_source=auto_confirmed')
  assert(confirmed[0].standard_account_id === 'sa-001', '使用后端 resolved ID')
}

// 3. 无选中 + 后端未 resolved → 不提交（execute 必须阻断）
{
  const rows = [
    {
      row_index: 0,
      rec: { ...baseRec, mapping_role: 'anchor', resolved_standard_account_id: null },
    },
  ]
  const confirmed = buildAnchorOnlyConfirmedMappings(rows, {})
  assert(confirmed.length === 0, '未解析 anchor → 不提交')
}

// 4. inherited 行即使被选中也不应被 buildAnchorOnly 提交
{
  const rows = [
    {
      row_index: 0,
      rec: { ...baseRec, mapping_role: 'inherited', resolved_standard_account_id: 'sa-001' },
    },
  ]
  const selected: Record<number, MappingCandidate | null> = {
    0: baseCandidate,
  }
  const confirmed = buildAnchorOnlyConfirmedMappings(rows, selected)
  assert(confirmed.length === 0, 'inherited 不提交，即使有选中')
}

// ─────────── §4 显式覆盖 / 恢复继承 ───────────

console.log('\n--- §4 显式覆盖 / 恢复继承 ---')

{
  const before: Record<number, MappingCandidate | null> = {}
  const after = applyExplicitOverride(before, 0, baseCandidate)
  assert(after[0] === baseCandidate, 'applyExplicitOverride 写入 candidate')
  assert(before[0] === undefined, '原对象不被修改（不可变）')
}
{
  const before: Record<number, MappingCandidate | null> = { 0: baseCandidate }
  const after = restoreInheritance(before, 0)
  assert(after[0] === undefined, 'restoreInheritance 删除选中')
  assert(before[0] === baseCandidate, '原对象不被修改')
}

// ─────────── §5 汇总统计 ───────────

console.log('\n--- §5 汇总统计 ---')

const summary: MappingPlanSummary = {
  total_nodes: 10,
  structural_summary_count: 2,
  anchor_count: 3,
  inherited_count: 4,
  breakpoint_count: 0,
  explicit_override_count: 0,
  unresolved_count: 1,
  confirmation_required_count: 1,
  participating_leaf_count: 7,
  resolved_participating_leaf_count: 6,
}

// 1. inherited 行即使没有 selected 也不计入 unmapped
{
  const rows = [
    { row_index: 0, rec: { ...baseRec, row_index: 0, mapping_role: 'anchor' } },
    { row_index: 1, rec: { ...baseRec, row_index: 1, mapping_role: 'inherited' } },
    { row_index: 2, rec: { ...baseRec, row_index: 2, mapping_role: 'structural_summary' } },
    { row_index: 3, rec: { ...baseRec, row_index: 3, mapping_role: 'unresolved' } },
  ]
  const selected: Record<number, MappingCandidate | null> = {
    0: baseCandidate,
    // 1 inherited 不计入
    // 2 structural 不计入
    // 3 unresolved 必计入
  }
  const stats = computeStats(asRows(rows), selected, summary, true, 0, false)
  assert(stats.unmapped_count === 1, 'unmapped 仅统计 unresolved（=1）')
  assert(stats.unresolved_leaf_count === 1, 'unresolved_leaf_count 来自 summary')
  assert(stats.can_confirm === false, 'unresolved > 0 → can_confirm=false')
  assert(stats.can_execute === false, 'unresolved > 0 → can_execute=false')
}

// 2. 所有可确认行都已选 → can_confirm=true
{
  const rows = [
    { row_index: 0, rec: { ...baseRec, row_index: 0, mapping_role: 'anchor' } },
    { row_index: 1, rec: { ...baseRec, row_index: 1, mapping_role: 'inherited' } },
    { row_index: 3, rec: { ...baseRec, row_index: 3, mapping_role: 'unresolved', resolved_standard_account_id: 'sa-002', mapping_mode: 'direct_auto', requires_confirmation: false } },
  ]
  const empty_summary: MappingPlanSummary = { ...summary, unresolved_count: 0 }
  const selected: Record<number, MappingCandidate | null> = {
    0: baseCandidate,
    3: { ...baseCandidate, standard_account_id: 'sa-002', standard_account_code: '6001', standard_account_name: '主营业务收入' },
  }
  const stats = computeStats(asRows(rows), selected, empty_summary, true, 0, false)
  assert(stats.unmapped_count === 0, '全部已确认 → unmapped=0')
  assert(stats.unresolved_leaf_count === 0, 'summary unresolved=0')
  assert(stats.can_confirm === true, 'can_confirm=true')
  assert(stats.can_execute === true, '无警告且 can_confirm → can_execute=true')
}

// 3. 有警告未确认 → can_execute=false
{
  const rows: any[] = []
  const empty_summary: MappingPlanSummary = { ...summary, unresolved_count: 0 }
  const stats = computeStats(asRows(rows), {}, empty_summary, false, 0, true)
  assert(stats.can_confirm === true, 'can_confirm=true')
  assert(stats.can_execute === false, '有警告未确认 → can_execute=false')
}

// 4. blockingErrorCount > 0 → can_confirm=false
{
  const rows: any[] = []
  const empty_summary: MappingPlanSummary = { ...summary, unresolved_count: 0 }
  const stats = computeStats(asRows(rows), {}, empty_summary, true, 1, false)
  assert(stats.can_confirm === false, '有阻塞错误 → can_confirm=false')
}

// ─────────── §6 兼容性 / 老版本响应 ───────────

console.log('\n--- §6 兼容性 ---')

{
  const rec = normalizeMappingRecommend({
    row_index: 1,
    client_account_code: '1002',
    client_account_name: '银行存款',
    // 无 mapping_role 字段
    candidates: [],
  })
  assert(rec.mapping_role === 'unresolved', '老版本无 mapping_role → unresolved')
  assert(rec.requires_confirmation === false, '老版本 requires_confirmation 默认 false')
  assert(rec.suggested_standard_account_id === null, 'suggested_* 默认 null')
  assert((rec.inheritance_evidence || []).length === 0, 'inheritance_evidence 默认空数组')
}

{
  const rec = normalizeMappingRecommend({
    row_index: 1,
    client_account_code: '1002',
    client_account_name: '银行存款',
    mapping_role: 'inherited',
    inheritance_evidence: ['a', 'b'],
    suggested_standard_account_id: 'sa-099',
  })
  assert(rec.mapping_role === 'inherited', '新版本 mapping_role 保留')
  assert(rec.suggested_standard_account_id === 'sa-099', 'suggested_* 保留')
  assert((rec.inheritance_evidence || []).length === 2, 'inheritance_evidence 保留')
}

// ─────────── §7 常量集合完整性 ───────────

console.log('\n--- §7 常量集合 ---')

{
  assert(MAPPING_ROLES.length === 7, 'MAPPING_ROLES 7 项')
  assert(MAPPING_ROLES.includes('anchor'), 'MAPPING_ROLES 包含 anchor')
  assert(MAPPING_ROLES.includes('inherited'), 'MAPPING_ROLES 包含 inherited')
  assert(SUBMITTABLE_ROLES.length === 3, 'SUBMITTABLE_ROLES 3 项')
  assert(SUBMITTABLE_ROLES.includes('anchor'), 'SUBMITTABLE_ROLES 包含 anchor')
  assert(SUBMITTABLE_ROLES.includes('breakpoint'), 'SUBMITTABLE_ROLES 包含 breakpoint')
  assert(SUBMITTABLE_ROLES.includes('explicit_override'), 'SUBMITTABLE_ROLES 包含 explicit_override')
  assert(!SUBMITTABLE_ROLES.includes('inherited'), 'SUBMITTABLE_ROLES 不包含 inherited')
  assert(INHERITED_LIKE_ROLES.includes('inherited'), 'INHERITED_LIKE_ROLES 包含 inherited')
  assert(INHERITED_LIKE_ROLES.includes('structural_summary'), 'INHERITED_LIKE_ROLES 包含 structural_summary')
  assert(INHERITED_LIKE_ROLES.includes('ignored'), 'INHERITED_LIKE_ROLES 包含 ignored')
}

// ── 总结 ──

console.log(`\n--- 结果: ${pass} 通过, ${fail} 失败 ---`)
if (fail > 0) {
  throw new Error(`前端锚点继承式映射测试有 ${fail} 项失败`)
}

test('anchor inheritance mapping self-checks pass', () => {
  if (fail > 0) {
    throw new Error(`前端锚点继承式映射测试有 ${fail} 项失败`)
  }
})
