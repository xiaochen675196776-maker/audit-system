/** TASK-090：前端安全候选逻辑纯函数验证（直接导入生产函数）
 *
 * 本文件可在 Node 环境中独立运行以验证工具函数正确性。
 * 运行方式：npx tsx src/utils/mappingCandidate.test.ts
 *
 * TASK-090 强制约束：
 * - 不得在测试文件重新声明生产函数
 * - 必须从生产模块直接 import isSafeCandidate / pickUniqueAutoConfirmCandidate / getAutoConfirmCandidate
 * - 不得复制安全阈值逻辑
 * - 断言不少于 25 项
 */

import {
  isSafeCandidate,
  pickUniqueAutoConfirmCandidate,
  getAutoConfirmCandidate,
} from './mappingCandidate'
import { test } from 'vitest'

import type { MappingCandidate } from '../types'

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

// ── 测试用例 ──

console.log('\n=== TASK-090 前端安全候选逻辑验证 ===\n')

const safeBase: MappingCandidate = {
  standard_account_id: 'sa-001',
  standard_account_code: '5001',
  standard_account_name: '生产成本',
  score: 0.92,
  source: 'code_match',
  reason: '代码精确匹配且名称兼容',
  warning: null,
  auto_confirmable: true,
  compatibility_status: 'compatible',
}

// ─────────── §7.1 isSafeCandidate ───────────

console.log('--- §7.1 isSafeCandidate ---')

// 1. 合法安全候选
assert(isSafeCandidate(safeBase) === true, '合法安全候选 → 安全')

// 2. 空字符串 ID
assert(isSafeCandidate({ ...safeBase, standard_account_id: '' }) === false,
  '空字符串 ID → 不安全')

// 3. null ID
assert(isSafeCandidate({ ...safeBase, standard_account_id: null as unknown as string }) === false,
  'null ID → 不安全')

// 4. undefined ID
assert(isSafeCandidate({ ...safeBase, standard_account_id: undefined as unknown as string }) === false,
  'undefined ID → 不安全')

// 5. warning
assert(isSafeCandidate({ ...safeBase, warning: '已停用' }) === false,
  'warning 非空 → 不安全')

// 6. auto_confirmable=false
assert(isSafeCandidate({ ...safeBase, auto_confirmable: false }) === false,
  'auto_confirmable=false → 不安全')

// 7. 缺少 auto_confirmable
{
  const c = { ...safeBase } as Partial<MappingCandidate>
  delete c.auto_confirmable
  assert(isSafeCandidate(c as MappingCandidate) === false, '缺少 auto_confirmable → 不安全')
}

// 8. conflict
assert(isSafeCandidate({ ...safeBase, compatibility_status: 'conflict' }) === false,
  'compatibility_status=conflict → 不安全')

// 9. unknown
assert(isSafeCandidate({ ...safeBase, compatibility_status: 'unknown' }) === false,
  'compatibility_status=unknown → 不安全')

// 10. score 低于 0.9
assert(isSafeCandidate({ ...safeBase, score: 0.85 }) === false,
  'score=0.85 < 0.9 → 不安全')

// 11. score 等于 0.9
assert(isSafeCandidate({ ...safeBase, score: 0.9 }) === true,
  'score=0.9 → 安全（边界）')

// 12. score=NaN
assert(isSafeCandidate({ ...safeBase, score: Number.NaN }) === false,
  'score=NaN → 不安全（TASK-090）')

// 13. score=Infinity
assert(isSafeCandidate({ ...safeBase, score: Number.POSITIVE_INFINITY }) === false,
  'score=Infinity → 不安全（TASK-090）')

// 14. 停用候选
assert(isSafeCandidate({ ...safeBase, warning: '标准科目已停用' }) === false,
  '停用候选（warning）→ 不安全')

// ─────────── §7.2 pickUniqueAutoConfirmCandidate ───────────

