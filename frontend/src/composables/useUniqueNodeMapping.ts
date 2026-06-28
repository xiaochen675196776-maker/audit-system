/**
 * TASK-096A：前端唯一 NodeKey 确认 composable
 *
 * 核心职责：
 * 1. 把后端 `unique_mapping_nodes` + `row_node_bindings` 转换为前端 `UniqueNodeReviewRow[]`
 * 2. 用 Map 预索引，避免 O(nodes × rows) 的反向查找
 * 3. 维护 NodeKey 级本地状态（selectedByNodeKey / explicitOverrideNodeKeys / ...）
 * 4. 直接由 NodeKey 状态构造 confirmed_node_mappings（禁止先生成 row mappings 再折叠）
 * 5. 在旧后端无 unique_mapping_nodes 时仍提供行级兼容路径
 * 6. 旧行级模式下检测同 node_key 不同目标冲突（阻止确认/执行）
 *
 * 设计原则：
 * - 纯 Vue 3 Composition API；不依赖具体 UI 组件；
 * - 主表渲染、stats、提交构造全部按 NodeKey 口径；
 * - 单测可脱离 element-plus 直接挂载。
 */

import { computed, reactive, ref, watch, type ComputedRef, type Ref } from 'vue'
import { buildAnchorOnlyConfirmedMappings } from '@/utils/anchorInheritanceMapping'
import type {
  ConfirmedMapping,
  ConfirmedNodeMapping,
  MappingCandidate,
  RowNodeBinding,
  StdAnalyzeResponse,
  UniqueMappingNode,
  UniqueNodeReviewRow,
  NodeMappingLocalState,
  NodeMappingStats,
  NodeSelectionConflict,
} from '@/types'

// re-export for callers that need the type
export type { NodeMappingStats }

// ===== 输入 =====

export interface UseUniqueNodeMappingOptions {
  /** 当前 analyze 响应；为 null 时进入空状态 */
  analyzeResult: Ref<StdAnalyzeResponse | null>
  /** analyze 返回的 warnings（来自 analyze.warnings） */
  warnings?: Ref<Array<{ row_index: number | null; code: string; message: string; category: string }>>
  /** warnings 是否已确认 */
  warningsConfirmed?: Ref<boolean>
}

export interface UseUniqueNodeMappingReturn {
  // ===== 主表数据 =====
  /** 是否进入 NodeKey 模式（analyze.unique_mapping_nodes 非空） */
  isNodeKeyMode: ComputedRef<boolean>
  /** 前端组合的唯一节点确认行 */
  uniqueNodeRows: ComputedRef<UniqueNodeReviewRow[]>
  /** 按 row-key=node_key 的去重 Map（用于 O(1) 查找） */
  nodeByKey: ComputedRef<Map<string, UniqueNodeReviewRow>>
  /** 按 node_key 分组的绑定原始行 */
  rowBindingsByNodeKey: ComputedRef<Map<string, RowNodeBinding[]>>
  /** 按 row_index 索引的代表行数据（hierarchy + rec） */
  rowByIndex: ComputedRef<Map<number, { row_index: number; client_account_code: string | null; client_account_name: string | null; level: number | null; is_leaf: boolean | null; is_summary: boolean | null }>>

  // ===== 本地状态（NodeKey 模式的主状态） =====
  selectedByNodeKey: Ref<Record<string, MappingCandidate | null | undefined>>
  explicitOverrideNodeKeys: Ref<Record<string, boolean | undefined>>
  ignoredNodeKeys: Ref<Record<string, boolean | undefined>>
  expandedNodeKeys: Ref<Record<string, boolean | undefined>>
  searchQueriesByNodeKey: Ref<Record<string, string>>
  searchResultsByNodeKey: Ref<Record<string, any[]>>

  // ===== 旧行级状态（仅在 NodeKey 模式下保留兼容入口；旧后端无 unique_mapping_nodes 时主用） =====
  selectedByRow: Ref<Record<number, MappingCandidate | null | undefined>>
  explicitOverrideRows: Ref<Record<number, boolean | undefined>>
  confirmedUnresolvedRows: Ref<Record<number, boolean | undefined>>
  ignoredRows: Ref<Record<number, boolean | undefined>>

  // ===== 统计 =====
  nodeStats: ComputedRef<NodeMappingStats>

