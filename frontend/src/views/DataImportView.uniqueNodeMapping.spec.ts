import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import DataImportView from './DataImportView.vue'
import api from '@/api'
import type { MappingCandidate, StdAnalyzeResponse } from '@/types'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('element-plus', async () => {
  const actual = await vi.importActual<typeof import('element-plus')>('element-plus')
  return {
    ...actual,
    ElMessage: {
      warning: vi.fn(),
      success: vi.fn(),
      error: vi.fn(),
      info: vi.fn(),
    },
  }
})

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

const analyzeFixture = (): StdAnalyzeResponse => ({
  batch_id: 'batch-node',
  status: 'analyzed',
  hierarchy: [
    { row_index: 0, client_account_code: '1001', client_account_name: 'Cash', level: 1, parent_key: null, is_leaf: true, is_summary: false, level_source: 'flat' },
    { row_index: 1, client_account_code: '1001', client_account_name: 'Cash', level: 1, parent_key: null, is_leaf: true, is_summary: false, level_source: 'flat' },
    { row_index: 2, client_account_code: '1001', client_account_name: 'Cash', level: 1, parent_key: null, is_leaf: true, is_summary: false, level_source: 'flat' },
  ],
  mapping_recommendations: [
    {
      row_index: 0,
      client_account_code: '1001',
      client_account_name: 'Cash',
      is_leaf: true,
      is_summary: false,
      participates_in_entry: true,
      mapping_role: 'anchor',
      mapping_mode: 'none',
      requires_confirmation: true,
      candidates: [candidate('sa-cash', '1001', 'Cash')],
      node_key: 'uak:v2:cash',
      node_source_row_indexes: [0, 1, 2],
      node_representative_row_index: 0,
      node_duplicate_binding: false,
      mapping_editable: true,
      deprecated: false,
    },
    {
      row_index: 1,
      client_account_code: '1001',
      client_account_name: 'Cash',
      is_leaf: true,
      is_summary: false,
      participates_in_entry: true,
      mapping_role: 'anchor',
      mapping_mode: 'none',
      requires_confirmation: true,
      candidates: [candidate('sa-cash', '1001', 'Cash')],
      node_key: 'uak:v2:cash',
      node_source_row_indexes: [0, 1, 2],
      node_representative_row_index: 0,
      node_duplicate_binding: true,
      mapping_editable: false,
      deprecated: true,
    },
    {
      row_index: 2,
      client_account_code: '1001',
      client_account_name: 'Cash',
      is_leaf: true,
      is_summary: false,
      participates_in_entry: true,
      mapping_role: 'anchor',
      mapping_mode: 'none',
      requires_confirmation: true,
      candidates: [candidate('sa-cash', '1001', 'Cash')],
      node_key: 'uak:v2:cash',
      node_source_row_indexes: [0, 1, 2],
      node_representative_row_index: 0,
      node_duplicate_binding: true,
      mapping_editable: false,
      deprecated: true,
    },
  ],
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
    },
  ],
  row_node_bindings: [
    { row_index: 0, node_key: 'uak:v2:cash', representative_row_index: 0, is_representative: true },
    { row_index: 1, node_key: 'uak:v2:cash', representative_row_index: 0, is_representative: false },
    { row_index: 2, node_key: 'uak:v2:cash', representative_row_index: 0, is_representative: false },
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
})

