import { describe, expect, it, beforeEach, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import {
  useUniqueNodeMapping,
  type UseUniqueNodeMappingOptions,
} from './useUniqueNodeMapping'
import type {
  StdAnalyzeResponse,
  MappingCandidate,
  UniqueMappingNode,
  RowNodeBinding,
} from '@/types'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

const candidate = (id: string, code: string, name: string): MappingCandidate => ({
  standard_account_id: id,
  standard_account_code: code,
  standard_account_name: name,
  score: 1,
  source: 'user_selected',
  reason: 'test',
  warning: null,
  auto_confirmable: false,
  compatibility_status: 'compatible',
})

/**
 * 构造 1 个唯一节点 + 3 条绑定原始行的最小 fixture
 * （与 205201 主表的 715 节点 / 98k 行的真实结构对齐）
 */
const buildAnalyzeFixture = (overrides: Partial<StdAnalyzeResponse> = {}): StdAnalyzeResponse => ({
  batch_id: 'batch-1',
  status: 'analyzed',
  hierarchy: [
    { row_index: 0, client_account_code: '1001', client_account_name: 'Cash', level: 1, parent_key: null, is_leaf: true, is_summary: false, level_source: 'flat' },
    { row_index: 1, client_account_code: '1001', client_account_name: 'Cash', level: 1, parent_key: null, is_leaf: true, is_summary: false, level_source: 'flat' },
    { row_index: 2, client_account_code: '1001', client_account_name: 'Cash', level: 1, parent_key: null, is_leaf: true, is_summary: false, level_source: 'flat' },
  ],
  mapping_recommendations: [
    { row_index: 0, client_account_code: '1001', client_account_name: 'Cash', is_leaf: true, is_summary: false, participates_in_entry: true, mapping_role: 'anchor', mapping_mode: 'none', requires_confirmation: true, candidates: [candidate('sa-cash', '1001', 'Cash')], node_key: 'uak:v2:cash' },
    { row_index: 1, client_account_code: '1001', client_account_name: 'Cash', is_leaf: true, is_summary: false, participates_in_entry: true, mapping_role: 'anchor', mapping_mode: 'none', requires_confirmation: true, candidates: [candidate('sa-cash', '1001', 'Cash')], node_key: 'uak:v2:cash' },
    { row_index: 2, client_account_code: '1001', client_account_name: 'Cash', is_leaf: true, is_summary: false, participates_in_entry: true, mapping_role: 'anchor', mapping_mode: 'none', requires_confirmation: true, candidates: [candidate('sa-cash', '1001', 'Cash')], node_key: 'uak:v2:cash' },
  ],
  amounts: [],
  errors: [],
  warnings: [],
  mapping_summary: {
    total_nodes: 1,
    structural_summary_count: 0,
    anchor_count: 1,
    inherited_count: 0,
    breakpoint_count: 0,
    explicit_override_count: 0,
    unresolved_count: 0,
    confirmation_required_count: 1,
    participating_leaf_count: 3,
    resolved_participating_leaf_count: 0,
  },
  mapping_strategy: 'anchor_inheritance_v2',
  unique_mapping_nodes: [
    {
      node_key: 'uak:v2:cash',
      representative_row_index: 0,
      source_row_count: 3,
      source_row_indexes: [0, 1, 2],
      account_code: '1001',
      account_name: 'Cash',
      full_path: 'Cash',
      parent_node_key: null,
      node_type: 'account',
      mapping_role: 'anchor',
      requires_confirmation: true,
      resolved_standard_account_id: null,
      suggested_standard_account_id: 'sa-cash',
      candidates: [candidate('sa-cash', '1001', 'Cash')],
    } as UniqueMappingNode,
  ],
  row_node_bindings: [
    { row_index: 0, node_key: 'uak:v2:cash', representative_row_index: 0, is_representative: true },
    { row_index: 1, node_key: 'uak:v2:cash', representative_row_index: 0, is_representative: false },
    { row_index: 2, node_key: 'uak:v2:cash', representative_row_index: 0, is_representative: false },
  ] as RowNodeBinding[],
  ...overrides,
})

function setup(analyze: StdAnalyzeResponse | null) {
  const analyzeResult = ref<StdAnalyzeResponse | null>(analyze)
  const warnings = ref<any[]>((analyze as any)?.warnings || [])
  const warningsConfirmed = ref(false)
  const opts: UseUniqueNodeMappingOptions = {
    analyzeResult,
    warnings,
    warningsConfirmed,
  }
  const m = useUniqueNodeMapping(opts)
  return { m, analyzeResult, warnings, warningsConfirmed }
}

describe('useUniqueNodeMapping - NodeKey 模式数据模型', () => {
  it('后端返回 unique_mapping_nodes 时进入 NodeKey 模式', () => {
    const { m } = setup(buildAnalyzeFixture())
    expect(m.isNodeKeyMode.value).toBe(true)
  })

  it('后端无 unique_mapping_nodes 时退回旧行级模式', () => {
    const fixture = buildAnalyzeFixture()
    delete (fixture as any).unique_mapping_nodes
    delete (fixture as any).row_node_bindings
    const { m } = setup(fixture)
    expect(m.isNodeKeyMode.value).toBe(false)
  })

  it('uniqueNodeRows 长度等于后端唯一节点数（不展开绑定原始行）', () => {
    const { m } = setup(buildAnalyzeFixture())
    expect(m.uniqueNodeRows.value).toHaveLength(1)
  })

  it('3 条重复绑定行只显示 1 个唯一节点，主表不重复', () => {
    const { m } = setup(buildAnalyzeFixture())
    const node = m.uniqueNodeRows.value[0]
    expect(node.source_row_count).toBe(3)
    expect(node.source_row_indexes).toEqual([0, 1, 2])
    expect(m.uniqueNodeRows.value).toHaveLength(1)
  })

  it('nodeByKey 提供 O(1) 节点查找', () => {
    const { m } = setup(buildAnalyzeFixture())
    const map = m.nodeByKey.value
    expect(map.get('uak:v2:cash')).toBeDefined()
    expect(map.get('uak:v2:cash')?.source_row_count).toBe(3)
  })

  it('rowBindingsByNodeKey 按 node_key 分组绑定原始行', () => {
    const { m } = setup(buildAnalyzeFixture())
    const group = m.rowBindingsByNodeKey.value.get('uak:v2:cash')
    expect(group).toBeDefined()
    expect(group).toHaveLength(3)
    expect(group?.find((b) => b.is_representative)?.row_index).toBe(0)
  })

  it('rowByIndex 提供 O(1) 原始行查找', () => {
    const { m } = setup(buildAnalyzeFixture())
    expect(m.rowByIndex.value.get(0)?.client_account_code).toBe('1001')
    expect(m.rowByIndex.value.get(1)?.client_account_code).toBe('1001')
  })
})

describe('useUniqueNodeMapping - NodeKey 本地状态与操作', () => {
  it('selectNodeCandidate 写入 selectedByNodeKey[node_key]', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    expect(m.selectedByNodeKey.value['uak:v2:cash']?.standard_account_id).toBe('sa-cash')
  })

  it('clearNodeCandidate 删除 selectedByNodeKey[node_key]', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    m.clearNodeCandidate('uak:v2:cash')
    expect(m.selectedByNodeKey.value['uak:v2:cash']).toBeUndefined()
  })

  it('setNodeOverride 开启 explicit_override 并清掉旧选择', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    m.setNodeOverride('uak:v2:cash')
    expect(m.explicitOverrideNodeKeys.value['uak:v2:cash']).toBe(true)
    expect(m.selectedByNodeKey.value['uak:v2:cash']).toBeUndefined()
  })

  it('restoreNodeInheritance 清除 override 与选择', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.setNodeOverride('uak:v2:cash')
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    m.restoreNodeInheritance('uak:v2:cash')
    expect(m.explicitOverrideNodeKeys.value['uak:v2:cash']).toBeUndefined()
    expect(m.selectedByNodeKey.value['uak:v2:cash']).toBeUndefined()
  })

  it('NodeKey 模式同一 node_key 只允许 1 个 selected，天然避免同节点不同目标', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-bank', '1002', 'Bank'))
    expect(m.selectedByNodeKey.value['uak:v2:cash']?.standard_account_id).toBe('sa-bank')
    expect(Object.keys(m.selectedByNodeKey.value)).toHaveLength(1)
  })
})

