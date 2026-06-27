from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORT_SERVICE = ROOT / "app" / "services" / "standard_trial_balance_import_service.py"


def test_entry_generation_skips_ignored_and_zero_skip_rows_and_reports_counts():
    source = IMPORT_SERVICE.read_text(encoding="utf-8")
    execute_source = source[source.index("async def execute_standard_import"):]
    entry_loop = execute_source[execute_source.index("for leaf in leaves:"):]

    assert "if leaf.row_index in ignored_row_set" in entry_loop
    assert "if leaf.row_index in execute_auto_skip_rows" in entry_loop
    assert '"participating_leaf_count"' in execute_source
    assert '"ignored_leaf_count"' in execute_source
    assert '"zero_amount_skipped_leaf_count"' in execute_source
    # TASK-094D：5 类行集合勾稽（与 094D 新口径一致）
    assert "raw_identified_leaf_count" in execute_source
    assert "eligible_business_leaf_rows" in execute_source
    assert "zero_amount_template_leaf_rows" in execute_source
    assert "summary_total_leaf_rows" in execute_source
    assert "duplicate_aggregate_leaf_rows" in execute_source
    assert "ignored_leaf_rows" in execute_source
    assert (
        "base_leaf_rows == eligible + zero + summary + duplicate + ignored" in execute_source
    )
    assert "entry_count must equal eligible_business_leaf_count" in execute_source
    assert '"business_amount_reconciliation"' in execute_source
    assert '"summary_amount_reconciliation"' in execute_source
    assert "business amount reconciliation failed" in execute_source
    assert "opening_debit" in execute_source
    assert "opening_credit" in execute_source
    assert "current_debit" in execute_source
    assert "current_credit" in execute_source
    assert "ending_debit" in execute_source
    assert "ending_credit" in execute_source