  // ===== 角色与判定 =====
  effectiveNodeMappingRole(node: UniqueNodeReviewRow): string
  nodeRequiresMapping(node: UniqueNodeReviewRow): boolean
  nodeShouldSubmitMapping(node: UniqueNodeReviewRow): boolean
  nodeDisplayStatus(node: UniqueNodeReviewRow): NodeDisplayInfo
  nodeWarnings(node: UniqueNodeReviewRow): string[]
  /** 当前节点在 warnings 列表里出现的 row_index */
  warningRowIndexesForNode(node: UniqueNodeReviewRow): number[]

  // ===== 操作 =====
  selectNodeCandidate(nodeKey: string, candidate: MappingCandidate): void
  clearNodeCandidate(nodeKey: string): void
  setNodeOverride(nodeKey: string): void
  restoreNodeInheritance(nodeKey: string): void
  setNodeIgnored(nodeKey: string, ignored: boolean): void
  toggleNodeExpanded(nodeKey: string): void

  // ===== 提交构造 =====
  buildConfirmedNodeMappingsFromNodeState(): ConfirmedNodeMapping[]
  /** 旧行级兼容构造：当后端无 unique_mapping_nodes 时，行级选择折叠为 confirmed_mappings */
  buildLegacyConfirmedMappings(): ConfirmedMapping[]
  /** 旧行级兼容：检测同 node_key 不同目标冲突 */
  detectNodeSelectionConflicts(): NodeSelectionConflict[]

  // ===== 警告与启用判定 =====
  totalWarningNodes: ComputedRef<number>
  blockingErrorCount: ComputedRef<number>
  canConfirm: ComputedRef<boolean>
  canExecute: ComputedRef<boolean>
  confirmHint: ComputedRef<string>

  // ===== 工具 =====
  /** 标准科目搜索（直接调用 API；与原 stdSearchAccounts 行为一致） */
  searchStandardAccounts(nodeKey: string, keyword: string): Promise<any[]>
  /** 标准科目搜索（旧行级） */
  searchStandardAccountsForRow(rowIndex: number, keyword: string): Promise<any[]>

  /** 重置（切换文件 / batch 时清空） */
  reset(): void
  /** 由外部 analyze 响应注入（与 DataImportView 集成用） */
  setAnalyzeResult(data: StdAnalyzeResponse): void
}

// ===== Node 显示状态类型（与 anchorInheritanceMapping 保持并行） =====

export type NodeDisplayStatus =
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
  | 'all_bound_rows_ignored'

export interface NodeDisplayInfo {
  status: NodeDisplayStatus
  label: string
  type: '' | 'success' | 'warning' | 'info' | 'danger' | 'primary'
}

// ===== 实现 =====