describe('useUniqueNodeMapping - 角色与状态判定', () => {
  it('inherited 节点未 override 时 nodeRequiresMapping=false', () => {
    const fixture = buildAnalyzeFixture()
    fixture.unique_mapping_nodes![0].mapping_role = 'inherited'
    fixture.unique_mapping_nodes![0].requires_confirmation = false
    fixture.unique_mapping_nodes![0].resolved_standard_account_id = 'sa-cash'
    const { m } = setup(fixture)
    const node = m.uniqueNodeRows.value[0]
    expect(m.nodeRequiresMapping(node)).toBe(false)
    expect(m.effectiveNodeMappingRole(node)).toBe('inherited')
  })

  it('inherited 开启 override 但未选择时 nodeRequiresMapping=true', () => {
    const fixture = buildAnalyzeFixture()
    fixture.unique_mapping_nodes![0].mapping_role = 'inherited'
    const { m } = setup(fixture)
    m.setNodeOverride('uak:v2:cash')
    const node = m.uniqueNodeRows.value[0]
    expect(m.nodeRequiresMapping(node)).toBe(true)
    expect(m.effectiveNodeMappingRole(node)).toBe('explicit_override')
  })

  it('inherited override 已选择时 nodeShouldSubmitMapping=true', () => {
    const fixture = buildAnalyzeFixture()
    fixture.unique_mapping_nodes![0].mapping_role = 'inherited'
    const { m } = setup(fixture)
    m.setNodeOverride('uak:v2:cash')
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-bank', '1002', 'Bank'))
    const node = m.uniqueNodeRows.value[0]
    expect(m.nodeShouldSubmitMapping(node)).toBe(true)
  })

  it('summary 节点 nodeRequiresMapping=false 且不可选', () => {
    const fixture = buildAnalyzeFixture()
    fixture.unique_mapping_nodes![0].node_type = 'summary'
    fixture.unique_mapping_nodes![0].mapping_role = 'structural_summary'
    fixture.unique_mapping_nodes![0].requires_confirmation = false
    const { m } = setup(fixture)
    const node = m.uniqueNodeRows.value[0]
    expect(m.nodeRequiresMapping(node)).toBe(false)
    expect(m.nodeDisplayStatus(node).status).toBe('structural')
  })

  it('unresolved 节点选择后转 anchor', () => {
    const fixture = buildAnalyzeFixture()
    fixture.unique_mapping_nodes![0].mapping_role = 'unresolved'
    const { m } = setup(fixture)
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    const node = m.uniqueNodeRows.value[0]
    expect(m.effectiveNodeMappingRole(node)).toBe('anchor')
    expect(m.nodeShouldSubmitMapping(node)).toBe(true)
  })
})