function mountView() {
  return mount(DataImportView, {
    global: {
      stubs: {
        RouterLink: true,
        PageHeader: true,
        ActionCard: true,
        StatsCard: true,
        'el-upload': true,
        'el-button': { template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>', props: ['disabled'] },
        'el-icon': { template: '<i><slot /></i>' },
        'el-progress': true,
        'el-table': { template: '<div><slot /></div>', props: ['data'] },
        'el-table-column': { template: '<div><slot name="default" :row="{}" /></div>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-popover': { template: '<div><slot name="reference" /><slot /></div>' },
        'el-input': true,
        'el-checkbox': { template: '<label><input type="checkbox" @change="$emit(\'update:modelValue\', true)" /><slot /></label>' },
        transition: false,
      },
    },
  })
}

describe('DataImportView unique node mapping payload', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset()
    vi.mocked(api.get).mockReset()
  })

  it('submits one confirmed_node_mapping for duplicate bound rows', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        batch_id: 'batch-node',
        status: 'executed',
        entry_count: 3,
        raw_row_count: 3,
        mapping_saved_count: 1,
        mapping_saved: [],
      },
    })

    const wrapper = mountView()
    const vm = wrapper.vm as any
    vm.__setStdAnalyzeForTest(analyzeFixture())
    // 关键：必须在 composable watch(batch_id).reset() 跑完后再 selectCandidate
    await wrapper.vm.$nextTick()
    vm.__anchorInheritanceForTest.selectCandidate(0, candidate('sa-cash', '1001', 'Cash'))
    await wrapper.vm.$nextTick()

    expect(vm.__anchorInheritanceForTest.confirmedMappings()).toHaveLength(1)
    expect(vm.__anchorInheritanceForTest.confirmedNodeMappings()).toEqual([
      expect.objectContaining({
        node_key: 'uak:v2:cash',
        representative_row_index: 0,
        standard_account_id: 'sa-cash',
      }),
    ])

    await vm.__anchorInheritanceForTest.execute()

    expect(api.post).toHaveBeenCalledWith(
      '/standard-trial-balance-imports/batch-node/execute',
      expect.objectContaining({
        confirmed_mappings: [],
        confirmed_node_mappings: [
          expect.objectContaining({
            node_key: 'uak:v2:cash',
            representative_row_index: 0,
            standard_account_id: 'sa-cash',
          }),
        ],
      }),
    )
  })

  it('NodeKey 模式下主表只展示唯一节点，绑定原始行不进入主表', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as any
    vm.__setStdAnalyzeForTest(analyzeFixture())
    await wrapper.vm.$nextTick()
    const node = vm.__anchorInheritanceForTest.__nodeKey
    expect(node.isNodeKeyMode()).toBe(true)
    expect(node.uniqueNodeRows()).toHaveLength(1)
    expect(node.uniqueNodeRows()[0].source_row_count).toBe(3)
    expect(node.uniqueNodeRows()[0].source_row_indexes).toEqual([0, 1, 2])
  })

  it('NodeKey 模式 selectedByNodeKey 选择后未映射节点数减 1；清除后加 1', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as any
    vm.__setStdAnalyzeForTest(analyzeFixture())
    await wrapper.vm.$nextTick()
    const node = vm.__anchorInheritanceForTest.__nodeKey
    const beforeUnmapped = node.nodeStats().unmapped_count
    node.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    await wrapper.vm.$nextTick()
    expect(node.nodeStats().unmapped_count).toBe(beforeUnmapped - 1)
    expect(node.nodeStats().mapped_count).toBe(1)
    node.clearNodeCandidate('uak:v2:cash')
    await wrapper.vm.$nextTick()
    expect(node.nodeStats().unmapped_count).toBe(beforeUnmapped)
  })

  it('setNodeOverride 开启 override 未选择时阻止，selectNodeCandidate 后才能提交', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as any
    const inheritedFixture = analyzeFixture()
    inheritedFixture.unique_mapping_nodes![0].mapping_role = 'inherited'
    inheritedFixture.unique_mapping_nodes![0].requires_confirmation = false
    inheritedFixture.unique_mapping_nodes![0].resolved_standard_account_id = 'sa-cash'
    vm.__setStdAnalyzeForTest(inheritedFixture)
    await wrapper.vm.$nextTick()
    const node = vm.__anchorInheritanceForTest.__nodeKey
    node.setNodeOverride('uak:v2:cash')
    await wrapper.vm.$nextTick()
    // override 开启但未选择：buildConfirmedNodeMappingsFromNodeState 不应包含 override
    const before = node.buildConfirmedNodeMappings()
    expect(before).toHaveLength(0)
    // 选择后再生成
    node.selectNodeCandidate('uak:v2:cash', candidate('sa-bank', '1002', 'Bank'))
    await wrapper.vm.$nextTick()
    const after = node.buildConfirmedNodeMappings()
    expect(after).toHaveLength(1)
    expect(after[0].mapping_action).toBe('override')
  })

  it('restoreNodeInheritance 恢复 inherited 状态', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as any
    const inheritedFixture = analyzeFixture()
    inheritedFixture.unique_mapping_nodes![0].mapping_role = 'inherited'
    inheritedFixture.unique_mapping_nodes![0].resolved_standard_account_id = 'sa-cash'
    vm.__setStdAnalyzeForTest(inheritedFixture)
    await wrapper.vm.$nextTick()
    const node = vm.__anchorInheritanceForTest.__nodeKey
    node.setNodeOverride('uak:v2:cash')
    node.selectNodeCandidate('uak:v2:cash', candidate('sa-bank', '1002', 'Bank'))
    await wrapper.vm.$nextTick()
    expect(node.effectiveNodeMappingRole('uak:v2:cash')).toBe('explicit_override')
    node.restoreNodeInheritance('uak:v2:cash')
    await wrapper.vm.$nextTick()
    expect(node.effectiveNodeMappingRole('uak:v2:cash')).toBe('inherited')
  })

  it('breakpoint 未确认时阻止，确认后可提交', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as any
    const fixture = analyzeFixture()
    fixture.unique_mapping_nodes![0].mapping_role = 'breakpoint'
    fixture.unique_mapping_nodes![0].requires_confirmation = true
    vm.__setStdAnalyzeForTest(fixture)
    await wrapper.vm.$nextTick()
    const node = vm.__anchorInheritanceForTest.__nodeKey
    expect(node.nodeRequiresMapping('uak:v2:cash')).toBe(true)
    expect(node.buildConfirmedNodeMappings()).toHaveLength(0)
    node.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    await wrapper.vm.$nextTick()
    const confirmed = node.buildConfirmedNodeMappings()
    expect(confirmed).toHaveLength(1)
  })

  it('summary 节点不可选，不进入提交', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as any
    const fixture = analyzeFixture()
    fixture.unique_mapping_nodes![0].node_type = 'summary'
    fixture.unique_mapping_nodes![0].mapping_role = 'structural_summary'
    fixture.unique_mapping_nodes![0].requires_confirmation = false
    vm.__setStdAnalyzeForTest(fixture)
    await wrapper.vm.$nextTick()
    const node = vm.__anchorInheritanceForTest.__nodeKey
    expect(node.nodeRequiresMapping('uak:v2:cash')).toBe(false)
    expect(node.buildConfirmedNodeMappings()).toHaveLength(0)
  })

  it('请求中 confirmed_mappings 为空（NodeKey 模式）', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        batch_id: 'batch-node',
        status: 'executed',
        entry_count: 3,
        raw_row_count: 3,
        mapping_saved_count: 1,
        mapping_saved: [],
      },
    })
    const wrapper = mountView()
    const vm = wrapper.vm as any
    vm.__setStdAnalyzeForTest(analyzeFixture())
    await wrapper.vm.$nextTick()
    vm.__anchorInheritanceForTest.__nodeKey.selectNodeCandidate('uak:v2:cash', candidate('sa-cash', '1001', 'Cash'))
    await wrapper.vm.$nextTick()
    await vm.__anchorInheritanceForTest.execute()
    const call = vi.mocked(api.post).mock.calls[0]
    const body = call[1] as any
    expect(body.confirmed_mappings).toEqual([])
    expect(body.confirmed_node_mappings).toHaveLength(1)
  })

  it('旧后端无 unique_mapping_nodes 时退回行级模式', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        batch_id: 'batch-legacy',
        status: 'executed',
        entry_count: 1,
        raw_row_count: 1,
        mapping_saved_count: 1,
        mapping_saved: [],
      },
    })
    const wrapper = mountView()
    const vm = wrapper.vm as any
    const legacy = analyzeFixture()
    delete (legacy as any).unique_mapping_nodes
    delete (legacy as any).row_node_bindings
    vm.__setStdAnalyzeForTest(legacy)
    await wrapper.vm.$nextTick()
    const node = vm.__anchorInheritanceForTest.__nodeKey
    expect(node.isNodeKeyMode()).toBe(false)
    // 旧行级选择 + 执行：仍走 confirmed_mappings 路径
    vm.__anchorInheritanceForTest.selectCandidate(0, candidate('sa-cash', '1001', 'Cash'))
    await wrapper.vm.$nextTick()
    await vm.__anchorInheritanceForTest.execute()
    const call = vi.mocked(api.post).mock.calls[0]
    const body = call[1] as any
    expect(body.confirmed_mappings.length).toBeGreaterThanOrEqual(1)
    expect(body.confirmed_node_mappings).toEqual([])
  })
})
