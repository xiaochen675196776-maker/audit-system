/**
 * TASK-094B 前端锚点继承式映射工具函数测试
 *
 * 直接从生产模块导入函数，禁止复制实现。
 * 运行方式：npx tsx src/utils/anchorInheritanceMapping.test.ts
 *
 * TASK-094B 重点：
 * - explicit_override 已开启但未选择：requiresMapping=true、shouldSubmit=false
 * - override 提交不得使用原 inherited resolved 兜底
 * - rowDisplayStatus 接收 state（不再用 hasSelected bool）
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
  computeDynamicUnresolvedCount,
  effectiveMappingRole,
  countEmptyOverrides,
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

// 6. explicit_override 要求确认 + 必须有用户选择才能提交（TASK-094B）
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'explicit_override', requires_confirmation: true },
  }
  assert(rowRequiresMapping(row) === true, 'explicit_override 要求确认')
  // 没有 explicitOverrideRows 标记时，单纯 explicit_override 不再单独视为待确认
  // （必须由用户在组件点击「单独映射」才会进入 override 角色）
  assert(rowShouldSubmitMapping(row) === false, 'explicit_override 无用户选择 → 不提交')
  // 用户点击 override + 选中 → 提交
  assert(
    rowShouldSubmitMapping(row, {
      explicitOverrideRows: { 0: true },
      selectedByRow: { 0: baseCandidate },
    }) === true,
    'explicit_override + 选中 → 提交',
  )
  // 用户点击 override + 未选择 → 阻断（TASK-094B 反例）
  assert(
    rowShouldSubmitMapping(row, {
      explicitOverrideRows: { 0: true },
    }) === false,
    'explicit_override 已开启但未选择 → 不提交（红线）',
  )
  assert(
    rowRequiresMapping(row, {
      explicitOverrideRows: { 0: true },
    }) === true,
    'explicit_override 已开启但未选择 → 仍需映射（计入未映射）',
  )
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
    {},
  )
  assert(info.status === 'inherited', 'inherited 未 override → inherited 状态')
  assert(info.label === '自动继承', 'inherited 未 override 标签 = 自动继承')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'inherited' } },
    { selectedByRow: { 0: baseCandidate } },
  )
  assert(info.status === 'overridden', 'inherited 已 override → overridden')
  assert(info.label === '显式覆盖已确认', 'inherited 已 override 标签 = 显式覆盖已确认')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'anchor', requires_confirmation: false, resolved_standard_account_id: 'sa-001', auto_confirm_status: 'unique_safe' as any } },
    {},
  )
  assert(info.status === 'auto_confirmed', 'anchor unique_safe + 无 selection → auto_confirmed')
  assert(info.label === '自动确认', 'anchor unique_safe 标签 = 自动确认')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'anchor', requires_confirmation: true } },
    {},
  )
  assert(info.status === 'pending_confirmation', 'anchor 待确认 → pending_confirmation')
  assert(info.label.includes('映射锚点'), 'anchor 待确认 标签包含 映射锚点')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'unresolved' } },
    {},
  )
  assert(info.status === 'unresolved', 'unresolved → unresolved')
  assert(info.label === '未解决', 'unresolved 标签 = 未解决')
}
{
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'structural_summary' } },
    {},
  )
  assert(info.status === 'structural', 'structural_summary → structural')
  assert(info.label === '结构汇总', 'structural_summary 标签 = 结构汇总（非父级不入库）')
}
{
  // TASK-094B：explicit_override 已开启但未选择 → 显式覆盖待选择
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'explicit_override' } },
    { explicitOverrideRows: { 0: true } },
  )
  assert(
    info.status === 'explicit_override_pending',
    'explicit_override + 未选择 → explicit_override_pending',
  )
  assert(
    info.label === '显式覆盖待选择',
    'explicit_override + 未选择 标签 = 显式覆盖待选择',
  )
}
{
  // TASK-094B：explicit_override + 选中 → 显式覆盖已确认
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'explicit_override' } },
    { explicitOverrideRows: { 0: true }, selectedByRow: { 0: baseCandidate } },
  )
  assert(
    info.status === 'explicit_override_confirmed',
    'explicit_override + 已选择 → explicit_override_confirmed',
  )
  assert(
    info.label === '显式覆盖已确认',
    'explicit_override + 已选择 标签 = 显式覆盖已确认',
  )
}
{
  // TASK-094B：非末级 anchor（is_leaf=false）仍展示映射锚点
  const info = rowDisplayStatus(
    {
      row_index: 0,
      rec: { ...baseRec, mapping_role: 'anchor', requires_confirmation: false, resolved_standard_account_id: 'sa-001', auto_confirm_status: 'unique_safe' as any },
      is_leaf: false,
      is_summary: true,
      participates_in_entry: false,
    },
    {},
  )
  assert(info.label !== '父级不入库', '非末级 anchor 不显示 父级不入库')
  assert(info.status === 'auto_confirmed', '非末级 anchor unique_safe → auto_confirmed')
}
{
  // TASK-094B：breakpoint 待确认 → 继承中断点 标签
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'breakpoint', requires_confirmation: true } },
    {},
  )
  assert(info.status === 'pending_confirmation', 'breakpoint 待确认 → pending_confirmation')
  assert(info.label.includes('继承中断点'), 'breakpoint 待确认 标签包含 继承中断点')
}
{
  // TASK-094B：ignored → 已忽略
  const info = rowDisplayStatus(
    { row_index: 0, rec: { ...baseRec, mapping_role: 'anchor' }, is_ignored: true },
    {},
  )
  assert(info.status === 'ignored', 'is_ignored=true → ignored')
  assert(info.label === '已忽略', 'is_ignored 标签 = 已忽略')
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
  const state: any = {
    explicitOverrideRows: { 4: true },
    selectedByRow: selected,
  }
  const confirmed = buildAnchorOnlyConfirmedMappings(rows, selected, state)
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

// 5. TASK-094B 反例：explicit_override 已开启但未选择 → 不提交（不得使用原 inherited resolved 兜底）
{
  const rows = [
    {
      row_index: 0,
      rec: {
        ...baseRec,
        mapping_role: 'inherited',
        resolved_standard_account_id: 'sa-inherited',
        resolved_standard_account_code: '1002',
        resolved_standard_account_name: '银行存款',
      },
    },
  ]
  const state: any = {
    explicitOverrideRows: { 0: true },
    selectedByRow: {},
  }
  const confirmed = buildAnchorOnlyConfirmedMappings(rows, {}, state)
  assert(
    confirmed.length === 0,
    'override 已开启但未选择 → confirmed_mappings 不应包含该行（红线）',
  )
  // 即使 selectedByRow 被显式传 null，仍然必须包含 explicitOverrideRows=true 的状态
  assert(
    rowShouldSubmitMapping(rows[0] as any, state) === false,
    'override 已开启但未选择 → rowShouldSubmitMapping=false（红线）',
  )
  assert(
    rowRequiresMapping(rows[0] as any, state) === true,
    'override 已开启但未选择 → rowRequiresMapping=true（计入未映射）',
  )
}

// 6. TASK-094B：override 目标必须使用用户选择的标准科目，不得使用原 inherited resolved
{
  const userCandidate: MappingCandidate = {
    ...baseCandidate,
    standard_account_id: 'sa-user-override',
    standard_account_code: '6603',
    standard_account_name: '用户指定的覆盖科目',
  }
  const rows = [
    {
      row_index: 0,
      rec: {
        ...baseRec,
        mapping_role: 'inherited',
        resolved_standard_account_id: 'sa-inherited',
        resolved_standard_account_code: '1002',
        resolved_standard_account_name: '银行存款',
      },
    },
  ]
  const state: any = {
    explicitOverrideRows: { 0: true },
    selectedByRow: { 0: userCandidate },
  }
  const confirmed = buildAnchorOnlyConfirmedMappings(rows, { 0: userCandidate }, state)
  assert(confirmed.length === 1, 'override + 用户选择 → 提交')
  assert(confirmed[0].standard_account_id === 'sa-user-override', 'override 目标 = 用户选择')
  assert(
    confirmed[0].standard_account_code === '6603',
    'override 目标代码 = 用户选择（不是原 inherited 1002）',
  )
  assert(confirmed[0].selection_source === 'user_confirmed', 'override selection_source = user_confirmed')
  assert(confirmed[0].mapping_action === 'override', 'override mapping_action = override')
  assert(confirmed[0].apply_to_descendants === true, 'override apply_to_descendants = true')
}

// 7. TASK-094B：恢复继承后 explicit_override 行不再提交
{
  const rows = [
    {
      row_index: 0,
      rec: {
        ...baseRec,
        mapping_role: 'inherited',
        resolved_standard_account_id: 'sa-inherited',
        resolved_standard_account_code: '1002',
        resolved_standard_account_name: '银行存款',
      },
    },
  ]
  // 模拟恢复继承：清空 override 与选择
  const state: any = {
    explicitOverrideRows: {},
    selectedByRow: {},
  }
  const confirmed = buildAnchorOnlyConfirmedMappings(rows, {}, state)
  assert(confirmed.length === 0, '恢复继承后 → 不提交')
  assert(rowShouldSubmitMapping(rows[0] as any, state) === false, '恢复继承后 → rowShouldSubmitMapping=false')
  assert(rowRequiresMapping(rows[0] as any, state) === false, '恢复继承后 → rowRequiresMapping=false（恢复 inherited）')
  assert(effectiveMappingRole(rows[0] as any, state) === 'inherited', '恢复继承后 effective role=inherited')
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

// ─────────── §8 TASK-094B 反例与闭环 ───────────

console.log('\n--- §8 TASK-094B 反例与闭环 ---')

// 8.1 inherited + explicitOverrideRows=true + 无选择 → requiresMapping=true, shouldSubmit=false
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'inherited' },
  }
  const state: any = { explicitOverrideRows: { 0: true } }
  assert(
    rowRequiresMapping(row, state) === true,
    '8.1 inherited override 开启未选择 → requiresMapping=true',
  )
  assert(
    rowShouldSubmitMapping(row, state) === false,
    '8.1 inherited override 开启未选择 → shouldSubmit=false',
  )
  assert(
    effectiveMappingRole(row, state) === 'explicit_override',
    '8.1 inherited override 开启 → effective role = explicit_override',
  )
  assert(
    countEmptyOverrides([row], state) === 1,
    '8.1 inherited override 开启未选择 → countEmptyOverrides=1',
  )
}

// 8.2 inherited + explicitOverrideRows=true + 选中 → shouldSubmit=true，使用用户选择
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'inherited' },
  }
  const state: any = {
    explicitOverrideRows: { 0: true },
    selectedByRow: { 0: baseCandidate },
  }
  assert(
    rowShouldSubmitMapping(row, state) === true,
    '8.2 inherited override + 选中 → shouldSubmit=true',
  )
  assert(
    countEmptyOverrides([row], state) === 0,
    '8.2 inherited override + 选中 → countEmptyOverrides=0',
  )
}

// 8.3 恢复继承：清空 override + 清空选择 → effective role=inherited，requiresMapping=false
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'inherited' },
  }
  // 模拟组件内 stdRestoreInheritance 后的状态
  const state: any = {
    explicitOverrideRows: {},
    selectedByRow: {},
    ignoredRows: {},
  }
  assert(
    effectiveMappingRole(row, state) === 'inherited',
    '8.3 恢复继承后 effective role = inherited',
  )
  assert(
    rowRequiresMapping(row, state) === false,
    '8.3 恢复继承后 requiresMapping=false（不再计入未映射）',
  )
  assert(
    rowShouldSubmitMapping(row, state) === false,
    '8.3 恢复继承后 shouldSubmit=false',
  )
}

// 8.4 unresolved + 选择 → effective role=anchor，应该计入未映射减少
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'unresolved', resolved_standard_account_id: null },
  }
  // 选择前
  assert(
    effectiveMappingRole(row, {}) === 'unresolved',
    '8.4 unresolved 未选择 → effective role = unresolved',
  )
  assert(rowRequiresMapping(row, {}) === true, '8.4 unresolved 未选择 → requiresMapping=true')
  // 选择后
  const state: any = { selectedByRow: { 0: baseCandidate } }
  assert(
    effectiveMappingRole(row, state) === 'anchor',
    '8.4 unresolved 选择后 → effective role = anchor',
  )
  assert(rowRequiresMapping(row, state) === false, '8.4 unresolved 选择后 → requiresMapping=false')
  assert(rowShouldSubmitMapping(row, state) === true, '8.4 unresolved 选择后 → shouldSubmit=true')
}

// 8.5 unresolved 清除选择 → 回到 unresolved
{
  const row = {
    row_index: 0,
    rec: { ...baseRec, mapping_role: 'unresolved' },
  }
  const state: any = { selectedByRow: {} }
  assert(effectiveMappingRole(row, state) === 'unresolved', '8.5 清除 unresolved 选择 → role=unresolved')
  assert(rowRequiresMapping(row, state) === true, '8.5 清除 unresolved 选择 → requiresMapping=true')
}

// 8.6 computeDynamicUnresolvedCount 区分已选择/未选择
{
  const rows = [
    { row_index: 0, rec: { ...baseRec, mapping_role: 'unresolved' } },
    { row_index: 1, rec: { ...baseRec, mapping_role: 'unresolved' } },
    { row_index: 2, rec: { ...baseRec, mapping_role: 'inherited' } },
    { row_index: 3, rec: { ...baseRec, mapping_role: 'anchor' } },
  ]
  // 全部未选：unresolved=2
  assert(
    computeDynamicUnresolvedCount(rows as any, {}) === 2,
    '8.6 全部未选 → unresolved=2',
  )
  // 选择 row 0 → unresolved=1
  assert(
    computeDynamicUnresolvedCount(rows as any, { selectedByRow: { 0: baseCandidate } }) === 1,
    '8.6 选择 1 个 unresolved → unresolved=1',
  )
  // 全部 unresolved 已选 → unresolved=0
  assert(
    computeDynamicUnresolvedCount(rows as any, {
      selectedByRow: { 0: baseCandidate, 1: baseCandidate },
    }) === 0,
    '8.6 全部 unresolved 已选 → unresolved=0',
  )
}

// 8.7 ignored 行不计入 unresolved 也不计入 unmapped
{
  const rows = [
    { row_index: 0, rec: { ...baseRec, mapping_role: 'unresolved' }, is_ignored: true },
  ]
  assert(
    computeDynamicUnresolvedCount(rows as any, {}) === 0,
    '8.7 ignored 行 → unresolved=0',
  )
  assert(rowRequiresMapping(rows[0] as any, {}) === false, '8.7 ignored 行 → requiresMapping=false')
  assert(rowShouldSubmitMapping(rows[0] as any, {}) === false, '8.7 ignored 行 → shouldSubmit=false')
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