describe('useUniqueNodeMapping - NodeKey 统计', () => {
  it('绑定行不重复计入 mapped/unmapped，按唯一节点统计', () => {
    const { m } = setup(buildAnalyzeFixture())
    // 3 行绑定到 1 个节点，未选择时 unmapped_count 必须为 1（不是 3）
    expect(m.nodeStats.value.total_node_count).toBe(1)
    expect(m.nodeStats.value.bound_raw_row_count).toBe(3)
    expect(m.nodeStats.value.unmapped_count).toBe(1)
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    expect(m.nodeStats.value.mapped_count).toBe(1)
    expect(m.nodeStats.value.unmapped_count).toBe(0)
  })

  it('warning 节点按唯一节点统计（不按绑定行重复计算）', () => {
    const fixture = buildAnalyzeFixture()
    fixture.warnings = [
      { row_index: 0, code: 'amount_mismatch', message: 'diff', category: 'amount' },
      { row_index: 1, code: 'amount_mismatch', message: 'diff', category: 'amount' },
    ]
    const { m } = setup(fixture)
    expect(m.nodeStats.value.warning_count).toBe(1)
    expect(m.totalWarningNodes.value).toBe(1)
  })
})

describe('useUniqueNodeMapping - 提交构造', () => {
  it('buildConfirmedNodeMappingsFromNodeState 直接由 NodeKey 状态生成 1 条 / node', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    const out = m.buildConfirmedNodeMappingsFromNodeState()
    expect(out).toHaveLength(1)
    expect(out[0]).toEqual(
      expect.objectContaining({
        node_key: 'uak:v2:cash',
        representative_row_index: 0,
        standard_account_id: 'sa-cash',
        mapping_action: 'anchor',
        apply_to_descendants: true,
        selection_source: 'user_confirmed',
      }),
    )
  })

  it('3 条重复绑定行只生成 1 条 confirmed_node_mapping（不依赖 Map 折叠）', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    const out = m.buildConfirmedNodeMappingsFromNodeState()
    expect(out).toHaveLength(1)
    expect(out[0].node_key).toBe('uak:v2:cash')
  })

  it('summary 节点不进入 confirmed_node_mappings', () => {
    const fixture = buildAnalyzeFixture()
    fixture.unique_mapping_nodes![0].node_type = 'summary'
    fixture.unique_mapping_nodes![0].mapping_role = 'structural_summary'
    fixture.unique_mapping_nodes![0].requires_confirmation = false
    const { m } = setup(fixture)
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    const out = m.buildConfirmedNodeMappingsFromNodeState()
    expect(out).toHaveLength(0)
  })

  it('explicit_override 已选择生成 mapping_action=override', () => {
    const fixture = buildAnalyzeFixture()
    fixture.unique_mapping_nodes![0].mapping_role = 'inherited'
    const { m } = setup(fixture)
    m.setNodeOverride('uak:v2:cash')
    m.selectNodeCandidate('uak:v2:cash', candidate('sa-bank', '1002', 'Bank'))
    const out = m.buildConfirmedNodeMappingsFromNodeState()
    expect(out[0].mapping_action).toBe('override')
  })
})

