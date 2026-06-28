from __future__ import annotations

import uuid

import pytest

from app.schemas.standard_trial_balance import AnalyzeResponse
from app.services.account_mapping_inheritance_service import compute_unique_node_key
from app.services.standard_trial_balance_import_service import (
    analyze_standard_import,
    preview_standard_import,
)
from task_095b_helpers import FIELD_MAPPINGS, make_excel, remove_file, seed_accounts


@pytest.mark.asyncio
async def test_analyze_returns_one_unique_node_for_1000_duplicate_rows(db):
    accounts = await seed_accounts(db, [{"code": "1001", "name": "Cash"}])
    file_path = make_excel([["1001", "Cash", "1", "0"] for _ in range(1000)])

    try:
        preview = await preview_standard_import(
            db,
            file_path,
            "task095b-1000.xlsx",
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Customer A",
        )
        analyze = await analyze_standard_import(
            db,
            uuid.UUID(preview["batch_id"]),
            file_path,
            field_mappings=FIELD_MAPPINGS,
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Customer A",
            hierarchy_mode="flat",
        )

        assert len(analyze["unique_mapping_nodes"]) == 1
        node = analyze["unique_mapping_nodes"][0]
        assert node["node_key"].startswith("uak:v2:")
        assert node["representative_row_index"] == 0
        assert node["source_row_count"] == 1000
        assert node["source_row_indexes"] == list(range(1000))
        assert node["account_code"] == "1001"
        assert node["account_name"] == "Cash"
        assert node["suggested_standard_account_id"] == str(accounts["1001"].id)

        assert len(analyze["row_node_bindings"]) == 1000
        assert {b["node_key"] for b in analyze["row_node_bindings"]} == {node["node_key"]}

        duplicate_recs = [
            rec
            for rec in analyze["mapping_recommendations"]
            if rec.get("row_index") != node["representative_row_index"]
        ]
        assert duplicate_recs
        assert all(rec["mapping_editable"] is False for rec in duplicate_recs)
        assert all(rec["deprecated"] is True for rec in duplicate_recs)

        AnalyzeResponse.model_validate(analyze)
    finally:
        remove_file(file_path)


def test_node_key_uses_v2_prefix_customer_and_parent_path() -> None:
    base = compute_unique_node_key("1001", "Cash", "", customer_label="Customer A")
    same = compute_unique_node_key("1001", "Cash", "", customer_label="Customer A")
    other_customer = compute_unique_node_key("1001", "Cash", "", customer_label="Customer B")
    other_parent = compute_unique_node_key("1001", "Cash", "Assets\\Cash", customer_label="Customer A")

    assert base == same
    assert base.startswith("uak:v2:")
    assert base != other_customer
    assert base != other_parent
