from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.client_account_mapping import ClientAccountMapping
from app.services.standard_trial_balance_import_service import (
    analyze_standard_import,
    execute_standard_import,
    preview_standard_import,
)
from task_095b_helpers import FIELD_MAPPINGS, make_excel, node_mapping_payload, remove_file, seed_accounts


@pytest.mark.asyncio
async def test_same_node_experience_is_saved_once_and_inherited_not_saved(db):
    accounts = await seed_accounts(
        db,
        [
            {"code": "1002", "name": "Bank", "is_leaf": False},
            {"code": "100201", "name": "Bank Detail", "is_leaf": True},
        ],
    )
    file_path = make_excel(
        [
            ["1002", "Bank", "0", "0"],
            ["100201", "Bank Detail", "100", "0"],
            ["100201", "Bank Detail", "200", "0"],
        ]
    )

    try:
        preview = await preview_standard_import(
            db,
            file_path,
            "experience-dedup.xlsx",
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Experience",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        analyze = await analyze_standard_import(
            db,
            batch_id,
            file_path,
            field_mappings=FIELD_MAPPINGS,
            fiscal_year=2026,
            period=6,
            customer_label="TASK095B Experience",
            hierarchy_mode="code",
        )
        parent_node = next(node for node in analyze["unique_mapping_nodes"] if node["account_code"] == "1002")

        execute = await execute_standard_import(
            db,
            batch_id,
            file_path,
            confirmed_mappings=[],
            confirmed_node_mappings=[node_mapping_payload(parent_node, accounts["1002"])],
            warnings_confirmed=True,
            save_mapping_experience=True,
        )

        assert execute["status"] == "executed"
        assert execute["entry_count"] == 2
        assert execute["mapping_saved_count"] == 1
        assert execute["mapping_experience_saved_count"] == 1
        assert execute["mapping_experience_saved_count"] <= execute["confirmed_node_mapping_count"]

        saved = (
            await db.execute(
                select(ClientAccountMapping)
                .where(ClientAccountMapping.customer_label == "TASK095B Experience")
                .order_by(ClientAccountMapping.client_account_code)
            )
        ).scalars().all()
        assert len(saved) == 1
        assert saved[0].client_account_code == "1002"
        assert saved[0].mapping_kind == "anchor"
    finally:
        remove_file(file_path)