describe('useUniqueNodeMapping - 冲突检测（旧行级兼容）', () => {
  it('同 node_key 不同 target 必须被检测为冲突', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectedByRow.value = {
      0: candidate('sa-cash', '1001', 'Cash'),
      1: candidate('sa-bank', '1002', 'Bank'), // 同 node_key 选了不同目标
    }
    const conflicts = m.detectNodeSelectionConflicts()
    expect(conflicts).toHaveLength(1)
    expect(conflicts[0].node_key).toBe('uak:v2:cash')
    expect(conflicts[0].conflicting_selections).toHaveLength(2)
  })

  it('同 node_key 同 target 不算冲突', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectedByRow.value = {
      0: candidate('sa-cash', '1001', 'Cash'),
      1: candidate('sa-cash', '1001', 'Cash'),
    }
    const conflicts = m.detectNodeSelectionConflicts()
    expect(conflicts).toHaveLength(0)
  })

  it('存在冲突时 canConfirm=false', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectedByRow.value = {
      0: candidate('sa-cash', '1001', 'Cash'),
      1: candidate('sa-bank', '1002', 'Bank'),
    }
    expect(m.canConfirm.value).toBe(false)
  })

  it('存在冲突时 canExecute=false', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectedByRow.value = {
      0: candidate('sa-cash', '1001', 'Cash'),
      1: candidate('sa-bank', '1002', 'Bank'),
    }
    expect(m.canExecute.value).toBe(false)
  })

  it('同 node_key 不同 target 不静默保留第一条（必须阻止）', () => {
    const { m } = setup(buildAnalyzeFixture())
    m.selectedByRow.value = {
      0: candidate('sa-cash', '1001', 'Cash'),
      1: candidate('sa-bank', '1002', 'Bank'),
    }
    const conflicts = m.detectNodeSelectionConflicts()
    expect(conflicts).toHaveLength(1)
    expect(conflicts[0].conflicting_selections.map((s) => s.row_index).sort()).toEqual([0, 1])
  })
})

describe('useUniqueNodeMapping - 性能（O(unique_nodes + row_bindings)）', () => {
  it('715 节点 + 98k 绑定行初始化 < 2 秒（不构建 O(nodes × rows) 的反向索引）', () => {
    // 构造 715 节点 + 每节点 ~137 绑定行（715 × 137 ≈ 98,000）
    const nodeCount = 715
    const bindingsPerNode = 137
    const uniqueNodes: UniqueMappingNode[] = []
    const rowNodeBindings: RowNodeBinding[] = []
    for (let n = 0; n < nodeCount; n++) {
      const baseRow = n * bindingsPerNode
      const indexes: number[] = []
      for (let b = 0; b < bindingsPerNode; b++) {
        const idx = baseRow + b
        indexes.push(idx)
        rowNodeBindings.push({ row_index: idx, node_key: `uak:v2:n${n}`, representative_row_index: baseRow, is_representative: b === 0 })
      }
      uniqueNodes.push({
        node_key: `uak:v2:n${n}`,
        representative_row_index: baseRow,
        source_row_count: bindingsPerNode,
        source_row_indexes: indexes,
        account_code: `1${String(n).padStart(4, '0')}`,
        account_name: `Node ${n}`,
        full_path: `Node ${n}`,
        parent_node_key: null,
        node_type: 'account',
        mapping_role: 'anchor',
        requires_confirmation: true,
        resolved_standard_account_id: null,
        suggested_standard_account_id: `sa-${n}`,
        candidates: [candidate(`sa-${n}`, `1${String(n).padStart(4, '0')}`, `Node ${n}`)],
      })
    }
    const fixture = buildAnalyzeFixture()
    fixture.unique_mapping_nodes = uniqueNodes
    fixture.row_node_bindings = rowNodeBindings

    const t0 = performance.now()
    const { m } = setup(fixture)
    // 触发 uniqueNodeRows computed
    const rows = m.uniqueNodeRows.value
    const t1 = performance.now()
    expect(rows).toHaveLength(nodeCount)
    // 总绑定原始行数 ≈ 98,055
    expect(m.nodeStats.value.bound_raw_row_count).toBe(nodeCount * bindingsPerNode)
    // 100ms 内必须完成（远小于 2s 目标）
    expect(t1 - t0).toBeLessThan(2000)
  })
})