console.log('\n--- §7.2 pickUniqueAutoConfirmCandidate ---')

// 1. 单一安全候选
{
  const picked = pickUniqueAutoConfirmCandidate([safeBase])
  assert(picked !== null, '单一安全候选 → 自动确认')
  assert(picked!.standard_account_code === '5001', '目标为 5001 生产成本')
}

// 2. 无候选
assert(pickUniqueAutoConfirmCandidate([]) === null, '无候选 → null')
assert(pickUniqueAutoConfirmCandidate(null as unknown as MappingCandidate[]) === null, 'null 候选 → null')

// 3. 全部不安全
{
  const unsafe: MappingCandidate[] = [
    { ...safeBase, warning: '停用' },
    { ...safeBase, auto_confirmable: false },
    { ...safeBase, compatibility_status: 'conflict' },
  ]
  assert(pickUniqueAutoConfirmCandidate(unsafe) === null, '全部不安全 → null')
}

// 4. 同一目标多个来源
{
  const c1 = { ...safeBase }
  const c2 = { ...safeBase, source: 'semantic_alias', score: 0.91 }
  const picked = pickUniqueAutoConfirmCandidate([c1, c2])
  assert(picked !== null, '同一目标多来源 → 自动确认')
  assert(picked!.standard_account_id === 'sa-001', '目标 ID 一致')
}

// 5. 多个不同安全目标
{
  const other = {
    ...safeBase,
    standard_account_id: 'sa-002',
    standard_account_code: '4003',
    standard_account_name: '资本公积',
  }
  const picked = pickUniqueAutoConfirmCandidate([safeBase, other])
  assert(picked === null, '多个不同安全目标 → 不自动确认')
}

// 6. 一个安全目标 + 多个不安全目标
{
  const unsafe = [
    { ...safeBase, warning: '停用' },
    { ...safeBase, auto_confirmable: false, standard_account_id: 'sa-003' },
  ]
  const picked = pickUniqueAutoConfirmCandidate([safeBase, ...unsafe])
  assert(picked !== null, '一安全 + 多不安全 → 仅安全被选中')
  assert(picked!.standard_account_id === 'sa-001', '选中的是 sa-001')
}

// 7. 空 ID 候选与正常候选混合
{
  const empty = { ...safeBase, standard_account_id: '', standard_account_code: 'X' }
  const picked = pickUniqueAutoConfirmCandidate([empty, safeBase])
  assert(picked !== null, '空 ID + 正常 → 仅正常被选中（TASK-090）')
  assert(picked!.standard_account_id === 'sa-001', '空 ID 候选被排除')
}

// 8. 两个空 ID 候选
{
  const e1 = { ...safeBase, standard_account_id: '', standard_account_code: 'X' }
  const e2 = { ...safeBase, standard_account_id: '', standard_account_code: 'Y' }
  const picked = pickUniqueAutoConfirmCandidate([e1, e2])
  assert(picked === null, '两个空 ID 候选 → null（TASK-090）')
}

// 9. 相同 ID 不同 score（去重后仍自动确认）
{
  const high = { ...safeBase, score: 0.95 }
  const low = { ...safeBase, score: 0.91 }
  const picked = pickUniqueAutoConfirmCandidate([low, high])
  assert(picked !== null, '相同 ID 不同 score → 去重后自动确认')
  assert(picked!.standard_account_id === 'sa-001', '目标 ID 一致')
}

// 10. 相同 ID 不同 source
{
  const code = { ...safeBase, source: 'code_match' }
  const name = { ...safeBase, source: 'semantic_alias' }
  const picked = pickUniqueAutoConfirmCandidate([code, name])
  assert(picked !== null, '相同 ID 不同 source → 去重后自动确认')
  assert(picked!.standard_account_id === 'sa-001', '目标 ID 一致')
}

// ─────────── §7.3 getAutoConfirmCandidate ───────────

