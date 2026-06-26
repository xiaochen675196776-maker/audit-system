/** TASK-087：前端候选安全判定和自动选中工具函数 */

import type { MappingCandidate } from '@/types'

/** 安全候选最小分数阈值 */
const SAFE_CANDIDATE_MIN_SCORE = 0.9

/**
 * 判定是否为安全候选。
 *
 * 必须同时满足：
 * - auto_confirmable === true（显式标记）
 * - warning 为空
 * - score >= 0.9
 * - compatibility_status === 'compatible'
 *
 * 缺少 auto_confirmable 字段的旧候选按保守方式处理（视为不安全）。
 */
export function isSafeCandidate(c: MappingCandidate): boolean {
  if (c.warning) return false
  if (c.auto_confirmable !== true) return false
  if (c.compatibility_status !== 'compatible') return false
  return c.score >= SAFE_CANDIDATE_MIN_SCORE
}

/**
 * 唯一安全候选自动选中。
 *
 * 规则：
 * 1. 筛选所有安全候选
 * 2. 按 standard_account_id 去重
 * 3. 只有一个不同目标 → 返回该候选（如有多来源，返回 source 优先级最高者）
 * 4. 多个不同安全目标 → 返回 null
 * 5. 无安全候选 → 返回 null
 */
export function pickUniqueAutoConfirmCandidate(
  candidates: MappingCandidate[]
): MappingCandidate | null {
  if (!candidates || candidates.length === 0) return null

  const safe = candidates.filter(isSafeCandidate)
  if (safe.length === 0) return null

  // 按 standard_account_id 去重
  const seen = new Map<string, MappingCandidate>()
  for (const c of safe) {
    const id = c.standard_account_id
    if (!seen.has(id)) {
      seen.set(id, c)
    }
  }

  if (seen.size === 0) return null
  if (seen.size === 1) {
    // 唯一目标：返回 source 优先级最高的候选
    return safe[0]
  }

  // 多个不同安全目标：不自动确认
  return null
}

/**
 * 旧版兼容函数（从后端 auto_confirm_candidate 或前端安全候选中选择）。
 * 优先使用后端返回的 auto_confirm_candidate，其次使用前端本地计算。
 */
export function getAutoConfirmCandidate(
  candidates: MappingCandidate[],
  backendAutoConfirm?: MappingCandidate | null
): MappingCandidate | null {
  if (backendAutoConfirm && isSafeCandidate(backendAutoConfirm)) {
    return backendAutoConfirm
  }
  return pickUniqueAutoConfirmCandidate(candidates)
}
