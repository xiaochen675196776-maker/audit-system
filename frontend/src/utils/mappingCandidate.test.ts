/** TASK-088：前端安全候选逻辑纯函数验证
 *
 * 本文件可在 Node 环境中独立运行以验证工具函数正确性。
 * 运行方式：npx tsx src/utils/mappingCandidate.test.ts
 * 或手动编译后执行。
 */

// ── 重新声明类型和函数以便独立运行 ──

interface MappingCandidate {
  standard_account_id: string
  standard_account_code: string
  standard_account_name: string
  score: number
  source: string
  reason: string
  warning?: string | null
  auto_confirmable?: boolean
  compatibility_status?: string
  compatibility_reason?: string
  evidence?: string[]
}

const SAFE_CANDIDATE_MIN_SCORE = 0.9

function isSafeCandidate(c: MappingCandidate): boolean {
  if (c.warning) return false
  if (c.auto_confirmable !== true) return false
  if (c.compatibility_status !== 'compatible') return false
  return c.score >= SAFE_CANDIDATE_MIN_SCORE
}

function pickUniqueAutoConfirmCandidate(
  candidates: MappingCandidate[]
): MappingCandidate | null {
  if (!candidates || candidates.length === 0) return null

  const safe = candidates.filter(isSafeCandidate)
  if (safe.length === 0) return null

  const seen = new Map<string, MappingCandidate>()
  for (const c of safe) {
    const id = c.standard_account_id
    if (!seen.has(id)) {
      seen.set(id, c)
    }
  }

  if (seen.size === 0) return null
  if (seen.size === 1) {
    return safe[0]
  }

  return null
}

// ── 测试断言 ──

let pass = 0
let fail = 0

function assert(condition: boolean, label: string) {
  if (condition) {
    pass++
    console.log(`  ✅ ${label}`)
  } else {
    fail++
    console.error(`  ❌ ${label}`)
  }
}

// ── 测试用例 ──

console.log('\n═══ TASK-088 前端安全候选逻辑验证 ═══\n')

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

// 1. 单一安全候选 → 应自动确认
{
  const candidates: MappingCandidate[] = [safeBase]
  const picked = pickUniqueAutoConfirmCandidate(candidates)
  assert(picked !== null, '单一安全候选 → 自动确认')
  assert(picked!.standard_account_code === '5001', '目标为 5001 生产成本')
}

// 2. 多个来源指向同一标准科目 → 应自动确认
{
  const c1 = { ...safeBase }
  const c2 = { ...safeBase, source: 'semantic_alias', score: 0.91 }
  const picked = pickUniqueAutoConfirmCandidate([c1, c2])
  assert(picked !== null, '多来源同目标 → 自动确认')
  assert(picked!.standard_account_id === 'sa-001', '目标 ID 一致')
}

// 3. 多个安全候选指向不同标准科目 → 不自动确认
{
  const other = { ...safeBase, standard_account_id: 'sa-002', standard_account_code: '4003', standard_account_name: '资本公积' }
  const picked = pickUniqueAutoConfirmCandidate([safeBase, other])
  assert(picked === null, '多个不同安全目标 → 不自动确认')
}

// 4. 带 warning 候选 → 不安全
{
  const warned = { ...safeBase, warning: '标准科目已停用' }
  assert(!isSafeCandidate(warned), '带 warning → 不安全')
}

// 5. auto_confirmable=false → 不安全
{
  const noAuto = { ...safeBase, auto_confirmable: false }
  assert(!isSafeCandidate(noAuto), 'auto_confirmable=false → 不安全')
}

// 6. compatibility_status=conflict → 不安全
{
  const conflict = { ...safeBase, compatibility_status: 'conflict' }
  assert(!isSafeCandidate(conflict), 'compatibility_status=conflict → 不安全')
}

// 7. compatibility_status=unknown → 不安全
{
  const unknown = { ...safeBase, compatibility_status: 'unknown' }
  assert(!isSafeCandidate(unknown), 'compatibility_status=unknown → 不安全')
}

// 8. 分数低于安全阈值 → 不安全
{
  const lowScore = { ...safeBase, score: 0.85 }
  assert(!isSafeCandidate(lowScore), 'score=0.85 < 0.9 → 不安全')
}

// 9. 候选缺少 auto_confirmable → 不安全
{
  const missingField = { ...safeBase }
  delete (missingField as any).auto_confirmable
  assert(!isSafeCandidate(missingField), '缺少 auto_confirmable → 不安全')
}

// 10. 候选标准科目 ID 为空 → 仍判断为安全（由后端保证）
{
  const emptyId = { ...safeBase, standard_account_id: '' }
  // isSafeCandidate 不检查 ID 是否为空（该职责在后端）
  assert(isSafeCandidate(emptyId), '空 ID 的候选 isSafeCandidate 仍可返回 true（后端保证）')
}

// 11. 带 warning 且 score 高 → 不自动确认
{
  const warnedHigh = { ...safeBase, score: 0.95, warning: '请确认' }
  const picked = pickUniqueAutoConfirmCandidate([warnedHigh])
  assert(picked === null, 'warning + 高分 → 不自动确认')
}

// 12. 多个候选含 warning → 只有安全候选可被选中
{
  const warned = { ...safeBase, warning: '停用', auto_confirmable: false, compatibility_status: 'conflict' }
  const picked = pickUniqueAutoConfirmCandidate([warned, safeBase])
  assert(picked !== null, '混合安全与不安全 → 安全候选被选中')
  assert(picked!.warning === null, '选中候选无 warning')
}

console.log(`\n─── 结果: ${pass} 通过, ${fail} 失败 ───`)
if (fail > 0) {
  process.exit(1)
}