console.log('\n--- §7.3 getAutoConfirmCandidate ---')

// 1. 后端返回合法安全候选
{
  const picked = getAutoConfirmCandidate([], safeBase)
  assert(picked === safeBase, '后端合法 → 直接接受')
}

// 2. 后端返回 warning 候选
{
  const warned = { ...safeBase, warning: '请确认' }
  const picked = getAutoConfirmCandidate([safeBase], warned)
  assert(picked !== null, '后端不安全 → 回退到本地')
  assert(picked !== warned, '不直接使用不安全后端候选')
  assert(picked!.warning === null, '选中本地安全候选')
}

// 3. 后端返回空 ID 候选（TASK-090 强制）
{
  const empty = { ...safeBase, standard_account_id: '' }
  const picked = getAutoConfirmCandidate([safeBase], empty)
  assert(picked !== null, '后端空 ID → 回退到本地（TASK-090）')
  assert(picked!.standard_account_id === 'sa-001', '本地安全候选被选中')
}

// 4. 后端返回 conflict 候选
{
  const conflict: MappingCandidate = { ...safeBase, compatibility_status: 'conflict' }
  const picked = getAutoConfirmCandidate([safeBase], conflict)
  assert(picked !== null, '后端 conflict → 回退到本地')
  assert(picked!.compatibility_status === 'compatible', '选中本地兼容候选')
}

// 5. 后端不安全 + 本地唯一安全
{
  const warned = { ...safeBase, warning: '停用' }
  const picked = getAutoConfirmCandidate([safeBase], warned)
  assert(picked !== null, '后端不安全 + 本地唯一安全 → 本地')
  assert(picked!.standard_account_id === 'sa-001', '本地 sa-001 被选中')
}

// 6. 后端不安全 + 本地多个安全目标
{
  const other = {
    ...safeBase,
    standard_account_id: 'sa-002',
    standard_account_code: '4003',
    standard_account_name: '资本公积',
  }
  const warned = { ...safeBase, warning: '停用' }
  const picked = getAutoConfirmCandidate([safeBase, other], warned)
  assert(picked === null, '后端不安全 + 本地多安全目标 → null')
}

// 7. 后端候选为空 + 本地唯一安全
{
  const picked = getAutoConfirmCandidate([safeBase], null)
  assert(picked !== null, '后端 null + 本地唯一安全 → 本地')
  assert(picked!.standard_account_id === 'sa-001', '本地 sa-001 被选中')
}

// 8. 后端候选为空 + 本地无安全候选
{
  const unsafe = [{ ...safeBase, warning: '停用' }]
  const picked = getAutoConfirmCandidate(unsafe, null)
  assert(picked === null, '后端 null + 本地无安全 → null')
}

// 9. 后端候选合法但不在候选列表中
{
  const otherId = { ...safeBase, standard_account_id: 'sa-999' }
  const picked = getAutoConfirmCandidate([safeBase], otherId)
  // 后端候选优先于本地（即使不在 candidates 列表中）
  assert(picked === otherId, '后端候选即使不在列表也优先')
}

// 10. 后端候选 ID 为空时不得直接接受（TASK-090 强制）
{
  const empty = { ...safeBase, standard_account_id: '' }
  const picked = getAutoConfirmCandidate([safeBase], empty)
  assert(picked !== null, '后端空 ID 不得被直接接受（TASK-090）')
  assert(picked !== empty, '回退到本地候选')
  assert(picked!.standard_account_id === 'sa-001', '本地 sa-001 被选中')
}

// ── 总结 ──

console.log(`\n--- 结果: ${pass} 通过, ${fail} 失败 ---`)
if (fail > 0) {
  throw new Error(`前端安全候选测试有 ${fail} 项失败`)
}

test('mapping candidate self-checks pass', () => {
  if (fail > 0) {
    throw new Error(`前端安全候选测试有 ${fail} 项失败`)
  }
})
