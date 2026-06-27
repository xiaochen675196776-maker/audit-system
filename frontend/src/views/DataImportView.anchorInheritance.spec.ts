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
  reason: 'test user selection',
  warning: null,
  standard_balance_direction: 'debit',
  auto_confirmable: false,
  compatibility_status: 'compatible',
})

const analyzeFixture = (): StdAnalyzeResponse => ({
  batch_id: 'batch-093',
  status: 'analyzed',
  hierarchy: [
    { row_index: 0, client_account_code: '1002', client_account_name: 'bank', level: 1, parent_key: null, is_leaf: false, is_summary: false, level_source: 'code' },
    { row_index: 1, client_account_code: '100201', client_account_name: 'bank detail', level: 2, parent_key: '1002', is_leaf: true, is_summary: false, level_source: 'code' },
    { row_index: 2, client_account_code: '1122', client_account_name: 'ar', level: 1, parent_key: null, is_leaf: true, is_summary: false, level_source: 'code' },
    { row_index: 3, client_account_code: 'SUM', client_account_name: 'summary', level: 1, parent_key: null, is_leaf: false, is_summary: true, level_source: 'code' },
    { row_index: 4, client_account_code: '6602', client_account_name: 'fee warning', level: 1, parent_key: null, is_leaf: true, is_summary: false, level_source: 'code' },
  ],
  mapping_recommendations: [
    {
      row_index: 0,
      client_account_code: '1002',
      client_account_name: 'bank',
      is_leaf: false,
      is_summary: false,
      participates_in_entry: false,
      mapping_role: 'anchor',
      mapping_mode: 'direct_auto',
      requires_confirmation: false,
      resolved_standard_account_id: 'sa-bank',
      resolved_standard_account_code: '1002',
      resolved_standard_account_name: 'bank',
      candidates: [candidate('sa-bank', '1002', 'bank')],
      auto_confirm_status: 'unique_safe',
    },
    {
      row_index: 1,
      client_account_code: '100201',
      client_account_name: 'bank detail',
      is_leaf: true,
      is_summary: false,
      participates_in_entry: true,
      mapping_role: 'inherited',
      mapping_mode: 'inherited_ancestor',
      requires_confirmation: false,
      resolved_standard_account_id: 'sa-bank',
      resolved_standard_account_code: '1002',
      resolved_standard_account_name: 'bank',
      candidates: [candidate('sa-other-bank', '100201', 'other bank')],
    },
    {
      row_index: 2,
      client_account_code: '1122',
      client_account_name: 'ar',
      is_leaf: true,
      is_summary: false,
      participates_in_entry: true,
      mapping_role: 'unresolved',
      mapping_mode: 'none',
      requires_confirmation: true,
      candidates: [candidate('sa-ar', '1122', 'ar')],
    },
    {
      row_index: 3,
      client_account_code: 'SUM',
      client_account_name: 'summary',
      is_leaf: false,
      is_summary: true,
      participates_in_entry: false,
      mapping_role: 'structural_summary',
      mapping_mode: 'none',
      requires_confirmation: false,
      candidates: [],
    },
    {
      row_index: 4,
      client_account_code: '6602',
      client_account_name: 'fee warning',
      is_leaf: true,
      is_summary: false,
      participates_in_entry: true,
      mapping_role: 'unresolved',
      mapping_mode: 'none',
      requires_confirmation: true,
      candidates: [candidate('sa-fee', '6602', 'fee')],
    },
  ],
  amounts: [],
  errors: [],
  warnings: [{ row_index: 4, code: 'W', message: 'warning', category: 'other' }],
  mapping_summary: {
    total_nodes: 5,
    structural_summary_count: 1,
    anchor_count: 1,
    inherited_count: 1,
    breakpoint_count: 0,
    explicit_override_count: 0,
    unresolved_count: 2,
    confirmation_required_count: 2,
    participating_leaf_count: 3,
    resolved_participating_leaf_count: 1,
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

describe('DataImportView anchor inheritance real component state', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset()
    vi.mocked(api.get).mockReset()
  })

  it('turns selected unresolved rows into submittable anchors and gates execute by dynamic unresolved count', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as any
    vm.__setStdAnalyzeForTest(analyzeFixture())

    expect(vm.__anchorInheritanceForTest.dynamicUnresolvedCount.value).toBe(2)
    expect(vm.__anchorInheritanceForTest.canExecute.value).toBe(false)

    vm.__anchorInheritanceForTest.selectCandidate(2, candidate('sa-ar', '1122', 'ar'))
    await wrapper.vm.$nextTick()

    expect(vm.__anchorInheritanceForTest.dynamicUnresolvedCount.value).toBe(1)
    expect(vm.__anchorInheritanceForTest.confirmedMappings()).toContainEqual(
      expect.objectContaining({ row_index: 2, mapping_action: 'anchor', selection_source: 'user_confirmed' }),
    )

    vm.__anchorInheritanceForTest.selectCandidate(4, candidate('sa-fee', '6602', 'fee'))
    vm.__anchorInheritanceForTest.setWarningsConfirmed(true)
    await wrapper.vm.$nextTick()

    expect(vm.__anchorInheritanceForTest.dynamicUnresolvedCount.value).toBe(0)
    expect(vm.__anchorInheritanceForTest.canExecute.value).toBe(true)
  })

  it('submits inherited standalone mapping as override and restore inheritance removes it', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as any
    vm.__setStdAnalyzeForTest(analyzeFixture())

    vm.__anchorInheritanceForTest.setOverride(1)
    vm.__anchorInheritanceForTest.selectCandidate(1, candidate('sa-other-bank', '100201', 'other bank'))
    await wrapper.vm.$nextTick()

    expect(vm.__anchorInheritanceForTest.effectiveRole(1)).toBe('explicit_override')
    expect(vm.__anchorInheritanceForTest.confirmedMappings()).toContainEqual(
      expect.objectContaining({ row_index: 1, mapping_action: 'override', apply_to_descendants: true }),
    )

    vm.__anchorInheritanceForTest.restoreInheritance(1)
    await wrapper.vm.$nextTick()

    expect(vm.__anchorInheritanceForTest.effectiveRole(1)).toBe('inherited')
    expect(vm.__anchorInheritanceForTest.confirmedMappings()).not.toContainEqual(
      expect.objectContaining({ row_index: 1 }),
    )
  })

  it('keeps structural rows immutable and keeps warning confirmation separate from unresolved selection', async () => {
    const wrapper = mountView()
    const vm = wrapper.vm as any
    vm.__setStdAnalyzeForTest(analyzeFixture())

    expect(vm.__anchorInheritanceForTest.canSelect(3)).toBe(false)
    vm.__anchorInheritanceForTest.selectCandidate(2, candidate('sa-ar', '1122', 'ar'))
    vm.__anchorInheritanceForTest.selectCandidate(4, candidate('sa-fee', '6602', 'fee'))
    await wrapper.vm.$nextTick()

    expect(vm.__anchorInheritanceForTest.dynamicUnresolvedCount.value).toBe(0)
    expect(vm.__anchorInheritanceForTest.canExecute.value).toBe(false)

    vm.__anchorInheritanceForTest.setWarningsConfirmed(true)
    await wrapper.vm.$nextTick()
    expect(vm.__anchorInheritanceForTest.canExecute.value).toBe(true)
  })
})
