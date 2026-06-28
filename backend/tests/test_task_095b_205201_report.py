from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_account_mapping import ClientAccountMapping
from app.models.standard_account import StandardAccount
from app.services.file_parser import parse_trial_balance_import
from app.services.standard_trial_balance_import_service import (
    analyze_standard_import,
    execute_standard_import,
    preview_standard_import,
)
from test_task_094c_205201_compression import (
    REAL_205201_PATH,
    _ensure_min_standard_accounts,
    _read_xls_to_xlsx,
    _sniff_field_mappings,
)


REPORT_DIR = Path(__file__).parent.parent / "test_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _category_and_direction_for_code(code: str) -> tuple[str, str]:
    if code.startswith("2"):
        return "liability", "credit"
    if code.startswith("4"):
        return "equity", "credit"
    if code.startswith(("600", "605", "611", "630")):
        return "revenue", "credit"
    if code.startswith(("5", "6")):
        return "expense", "debit"
    return "asset", "debit"


async def _ensure_standard_accounts_for_nodes(
    db: AsyncSession,
    analyze: dict,
) -> dict[str, StandardAccount]:
    result = await db.execute(select(StandardAccount))
    by_code = {sa.account_code: sa for sa in result.scalars().all()}

    for node in analyze.get("unique_mapping_nodes", []):
        if node.get("node_type") == "summary":
            continue
        code = str(node.get("account_code") or "").strip()
        if not code or code in by_code:
            continue
        category, direction = _category_and_direction_for_code(code)
        account = StandardAccount(
            account_code=code,
            account_name=str(node.get("account_name") or code).strip() or code,
            account_category=category,
            balance_direction=direction,
            level=max(1, min(len(code) // 2, 6)),
            is_leaf=True,
            is_active=True,
        )
        db.add(account)
        by_code[code] = account
    await db.flush()
    return by_code


async def _build_full_node_mappings(
    db: AsyncSession,
    analyze: dict,
) -> list[dict]:
    accounts_by_code = await _ensure_standard_accounts_for_nodes(db, analyze)

    mappings: list[dict] = []
    seen_node_keys: set[str] = set()
    for node in analyze.get("unique_mapping_nodes", []):
        if node.get("node_type") == "summary":
            continue
        node_key = str(node.get("node_key") or "").strip()
        code = str(node.get("account_code") or "").strip()
        if not node_key or not code or node_key in seen_node_keys:
            continue
        account = accounts_by_code.get(code)
        if account is None:
            continue
        seen_node_keys.add(node_key)
        mappings.append({
            "node_key": node_key,
            "representative_row_index": node.get("representative_row_index"),
            "standard_account_id": str(account.id),
            "standard_account_code": account.account_code,
            "standard_account_name": account.account_name,
            "mapping_action": "anchor",
            "apply_to_descendants": True,
            "selection_source": "user_confirmed",
        })

    return sorted(
        mappings,
        key=lambda item: int(item.get("representative_row_index") or 0),
    )


def _max_abs_business_difference(execute: dict) -> str:
    max_diff = 0.0
    for info in (execute.get("business_amount_reconciliation") or {}).values():
        try:
            max_diff = max(max_diff, abs(float(info.get("difference", 0))))
        except (TypeError, ValueError):
            continue
    return f"{max_diff:.2f}"


@pytest.mark.skipif(
    not os.path.exists(REAL_205201_PATH),
    reason=f"205201 real file not found: {REAL_205201_PATH}",
)
@pytest.mark.asyncio
async def test_task_095b_205201_node_mapping_report(db: AsyncSession):
    await _ensure_min_standard_accounts(db)
    await db.execute(
        delete(ClientAccountMapping).where(ClientAccountMapping.customer_label == "205201")
    )
    await db.flush()

    src_path = _read_xls_to_xlsx(REAL_205201_PATH)
    try:
        t0 = time.time()
        preview = await preview_standard_import(
            db=db,
            file_path=src_path,
            file_name="205201-2023.xls",
            fiscal_year=2023,
            period=12,
            customer_label="205201",
        )
        preview_seconds = time.time() - t0
        batch_id = uuid.UUID(preview["batch_id"])

        parsed = parse_trial_balance_import(src_path)
        headers = parsed["merged_headers"]
        field_mappings = _sniff_field_mappings(headers, parsed["all_rows"][:5])
        if not any(f["field_name"] == "account_code" for f in field_mappings):
            field_mappings.insert(0, {"column_id": "col_0", "field_name": "account_code"})
        if not any(f["field_name"] == "account_name" for f in field_mappings):
            field_mappings.insert(1, {"column_id": "col_1", "field_name": "account_name"})
        if not any(f.get("period_type") in {"opening", "current", "ending"} for f in field_mappings):
            for idx, header in enumerate(headers):
                if "期末" in (header or ""):
                    field_mappings.append({
                        "column_id": f"col_{idx}",
                        "field_name": "ending_amount",
                        "period_type": "ending",
                        "split_mode": "single_by_direction",
                    })
                    break

        t0 = time.time()
        analyze = await analyze_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=src_path,
            field_mappings=field_mappings,
            fiscal_year=2023,
            period=12,
            customer_label="205201",
            hierarchy_mode="auto",
        )
        analyze_seconds = time.time() - t0

        ignored_rows: list[int] = []
        confirmed_node_mappings = await _build_full_node_mappings(db, analyze)

        t0 = time.time()
        execute = await execute_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=src_path,
            confirmed_mappings=[],
            confirmed_node_mappings=confirmed_node_mappings,
            ignored_rows=ignored_rows,
            warnings_confirmed=True,
            save_mapping_experience=True,
        )
        execute_seconds = time.time() - t0

        report = {
            "task": "TASK-095B",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "file_name": "205201-2023.xls",
            "customer_label": "205201",
            "raw_row_count": execute.get("raw_row_count", 0),
            "unique_node_count": execute.get("unique_node_count", analyze.get("unique_node_count", 0)),
            "analyze_unique_mapping_nodes": len(analyze.get("unique_mapping_nodes", [])),
            "row_node_bindings": len(analyze.get("row_node_bindings", [])),
            "confirmed_node_mapping_count": execute.get("confirmed_node_mapping_count", 0),
            "auto_confirmed_node_count": execute.get("auto_confirmed_node_count", 0),
            "manual_confirmed_node_count": execute.get("manual_confirmed_node_count", 0),
            "duplicate_row_submit_count": execute.get("duplicate_row_submit_count", 0),
            "row_level_confirmed_mapping_count": execute.get("row_level_confirmed_mapping_count", 0),
            "mapping_experience_saved_count": execute.get("mapping_experience_saved_count", 0),
            "entry_count": execute.get("entry_count", 0),
            "unresolved_node_count": execute.get("unresolved_node_count", 0),
            "ignored_rows": len(ignored_rows),
            "max_business_amount_difference": _max_abs_business_difference(execute),
            "preview_seconds": round(preview_seconds, 2),
            "analyze_seconds": round(analyze_seconds, 2),
            "execute_seconds": round(execute_seconds, 2),
            "total_seconds": round(preview_seconds + analyze_seconds + execute_seconds, 2),
            "gates": {
                "confirmed_node_mapping_count_lte_unique_nodes": (
                    execute.get("confirmed_node_mapping_count", 0)
                    <= execute.get("unique_node_count", analyze.get("unique_node_count", 0))
                ),
                "duplicate_row_submit_count_zero": execute.get("duplicate_row_submit_count", 0) == 0,
                "row_level_confirmed_mapping_count_zero": execute.get("row_level_confirmed_mapping_count", 0) == 0,
                "mapping_experience_lte_confirmed_nodes": (
                    execute.get("mapping_experience_saved_count", 0)
                    <= execute.get("confirmed_node_mapping_count", 0)
                ),
                "unresolved_node_count_zero": execute.get("unresolved_node_count", 0) == 0,
                "entry_count_positive": execute.get("entry_count", 0) > 0,
                "amount_difference_zero": _max_abs_business_difference(execute) == "0.00",
            },
        }

        json_path = REPORT_DIR / "task_095b_205201_node_mapping.json"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        md_path = REPORT_DIR / "task_095b_205201_node_mapping.md"
        md_path.write_text(
            "\n".join([
                "# TASK-095B 205201 Node Mapping Report",
                "",
                f"- generated_at: {report['generated_at']}",
                f"- raw_row_count: {report['raw_row_count']}",
                f"- unique_node_count: {report['unique_node_count']}",
                f"- confirmed_node_mapping_count: {report['confirmed_node_mapping_count']}",
                f"- auto_confirmed_node_count: {report['auto_confirmed_node_count']}",
                f"- manual_confirmed_node_count: {report['manual_confirmed_node_count']}",
                f"- duplicate_row_submit_count: {report['duplicate_row_submit_count']}",
                f"- row_level_confirmed_mapping_count: {report['row_level_confirmed_mapping_count']}",
                f"- mapping_experience_saved_count: {report['mapping_experience_saved_count']}",
                f"- entry_count: {report['entry_count']}",
                f"- unresolved_node_count: {report['unresolved_node_count']}",
                f"- max_business_amount_difference: {report['max_business_amount_difference']}",
                "",
                "## Gates",
                "",
                *[f"- {name}: {'PASS' if ok else 'FAIL'}" for name, ok in report["gates"].items()],
                "",
                "## Timings",
                "",
                f"- preview_seconds: {report['preview_seconds']}",
                f"- analyze_seconds: {report['analyze_seconds']}",
                f"- execute_seconds: {report['execute_seconds']}",
                f"- total_seconds: {report['total_seconds']}",
                "",
            ]),
            encoding="utf-8",
        )

        assert all(report["gates"].values()), report
    finally:
        if src_path != REAL_205201_PATH:
            try:
                Path(src_path).unlink()
            except FileNotFoundError:
                pass
