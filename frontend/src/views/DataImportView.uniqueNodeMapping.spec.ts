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
})