export function useUniqueNodeMapping(
  options: UseUniqueNodeMappingOptions,
): UseUniqueNodeMappingReturn {
  const { analyzeResult, warnings, warningsConfirmed } = options

  // ---- 本地状态（NodeKey 主状态） ----

  const selectedByNodeKey = ref<Record<string, MappingCandidate | null | undefined>>({})
  const explicitOverrideNodeKeys = ref<Record<string, boolean | undefined>>({})
  const ignoredNodeKeys = ref<Record<string, boolean | undefined>>({})
  const expandedNodeKeys = ref<Record<string, boolean | undefined>>({})
  const searchQueriesByNodeKey = ref<Record<string, string>>({})
  const searchResultsByNodeKey = ref<Record<string, any[]>>({})

  // ---- 旧行级状态（兼容） ----

  const selectedByRow = ref<Record<number, MappingCandidate | null | undefined>>({})
  const explicitOverrideRows = ref<Record<number, boolean | undefined>>({})
  const confirmedUnresolvedRows = ref<Record<number, boolean | undefined>>({})
  const ignoredRows = ref<Record<number, boolean | undefined>>({})

  // ---- 判定 ----

  const isNodeKeyMode = computed(() => {
    const nodes = analyzeResult.value?.unique_mapping_nodes
    return Array.isArray(nodes) && nodes.length > 0
  })

  /**
   * 主表数据：从 unique_mapping_nodes 出发，组合前端展示字段。
   * 复杂度：O(unique_nodes + row_node_bindings)
   * - 一次遍历 unique_mapping_nodes → uniqueNodeRows
   * - 一次遍历 row_node_bindings 构建 bindingsByNodeKey
   * - 一次遍历 hierarchy + recommendations 构建 rowByIndex
   * 禁止对每个节点反复 find 全部 rows。
   */
  const uniqueNodeRows = computed<UniqueNodeReviewRow[]>(() => {
    const analyze = analyzeResult.value
    if (!analyze || !Array.isArray(analyze.unique_mapping_nodes)) return []

    const nodes = analyze.unique_mapping_nodes
    const bindings = analyze.row_node_bindings || []

    // 预索引 1：rowByIndex（从 hierarchy + mapping_recommendations 聚合）
    const rowByIndex = new Map<
      number,
      { row_index: number; client_account_code: string | null; client_account_name: string | null; level: number | null; is_leaf: boolean | null; is_summary: boolean | null }
    >()
    for (const h of analyze.hierarchy || []) {
      rowByIndex.set(h.row_index, {
        row_index: h.row_index,
        client_account_code: h.client_account_code ?? null,
        client_account_name: h.client_account_name ?? null,
        level: h.level ?? null,
        is_leaf: h.is_leaf ?? null,
        is_summary: h.is_summary ?? null,
      })
    }
    for (const r of analyze.mapping_recommendations || []) {
      const cur = rowByIndex.get(r.row_index)
      if (!cur) {
        rowByIndex.set(r.row_index, {
          row_index: r.row_index,
          client_account_code: r.client_account_code ?? null,
          client_account_name: r.client_account_name ?? null,
          level: null,
          is_leaf: r.is_leaf ?? null,
          is_summary: r.is_summary ?? null,
        })
      } else {
        // mapping_recommendations 提供更精确的 code/name
        if (!cur.client_account_code && r.client_account_code) cur.client_account_code = r.client_account_code
        if (!cur.client_account_name && r.client_account_name) cur.client_account_name = r.client_account_name
      }
    }

    // 预索引 2：bindingsByNodeKey
    const bindingsByNodeKey = new Map<string, RowNodeBinding[]>()
    for (const b of bindings) {
      const arr = bindingsByNodeKey.get(b.node_key) || []
      arr.push(b)
      bindingsByNodeKey.set(b.node_key, arr)
    }

    // 推荐候选快速索引（按 node_key 的 mapping_recommendation.candidates）
    // 后端未必保证所有 row 都有 rec；但 representative_row_index 必有 rec
    const recByRowIndex = new Map<number, any>()
    for (const r of analyze.mapping_recommendations || []) {
      recByRowIndex.set(r.row_index, r)
    }

    // 警告索引：warnings → row_indexes
    const warningRows = new Set<number>()
    for (const w of warnings?.value || []) {
      if (w.row_index !== null && w.row_index !== undefined) warningRows.add(w.row_index)
    }

    const out: UniqueNodeReviewRow[] = []
    for (const n of nodes) {
      const repRow = rowByIndex.get(n.representative_row_index)
      const repRec = recByRowIndex.get(n.representative_row_index)
      const nodeBindings = bindingsByNodeKey.get(n.node_key) || []

      // warnings 聚合：任一绑定行有 warning 即认为该节点有警告
      const nodeWarningMessages: string[] = []
      for (const w of warnings?.value || []) {
        if (w.row_index === null || w.row_index === undefined) continue
        const boundIndexes = n.source_row_indexes || nodeBindings.map((b) => b.row_index)
        if (boundIndexes.includes(w.row_index)) {
          nodeWarningMessages.push(`${w.code}: ${w.message}`)
        }
      }

      const userSelected = selectedByNodeKey.value[n.node_key]
      const isIgnored = !!ignoredNodeKeys.value[n.node_key]
      const explicitOverride = !!explicitOverrideNodeKeys.value[n.node_key]

      out.push({
        node_key: n.node_key,
        representative_row_index: n.representative_row_index,
        source_row_count: n.source_row_count ?? nodeBindings.length ?? 0,
        source_row_indexes: n.source_row_indexes ?? nodeBindings.map((b) => b.row_index),
        account_code: n.account_code ?? repRow?.client_account_code ?? repRec?.client_account_code ?? null,
        account_name: n.account_name ?? repRow?.client_account_name ?? repRec?.client_account_name ?? null,
        full_path: n.full_path ?? '',
        parent_node_key: n.parent_node_key ?? null,
        node_type: (n.node_type as any) ?? repRec?.node_type ?? 'account',
        mapping_role: n.mapping_role ?? repRec?.mapping_role ?? 'unresolved',
        requires_confirmation: !!n.requires_confirmation,
        resolved_standard_account_id:
          n.resolved_standard_account_id ?? repRec?.resolved_standard_account_id ?? null,
        resolved_standard_account_code: repRec?.resolved_standard_account_code ?? null,
        resolved_standard_account_name: repRec?.resolved_standard_account_name ?? null,
        suggested_standard_account_id:
          n.suggested_standard_account_id ?? repRec?.suggested_standard_account_id ?? null,
        suggested_standard_account_code: repRec?.suggested_standard_account_code ?? null,
        suggested_standard_account_name: repRec?.suggested_standard_account_name ?? null,
        candidates: n.candidates ?? repRec?.candidates ?? [],
        selected_candidate: userSelected ?? null,
        explicit_override: explicitOverride,
        is_ignored: isIgnored,
        warnings: nodeWarningMessages,
        resolution_source: repRec?.resolution_source ?? null,
        resolution_reason: repRec?.resolution_reason ?? null,
        inheritance_evidence: repRec?.inheritance_evidence ?? [],
      })
    }
    return out
  })

  // 暴露 nodeByKey / bindingsByNodeKey / rowByIndex 给组件用
  const nodeByKey = computed(() => {
    const m = new Map<string, UniqueNodeReviewRow>()
    for (const n of uniqueNodeRows.value) m.set(n.node_key, n)
    return m
  })

  const rowBindingsByNodeKey = computed(() => {
    const m = new Map<string, RowNodeBinding[]>()
    const bindings = analyzeResult.value?.row_node_bindings || []
    for (const b of bindings) {
      const arr = m.get(b.node_key) || []
      arr.push(b)
      m.set(b.node_key, arr)
    }
    return m
  })

  const rowByIndex = computed(() => {
    const m = new Map<
      number,
      { row_index: number; client_account_code: string | null; client_account_name: string | null; level: number | null; is_leaf: boolean | null; is_summary: boolean | null }
    >()
    const analyze = analyzeResult.value
    if (!analyze) return m
    for (const h of analyze.hierarchy || []) {
      m.set(h.row_index, {
        row_index: h.row_index,
        client_account_code: h.client_account_code ?? null,
        client_account_name: h.client_account_name ?? null,
        level: h.level ?? null,
        is_leaf: h.is_leaf ?? null,
        is_summary: h.is_summary ?? null,
      })
    }
    for (const r of analyze.mapping_recommendations || []) {
      const cur = m.get(r.row_index)
      if (!cur) {
        m.set(r.row_index, {
          row_index: r.row_index,
          client_account_code: r.client_account_code ?? null,
          client_account_name: r.client_account_name ?? null,
          level: null,
          is_leaf: r.is_leaf ?? null,
          is_summary: r.is_summary ?? null,
        })
      } else {
        if (!cur.client_account_code && r.client_account_code) cur.client_account_code = r.client_account_code
        if (!cur.client_account_name && r.client_account_name) cur.client_account_name = r.client_account_name
      }
    }
    return m
  })

  // ===== 角色与判定 =====

  function effectiveNodeMappingRole(node: UniqueNodeReviewRow): string {
    if (node.is_ignored || ignoredNodeKeys.value[node.node_key]) return 'ignored'
    const role = node.mapping_role || 'unresolved'
    if (role === 'structural_summary' || role === 'ignored') return role
    if (role === 'inherited' && explicitOverrideNodeKeys.value[node.node_key]) {
      return 'explicit_override'
    }
    if (role === 'unresolved' && selectedByNodeKey.value[node.node_key]) {
      return 'anchor'
    }
    return role
  }

  function nodeRequiresMapping(node: UniqueNodeReviewRow): boolean {
    if (node.is_ignored || ignoredNodeKeys.value[node.node_key]) return false
    if (node.node_type === 'summary' || node.mapping_role === 'structural_summary') return false
    const role = effectiveNodeMappingRole(node)
    // anchor / breakpoint / unresolved / explicit_override（开启但未选）
    if (role === 'inherited' || role === 'structural_summary' || role === 'ignored') return false
    if (role === 'unresolved') return true
    if (role === 'explicit_override') {
      if (explicitOverrideNodeKeys.value[node.node_key]) return true
      return node.requires_confirmation
    }
    // anchor / breakpoint
    return node.requires_confirmation
  }

  function nodeShouldSubmitMapping(node: UniqueNodeReviewRow): boolean {
    if (node.is_ignored || ignoredNodeKeys.value[node.node_key]) return false
    if (node.node_type === 'summary' || node.mapping_role === 'structural_summary') return false
    const role = effectiveNodeMappingRole(node)
    if (role !== 'anchor' && role !== 'breakpoint' && role !== 'explicit_override') return false
    if (role === 'explicit_override' && !selectedByNodeKey.value[node.node_key]) return false
    return true
  }

  function nodeDisplayStatus(node: UniqueNodeReviewRow): NodeDisplayInfo {
    if (node.is_ignored || ignoredNodeKeys.value[node.node_key]) {
      if (node.source_row_count > 0) {
        return { status: 'all_bound_rows_ignored', label: '绑定行已全部忽略', type: 'info' }
      }
      return { status: 'ignored', label: '已忽略', type: 'info' }
    }
    const role = effectiveNodeMappingRole(node)
    const hasSelected = !!selectedByNodeKey.value[node.node_key]
    if (role === 'structural_summary' || node.node_type === 'summary') {
      return { status: 'structural', label: '结构汇总', type: 'info' }
    }
    if (role === 'inherited') {
      if (hasSelected) return { status: 'overridden', label: '显式覆盖已确认', type: 'primary' }
      return { status: 'inherited', label: '自动继承', type: 'success' }
    }
    if (role === 'explicit_override') {
      if (hasSelected) return { status: 'explicit_override_confirmed', label: '显式覆盖已确认', type: 'primary' }
      return { status: 'explicit_override_pending', label: '显式覆盖待选择', type: 'warning' }
    }
    if (role === 'anchor' || role === 'breakpoint') {
      if (hasSelected) {
        return {
          status: 'mapped',
          label: role === 'breakpoint' ? '继承中断点已确认' : '映射锚点已确认',
          type: role === 'breakpoint' ? 'warning' : 'success',
        }
      }
      // 自动确认 unique_safe + 有 resolved
      if (
        node.resolution_source?.includes('unique_safe') ||
        node.resolution_source === 'auto_unique_safe'
      ) {
        return { status: 'auto_confirmed', label: '自动确认', type: 'success' }
      }
      return {
        status: 'pending_confirmation',
        label: `待确认 · ${role === 'breakpoint' ? '继承中断点' : '映射锚点'}`,
        type: 'warning',
      }
    }
    if (role === 'unresolved') {
      return { status: 'unresolved', label: '未解决', type: 'danger' }
    }
    return { status: 'unresolved', label: '未解决', type: 'danger' }
  }

  function nodeWarnings(node: UniqueNodeReviewRow): string[] {
    return node.warnings || []
  }

  function warningRowIndexesForNode(node: UniqueNodeReviewRow): number[] {
    const idxs: number[] = []
    const ws = warnings?.value || []
    const boundSet = new Set(node.source_row_indexes)
    for (const w of ws) {
      if (w.row_index !== null && w.row_index !== undefined && boundSet.has(w.row_index)) {
        idxs.push(w.row_index)
      }
    }
    return idxs
  }

  // ===== 操作 =====

  function selectNodeCandidate(nodeKey: string, candidate: MappingCandidate) {
    selectedByNodeKey.value = { ...selectedByNodeKey.value, [nodeKey]: candidate }
    // 选择后，若 warnings 已确认则重置
    if (warningsConfirmed?.value) warningsConfirmed.value = false
  }

  function clearNodeCandidate(nodeKey: string) {
    const next = { ...selectedByNodeKey.value }
    delete next[nodeKey]
    selectedByNodeKey.value = next
    if (warningsConfirmed?.value) warningsConfirmed.value = false
  }

  function setNodeOverride(nodeKey: string) {
    explicitOverrideNodeKeys.value = { ...explicitOverrideNodeKeys.value, [nodeKey]: true }
    // override 开启时清掉旧选择（强制重新选）
    clearNodeCandidate(nodeKey)
  }

  function restoreNodeInheritance(nodeKey: string) {
    const nextOverride = { ...explicitOverrideNodeKeys.value }
    delete nextOverride[nodeKey]
    explicitOverrideNodeKeys.value = nextOverride
    clearNodeCandidate(nodeKey)
  }

  function setNodeIgnored(nodeKey: string, ignored: boolean) {
    const next = { ...ignoredNodeKeys.value }
    if (ignored) next[nodeKey] = true
    else delete next[nodeKey]
    ignoredNodeKeys.value = next
  }

  function toggleNodeExpanded(nodeKey: string) {
    const next = { ...expandedNodeKeys.value }
    if (next[nodeKey]) delete next[nodeKey]
    else next[nodeKey] = true
    expandedNodeKeys.value = next
  }

  // ===== 提交构造 =====

  /**
   * 直接从 NodeKey 状态构造 confirmed_node_mappings。
   * 禁止先生成 row mappings 再 Map 折叠。
   */
  function buildConfirmedNodeMappingsFromNodeState(): ConfirmedNodeMapping[] {
    if (!isNodeKeyMode.value) return []
    const out: ConfirmedNodeMapping[] = []
    for (const node of uniqueNodeRows.value) {
      if (!nodeShouldSubmitMapping(node)) continue
      const role = effectiveNodeMappingRole(node)
      let sel = selectedByNodeKey.value[node.node_key] || null
      let selectionSource: 'user_confirmed' | 'auto_confirmed' | 'user_corrected' = 'user_confirmed'

      // anchor / breakpoint 自动 unique_safe 兜底（与 anchorInheritanceMapping 对齐）
      const allowAutoFallback = role === 'anchor' || role === 'breakpoint'
      if (!sel && allowAutoFallback && node.resolved_standard_account_id) {
        sel = {
          standard_account_id: node.resolved_standard_account_id,
          standard_account_code: node.resolved_standard_account_code || '',
          standard_account_name: node.resolved_standard_account_name || '',
          score: 1.0,
          source: node.resolution_source || 'auto',
          reason: node.resolution_reason || '自动确认',
          warning: null,
          auto_confirmable: true,
          compatibility_status: 'compatible',
        }
        selectionSource = 'auto_confirmed'
      }

      if (!sel || !sel.standard_account_id) continue
      out.push({
        node_key: node.node_key,
        representative_row_index: node.representative_row_index,
        standard_account_id: sel.standard_account_id,
        standard_account_code: sel.standard_account_code,
        standard_account_name: sel.standard_account_name,
        mapping_action: role === 'explicit_override' ? 'override' : 'anchor',
        apply_to_descendants: true,
        selection_source: selectionSource,
      })
    }
    return out
  }

  /**
   * 旧行级兼容：当后端无 unique_mapping_nodes 时，从行级选择构造 confirmed_mappings。
   * 委托给 anchorInheritanceMapping 的 buildAnchorOnlyConfirmedMappings。
   */
  function buildLegacyConfirmedMappings(): ConfirmedMapping[] {
    if (isNodeKeyMode.value) return [] // NodeKey 模式不应走这里
    const rows = (analyzeResult.value?.mapping_recommendations || []).map((r: any) => ({
      row_index: r.row_index,
      client_account_code: r.client_account_code,
      client_account_name: r.client_account_name,
      is_leaf: r.is_leaf,
      is_summary: r.is_summary,
      participates_in_entry: r.participates_in_entry,
      rec: r,
      is_ignored: !!ignoredRows.value[r.row_index],
    }))
    const localState = {
      selectedByRow: selectedByRow.value,
      explicitOverrideRows: explicitOverrideRows.value,
      confirmedUnresolvedRows: confirmedUnresolvedRows.value,
      ignoredRows: ignoredRows.value,
    }
    return buildAnchorOnlyConfirmedMappings(rows as any, selectedByRow.value, localState)
  }

  /**
   * 旧行级冲突检测：同 node_key 但用户对不同 row 选了不同的 standard_account_id。
   * 仅在 NodeKey 模式下有意义（绑定行共享 node_key）；兼容模式下 row_index 不重复 node_key 也允许。
   * 一旦发现冲突，必须 canConfirm=false / canExecute=false。
   */
  function detectNodeSelectionConflicts(): NodeSelectionConflict[] {
    if (!isNodeKeyMode.value) {
      // 兼容模式：行级选择冲突
      const rowToNodeKey = new Map<number, string>()
      const analyze = analyzeResult.value
      for (const r of analyze?.mapping_recommendations || []) {
        if (r.node_key) rowToNodeKey.set(r.row_index, r.node_key)
      }
      const byNode = new Map<
        string,
        Array<{ row_index: number; standard_account_id: string; standard_account_code: string; standard_account_name: string; client_account_code: string | null; client_account_name: string | null }>
      >()
      for (const [rowIndex, candidate] of Object.entries(selectedByRow.value)) {
        if (!candidate) continue
        const nodeKey = rowToNodeKey.get(Number(rowIndex))
        if (!nodeKey) continue
        const row = rowByIndex.value.get(Number(rowIndex))
        const rec = (analyze?.mapping_recommendations || []).find((r: any) => r.row_index === Number(rowIndex))
        const arr = byNode.get(nodeKey) || []
        arr.push({
          row_index: Number(rowIndex),
          standard_account_id: candidate.standard_account_id,
          standard_account_code: candidate.standard_account_code,
          standard_account_name: candidate.standard_account_name,
          client_account_code: row?.client_account_code ?? rec?.client_account_code ?? null,
          client_account_name: row?.client_account_name ?? rec?.client_account_name ?? null,
        })
        byNode.set(nodeKey, arr)
      }
      const conflicts: NodeSelectionConflict[] = []
      for (const [nodeKey, selections] of byNode.entries()) {
        const distinct = new Set(selections.map((s) => s.standard_account_id))
        if (distinct.size > 1) {
          const node = nodeByKey.value.get(nodeKey)
          conflicts.push({
            node_key: nodeKey,
            representative_row_index: node?.representative_row_index ?? null,
            bound_row_indexes: selections.map((s) => s.row_index),
            conflicting_selections: selections,
          })
        }
      }
      return conflicts
    }
    // NodeKey 模式：selectedByNodeKey 一对一，不会自冲突，但兼容旧行级状态时仍扫一遍
    const conflicts: NodeSelectionConflict[] = []
    const rowToNodeKey = new Map<number, string>()
    const analyze = analyzeResult.value
    for (const r of analyze?.mapping_recommendations || []) {
      if (r.node_key) rowToNodeKey.set(r.row_index, r.node_key)
    }
    for (const b of analyze?.row_node_bindings || []) {
      if (!rowToNodeKey.has(b.row_index)) rowToNodeKey.set(b.row_index, b.node_key)
    }
    const byNode = new Map<
      string,
      Array<{ row_index: number; standard_account_id: string; standard_account_code: string; standard_account_name: string; client_account_code: string | null; client_account_name: string | null }>
    >()
    for (const [rowIndexStr, candidate] of Object.entries(selectedByRow.value)) {
      if (!candidate) continue
      const rowIndex = Number(rowIndexStr)
      const nodeKey = rowToNodeKey.get(rowIndex)
      if (!nodeKey) continue
      const row = rowByIndex.value.get(rowIndex)
      const rec = (analyze?.mapping_recommendations || []).find((r: any) => r.row_index === rowIndex)
      const arr = byNode.get(nodeKey) || []
      arr.push({
        row_index: rowIndex,
        standard_account_id: candidate.standard_account_id,
        standard_account_code: candidate.standard_account_code,
        standard_account_name: candidate.standard_account_name,
        client_account_code: row?.client_account_code ?? rec?.client_account_code ?? null,
        client_account_name: row?.client_account_name ?? rec?.client_account_name ?? null,
      })
      byNode.set(nodeKey, arr)
    }
    for (const [nodeKey, selections] of byNode.entries()) {
      const distinct = new Set(selections.map((s) => s.standard_account_id))
      if (distinct.size > 1) {
        const node = nodeByKey.value.get(nodeKey)
        conflicts.push({
          node_key: nodeKey,
          representative_row_index: node?.representative_row_index ?? null,
          bound_row_indexes: selections.map((s) => s.row_index),
          conflicting_selections: selections,
        })
      }
    }
    return conflicts
  }

  // ===== 统计 =====

  const blockingErrorCount = computed(() => {
    const analyze = analyzeResult.value
    if (!analyze) return 0
    return (analyze.errors || []).length
  })

  const nodeStats = computed<NodeMappingStats>(() => {
    const rows = uniqueNodeRows.value
    let mapped = 0
    let unmapped = 0
    let warning = 0
    let explicitOverride = 0
    let inherited = 0
    let anchorPending = 0
    let confirmationRequired = 0
    let boundRawRowCount = 0
    for (const node of rows) {
      boundRawRowCount += node.source_row_count
      if (nodeWarnings(node).length > 0) warning += 1
      if (node.requires_confirmation) confirmationRequired += 1
      const role = effectiveNodeMappingRole(node)
      if (role === 'inherited' && !node.selected_candidate) inherited += 1
      if (role === 'explicit_override' && explicitOverrideNodeKeys.value[node.node_key]) {
        explicitOverride += 1
      }
      if (nodeRequiresMapping(node)) {
        if (node.selected_candidate) mapped += 1
        else {
          unmapped += 1
          if (role === 'anchor' || role === 'breakpoint') anchorPending += 1
        }
      } else if (
        (role === 'anchor' || role === 'breakpoint') &&
        !node.selected_candidate &&
        node.resolved_standard_account_id &&
        (node.resolution_source?.includes('unique_safe') || node.resolution_source === 'auto_unique_safe')
      ) {
        // 自动 unique_safe 兜底，计入 mapped
        mapped += 1
      }
    }
    return {
      total_node_count: rows.length,
      confirmation_required_count: confirmationRequired,
      mapped_count: mapped,
      unmapped_count: unmapped,
      warning_count: warning,
      explicit_override_count: explicitOverride,
      inherited_count: inherited,
      anchor_pending_count: anchorPending,
      bound_raw_row_count: boundRawRowCount,
    }
  })

  const totalWarningNodes = computed(() => nodeStats.value.warning_count)

  // ===== 启用判定 =====

  const canConfirm = computed(() => {
    const conflicts = detectNodeSelectionConflicts()
    if (conflicts.length > 0) return false
    if (blockingErrorCount.value > 0) return false
    if (nodeStats.value.unmapped_count > 0) return false
    return true
  })

  const canExecute = computed(() => {
    if (!canConfirm.value) return false
    const warningsList = warnings?.value || []
    if (warningsList.length > 0 && !warningsConfirmed?.value) return false
    return true
  })

  const confirmHint = computed(() => {
    if (detectNodeSelectionConflicts().length > 0) return '存在 NodeKey 冲突，请先解决同节点不同目标的选择'
    if (blockingErrorCount.value > 0) return `还有 ${blockingErrorCount.value} 条错误需要处理`
    if (nodeStats.value.unmapped_count > 0)
      return `还有 ${nodeStats.value.unmapped_count} 个唯一节点未映射到标准科目`
    return ''
  })

  // ===== 标准科目搜索 =====

  async function searchStandardAccounts(nodeKey: string, keyword: string) {
    const q = (keyword || '').trim()
    if (q.length < 1) {
      searchResultsByNodeKey.value = { ...searchResultsByNodeKey.value, [nodeKey]: [] }
      return []
    }
    try {
      const { default: api } = await import('@/api')
      const { data } = await api.get('/standard-accounts', { params: { keyword: q, page_size: 10 } })
      const items = (data?.items || []) as any[]
      searchResultsByNodeKey.value = { ...searchResultsByNodeKey.value, [nodeKey]: items }
      return items
    } catch {
      searchResultsByNodeKey.value = { ...searchResultsByNodeKey.value, [nodeKey]: [] }
      return []
    }
  }

  async function searchStandardAccountsForRow(rowIndex: number, keyword: string) {
    // 兼容模式：搜索结果存到 selectedByRow 之外的 searchResultsByNodeKey（按 row key）
    const key = `row:${rowIndex}`
    return searchStandardAccounts(key, keyword)
  }

  // ===== 重置 =====

  function reset() {
    selectedByNodeKey.value = {}
    explicitOverrideNodeKeys.value = {}
    ignoredNodeKeys.value = {}
    expandedNodeKeys.value = {}
    searchQueriesByNodeKey.value = {}
    searchResultsByNodeKey.value = {}
    selectedByRow.value = {}
    explicitOverrideRows.value = {}
    confirmedUnresolvedRows.value = {}
    ignoredRows.value = {}
  }

  function setAnalyzeResult(_data: StdAnalyzeResponse) {
    // 切换 batch 时清空本地状态，避免污染新数据
    reset()
  }

  // ---- 当 analyze 变化时自动 reset ----
  watch(
    () => analyzeResult.value?.batch_id,
    (newId, oldId) => {
      if (newId && newId !== oldId) reset()
    },
  )

  return {
    isNodeKeyMode,
    uniqueNodeRows,
    nodeByKey,
    rowBindingsByNodeKey,
    rowByIndex,
    selectedByNodeKey,
    explicitOverrideNodeKeys,
    ignoredNodeKeys,
    expandedNodeKeys,
    searchQueriesByNodeKey,
    searchResultsByNodeKey,
    selectedByRow,
    explicitOverrideRows,
    confirmedUnresolvedRows,
    ignoredRows,
    nodeStats,
    effectiveNodeMappingRole,
    nodeRequiresMapping,
    nodeShouldSubmitMapping,
    nodeDisplayStatus,
    nodeWarnings,
    warningRowIndexesForNode,
    selectNodeCandidate,
    clearNodeCandidate,
    setNodeOverride,
    restoreNodeInheritance,
    setNodeIgnored,
    toggleNodeExpanded,
    buildConfirmedNodeMappingsFromNodeState,
    buildLegacyConfirmedMappings,
    detectNodeSelectionConflicts,
    totalWarningNodes,
    blockingErrorCount,
    canConfirm,
    canExecute,
    confirmHint,
    searchStandardAccounts,
    searchStandardAccountsForRow,
    reset,
    setAnalyzeResult,
  }
}