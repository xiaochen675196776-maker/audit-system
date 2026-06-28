from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow
from app.services.standard_trial_balance_import_service import (
    analyze_standard_import,
    execute_standard_import,
    preview_standard_import,
)
from task_095b_helpers import (
    FIELD_MAPPINGS,
    make_excel,
    node_mapping_payload,
    remove_file,
    row_mapping_payload,
    seed_accounts,
)


@pytest.mark.asyncio
async def test_confirmed_node_mapping_executes_all_bound_rows(db):
    accounts = await seed_accounts(db, [{"code": "1001", "name": "Cash"}])
    file_path = make_excel(
        [
            ["1001", "Cash", "10", "0"],
            ["1001", "Cash", "20", "0"],
            ["1001", "Cash", "30", "0"],
        ]
    )

    try:
        preview = await preview_standard_import(
            db,
            file_path,
            "node-execute.xlsx",
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Execute",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        analyze = await analyze_standard_import(
            db,
            batch_id,
            file_path,
            field_mappings=FIELD_MAPPINGS,
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Execute",
            hierarchy_mode="flat",
        )
        node = analyze["unique_mapping_nodes"][0]

        execute = await execute_standard_import(
            db,
            batch_id,
            file_path,
            confirmed_mappings=[],
            confirmed_node_mappings=[node_mapping_payload(node, accounts["1001"])],
            warnings_confirmed=True,
            save_mapping_experience=True,
        )

        assert execute["status"] == "executed"
        assert execute["entry_count"] == 3
        assert execute["confirmed_node_mapping_count"] == 1
        assert execute["row_level_confirmed_mapping_count"] == 0
        assert execute["duplicate_row_submit_count"] == 0
        assert execute["unresolved_node_count"] == 0

        rows = (
            await db.execute(
                select(StandardTrialBalanceRawRow)
                .where(StandardTrialBalanceRawRow.batch_id == batch_id)
                .order_by(StandardTrialBalanceRawRow.row_index)
            )
        ).scalars().all()
        assert [row.mapped_standard_account_id for row in rows] == [accounts["1001"].id] * 3
        assert {row.node_key for row in rows} == {node["node_key"]}
        assert {row.mapping_source for row in rows} == {"node_binding"}

        entries = (
            await db.execute(
                select(StandardTrialBalanceEntry)
                .where(StandardTrialBalanceEntry.batch_id == batch_id)
                .order_by(StandardTrialBalanceEntry.client_account_code)
            )
        ).scalars().all()
        assert len(entries) == 3
    finally:
        remove_file(file_path)


@pytest.mark.asyncio
async def test_legacy_row_mappings_fold_to_one_node(db):
    accounts = await seed_accounts(db, [{"code": "1001", "name": "Cash"}])
    file_path = make_excel(
        [
            ["1001", "Cash", "10", "0"],
            ["1001", "Cash", "20", "0"],
            ["1001", "Cash", "30", "0"],
        ]
    )

    try:
        preview = await preview_standard_import(
            db,
            file_path,
            "row-fold.xlsx",
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Legacy",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        await analyze_standard_import(
            db,
            batch_id,
            file_path,
            field_mappings=FIELD_MAPPINGS,
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Legacy",
            hierarchy_mode="flat",
        )

        execute = await execute_standard_import(
            db,
            batch_id,
            file_path,
            confirmed_mappings=[
                row_mapping_payload(0, "1001", "Cash", accounts["1001"]),
                row_mapping_payload(1, "1001", "Cash", accounts["1001"]),
                row_mapping_payload(2, "1001", "Cash", accounts["1001"]),
            ],
            warnings_confirmed=True,
            save_mapping_experience=False,
        )

        assert execute["status"] == "executed"
        assert execute["entry_count"] == 3
        assert execute["confirmed_node_mapping_count"] == 1
        assert execute["duplicate_row_submit_count"] == 0
        assert execute["row_level_confirmed_mapping_count"] == 3
    finally:
        remove_file(file_path)


@pytest.mark.asyncio
async def test_legacy_row_mappings_same_node_different_targets_are_blocked(db):
    accounts = await seed_accounts(
        db,
        [
            {"code": "1001", "name": "Cash"},
            {"code": "1002", "name": "Bank"},
        ],
    )
    file_path = make_excel(
        [
            ["1001", "Cash", "10", "0"],
            ["1001", "Cash", "20", "0"],
        ]
    )

    try:
        preview = await preview_standard_import(
            db,
            file_path,
            "row-conflict.xlsx",
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Conflict",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        await analyze_standard_import(
            db,
            batch_id,
            file_path,
            field_mappings=FIELD_MAPPINGS,
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Conflict",
            hierarchy_mode="flat",
        )

        with pytest.raises(ValueError, match="same node_key"):
            await execute_standard_import(
                db,
                batch_id,
                file_path,
                confirmed_mappings=[
                    row_mapping_payload(0, "1001", "Cash", accounts["1001"]),
                    row_mapping_payload(1, "1001", "Cash", accounts["1002"]),
                ],
                warnings_confirmed=True,
            )
    finally:
        remove_file(file_path)
