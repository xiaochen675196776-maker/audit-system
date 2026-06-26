"""Acceptance script for importing trial balances extracted from real ERP .DB files.

This script is intentionally read-only for the source DB files. It converts the
extracted balances to temporary CSV files, then runs the existing standardized
trial balance import pipeline:

    seed_standard_accounts -> preview_standard_import -> analyze_standard_import
    -> execute_standard_import -> get_tree

Hard constraints:
  - Do not add/remove/change built-in standard accounts.
  - Every imported active row must be auto-matchable safely.
  - Parent amount mismatch warnings are allowed; other warnings fail.
"""

from __future__ import annotations

import ast
import asyncio
import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.data.standard_accounts_seed import SEED_ACCOUNTS  # noqa: E402
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch  # noqa: E402
from app.services.client_account_mapping_service import _pick_auto_confirm_candidate  # noqa: E402
from app.services.file_parser import parse_trial_balance_import, slice_data_rows  # noqa: E402
from app.services.standard_account_service import seed_standard_accounts  # noqa: E402
from app.services.standard_trial_balance_import_service import (  # noqa: E402
    _collect_summary_total_skip_rows,
    _collect_zero_amount_template_rows,
    analyze_standard_import,
    execute_standard_import,
    preview_standard_import,
)
from app.services.standard_trial_balance_service import get_tree  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]

NC6_DB = Path(
    "D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/骆驼股份2024年年审/账套/"
    "采集[财务]_0277用友NC6财务_[丰城诺佳再生资源有限公司_基准账簿!2024_2024].DB"
)
K3_DB = Path(
    "D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/荆门高新2024年年审/"
    "审计资料2024（公司提供的资料）/账套（有公司改账了，2025年2月21日重新导的账套）/"
    "采集[财务]_0310金蝶K3Cloud_[湖北楚达路桥工程有限公司!2024_2024].DB"
)

CSV_HEADERS = [
    "科目代码",
    "科目名称",
    "期初借方余额",
    "期初贷方余额",
    "本期借方发生额",
    "本期贷方发生额",
    "期末借方余额",
    "期末贷方余额",
]

FIELD_MAPPINGS = [
    {"column_id": "col_0", "field_name": "account_code"},
    {"column_id": "col_1", "field_name": "account_name"},
    {
        "column_id": "col_2",
        "field_name": "opening_debit",
        "period_type": "opening",
        "split_mode": "two_column",
        "debit_column_id": "col_2",
        "credit_column_id": "col_3",
    },
    {
        "column_id": "col_3",
        "field_name": "opening_credit",
        "period_type": "opening",
        "split_mode": "two_column",
        "debit_column_id": "col_2",
        "credit_column_id": "col_3",
    },
    {
        "column_id": "col_4",
        "field_name": "current_debit",
        "period_type": "current",
        "split_mode": "two_column",
        "debit_column_id": "col_4",
        "credit_column_id": "col_5",
    },
    {
        "column_id": "col_5",
        "field_name": "current_credit",
        "period_type": "current",
        "split_mode": "two_column",
        "debit_column_id": "col_4",
        "credit_column_id": "col_5",
    },
    {
        "column_id": "col_6",
        "field_name": "ending_debit",
        "period_type": "ending",
        "split_mode": "two_column",
        "debit_column_id": "col_6",
        "credit_column_id": "col_7",
    },
    {
        "column_id": "col_7",
        "field_name": "ending_credit",
        "period_type": "ending",
        "split_mode": "two_column",
        "debit_column_id": "col_6",
        "credit_column_id": "col_7",
    },
]


@dataclass
class SourceCase:
    name: str
    source_path: Path
    customer_label: str
    extractor: str


SOURCE_CASES = [
    SourceCase(
        name="NC6_丰城诺佳再生资源有限公司_2024",
        source_path=NC6_DB,
        customer_label="丰城诺佳再生资源有限公司",
        extractor="nc6",
    ),
    SourceCase(
        name="K3Cloud_湖北楚达路桥工程有限公司_2024",
        source_path=K3_DB,
        customer_label="湖北楚达路桥工程有限公司",
        extractor="k3",
    ),
]


def _print(message: str) -> None:
    print(message, flush=True)


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if not text or text in {"~", "-", "None"}:
        return Decimal("0")
    return Decimal(text)


def _split_signed_balance(amount: Decimal) -> tuple[Decimal, Decimal]:
    if amount >= 0:
        return amount, Decimal("0")
    return Decimal("0"), -amount


def _fmt(amount: Decimal) -> str:
    amount = amount.quantize(Decimal("0.01"))
    if amount == 0:
        return "0.00"
    return format(amount, "f")


def _account_name_from_display(display_name: str | None, fallback: str | None) -> str:
    text = (display_name or "").strip()
    if text:
        parts = [p for p in text.replace("/", "\\").split("\\") if p.strip()]
        if len(parts) >= 2:
            return "_".join(parts[1:])
    return (fallback or "").strip() or text


def _read_seed_accounts_from_head() -> list[dict[str, Any]]:
    rel_path = "backend/app/data/standard_accounts_seed.py"
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{rel_path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())
    tree = ast.parse(result.stdout)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "SEED_ACCOUNTS":
                return ast.literal_eval(node.value)
    raise AssertionError("SEED_ACCOUNTS not found in git HEAD")


def assert_standard_seed_not_changed() -> dict[str, Any]:
    old = _read_seed_accounts_from_head()
    current = SEED_ACCOUNTS
    old_codes = {a["account_code"] for a in old}
    new_codes = {a["account_code"] for a in current}
    old_by_code = {a["account_code"]: a for a in old}
    new_by_code = {a["account_code"]: a for a in current}

    added = sorted(new_codes - old_codes)
    removed = sorted(old_codes - new_codes)
    changed = sorted(code for code in old_codes & new_codes if old_by_code[code] != new_by_code[code])
    summary = {
        "old_count": len(old),
        "new_count": len(current),
        "added_code_count": len(added),
        "removed_code_count": len(removed),
        "changed_count": len(changed),
        "added_codes": added,
        "removed_codes": removed,
        "changed_codes": changed,
    }
    _print(f"[SEED] {json.dumps(summary, ensure_ascii=False)}")
    if added or removed or changed:
        raise AssertionError("standard account seed changed")
    return summary


def _open_sqlite_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def extract_k3_trial_balance(path: Path) -> list[list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = _open_sqlite_readonly(path)
    try:
        rows = conn.execute(
            """
            select
                a.FNUMBER as code,
                coalesce(l.FNAME, a.FNUMBER) as name,
                b.FBEGINBALANCE as opening_balance,
                b.FYTDDEBIT as current_debit,
                b.FYTDCREDIT as current_credit,
                b.FENDBALANCE as ending_balance
            from T_GL_BALANCE b
            join T_BD_ACCOUNT a on a.FACCTID = b.FACCOUNTID
            left join T_BD_ACCOUNT_L l
                on l.FACCTID = a.FACCTID and l.FLOCALEID = 2052
            where b.FYEAR = 2024
              and b.FPERIOD = 12
              and b.FCURRENCYID = 0
              and b.FDETAILID = 0
            order by a.FNUMBER
            """
        ).fetchall()
    finally:
        conn.close()

    output: list[list[str]] = []
    for row in rows:
        opening_debit, opening_credit = _split_signed_balance(_decimal(row["opening_balance"]))
        ending_debit, ending_credit = _split_signed_balance(_decimal(row["ending_balance"]))
        output.append(
            [
                str(row["code"]).strip(),
                str(row["name"]).strip(),
                _fmt(opening_debit),
                _fmt(opening_credit),
                _fmt(_decimal(row["current_debit"])),
                _fmt(_decimal(row["current_credit"])),
                _fmt(ending_debit),
                _fmt(ending_credit),
            ]
        )
    return output


def extract_nc6_trial_balance(path: Path) -> list[list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = _open_sqlite_readonly(path)
    try:
        rows = conn.execute(
            """
            select
                d.ACCOUNTCODE as code,
                max(coalesce(acc.DISPNAME, '')) as display_name,
                max(coalesce(acc.NAME, ba.NAME, '')) as fallback_name,
                sum(case
                    when d.PERIODV = '00'
                    then coalesce(d.LOCALDEBITAMOUNT, 0) - coalesce(d.LOCALCREDITAMOUNT, 0)
                    else 0
                end) as opening_net,
                sum(case
                    when d.PERIODV != '00'
                    then coalesce(d.LOCALDEBITAMOUNT, 0)
                    else 0
                end) as current_debit,
                sum(case
                    when d.PERIODV != '00'
                    then coalesce(d.LOCALCREDITAMOUNT, 0)
                    else 0
                end) as current_credit
            from GL_DETAIL d
            left join BD_ACCASOA acc on acc.PK_ACCASOA = d.PK_ACCASOA
            left join BD_ACCOUNT ba on ba.PK_ACCOUNT = d.PK_ACCOUNT
            where d.YEARV = '2024'
              and d.DR = 0
              and d.PK_ACCOUNTINGBOOK = (
                  select PK_ACCOUNTINGBOOK from ORG_ACCOUNTINGBOOK where DR = 0 limit 1
              )
            group by d.ACCOUNTCODE
            having code is not null and trim(code) != ''
            order by d.ACCOUNTCODE
            """
        ).fetchall()
    finally:
        conn.close()

    output: list[list[str]] = []
    for row in rows:
        opening_net = _decimal(row["opening_net"])
        current_debit = _decimal(row["current_debit"])
        current_credit = _decimal(row["current_credit"])
        ending_net = opening_net + current_debit - current_credit
        opening_debit, opening_credit = _split_signed_balance(opening_net)
        ending_debit, ending_credit = _split_signed_balance(ending_net)
        output.append(
            [
                str(row["code"]).strip(),
                _account_name_from_display(row["display_name"], row["fallback_name"]),
                _fmt(opening_debit),
                _fmt(opening_credit),
                _fmt(current_debit),
                _fmt(current_credit),
                _fmt(ending_debit),
                _fmt(ending_credit),
            ]
        )
    return output


def write_csv(rows: list[list[str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        writer.writerows(rows)


def _period_configs(field_mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    configs = []
    for fm in field_mappings:
        if fm.get("period_type") and fm.get("split_mode"):
            configs.append(
                {
                    "period_type": fm["period_type"],
                    "mode": fm["split_mode"],
                    "debit_field": fm.get("debit_column_id"),
                    "credit_field": fm.get("credit_column_id"),
                    "amount_field": fm.get("column_id"),
                }
            )
    return configs


def _col_id_to_index(headers: list[str]) -> dict[str, int]:
    return {f"col_{idx}": idx for idx, _ in enumerate(headers)}


def _collect_node_ids(node: dict[str, Any], collector: list[str]) -> None:
    node_id = node.get("node_id")
    if node_id is not None:
        collector.append(str(node_id))
    for child in node.get("children", []) or []:
        _collect_node_ids(child, collector)


async def run_one(case: SourceCase, csv_path: Path, db: AsyncSession) -> dict[str, Any]:
    t0 = time.time()
    preview = await preview_standard_import(
        db,
        str(csv_path),
        csv_path.name,
        fiscal_year=2024,
        period=12,
        customer_label=case.customer_label,
    )
    batch_id = uuid.UUID(preview["batch_id"])

    analyze = await analyze_standard_import(
        db,
        batch_id,
        str(csv_path),
        field_mappings=FIELD_MAPPINGS,
        fiscal_year=2024,
        period=12,
        customer_label=case.customer_label,
        hierarchy_mode="auto",
    )
    recs = analyze["mapping_recommendations"]
    warnings = analyze["warnings"]
    errors = analyze["errors"]

    active_recs = [r for r in recs if r.get("participates_in_entry", True)]
    unmatched = [r for r in active_recs if not r.get("candidates")]
    unsafe: list[dict[str, Any]] = []
    confirmed_mappings: list[dict[str, Any]] = []

    for rec in active_recs:
        candidates = rec.get("candidates", []) or []
        picked = _pick_auto_confirm_candidate(candidates) if candidates else None
        if picked is None:
            continue
        score = float(picked.get("score", 0) or 0)
        if score < 0.85:
            unsafe.append(rec)
            continue
        confirmed_mappings.append(
            {
                "row_index": rec["row_index"],
                "client_account_code": rec.get("client_account_code"),
                "client_account_name": rec.get("client_account_name"),
                "standard_account_id": uuid.UUID(picked["standard_account_id"]),
                "standard_account_code": picked["standard_account_code"],
                "standard_account_name": picked["standard_account_name"],
            }
        )

    non_parent_warnings = [
        w
        for w in warnings
        if w.get("category") not in ("parent_amount_mismatch", "disabled_standard_account")
    ]

    execute_status = "not_executed"
    entry_count = 0
    execute_error = None
    try:
        execute = await execute_standard_import(
            db,
            batch_id,
            str(csv_path),
            confirmed_mappings=confirmed_mappings,
            warnings_confirmed=True,
            save_mapping_experience=True,
        )
        execute_status = execute["status"]
        entry_count = execute["entry_count"]
    except Exception as exc:  # pragma: no cover - diagnostic script path
        execute_error = f"{type(exc).__name__}: {exc}"
        await db.rollback()

    tree_error = None
    tree_total_nodes = 0
    dup_node_id_count = 0
    try:
        nodes, tree_total_nodes = await get_tree(db, batch_id=batch_id)
        node_ids: list[str] = []
        for root in nodes:
            _collect_node_ids(root, node_ids)
        dup_node_id_count = len([node_id for node_id in set(node_ids) if node_ids.count(node_id) > 1])
    except Exception as exc:  # pragma: no cover - diagnostic script path
        tree_error = f"{type(exc).__name__}: {exc}"
        await db.rollback()

    parsed = parse_trial_balance_import(str(csv_path))
    batch = (
        await db.execute(
            select(StandardTrialBalanceImportBatch).where(StandardTrialBalanceImportBatch.id == batch_id)
        )
    ).scalar_one_or_none()
    hierarchy_config = (batch.hierarchy_config or {}) if batch else {}
    parse_config = hierarchy_config.get("parse_config") or {}
    data_start_row = int(parse_config.get("data_start_row") or parsed["data_start_row"])
    merged_headers = parse_config.get("merged_headers") or parsed["merged_headers"]
    col_idx = _col_id_to_index(merged_headers)
    data_rows = slice_data_rows(parsed["all_rows"], data_start_row)
    zero_skip = _collect_zero_amount_template_rows(data_rows, _period_configs(FIELD_MAPPINGS), col_idx)
    summary_skip = _collect_summary_total_skip_rows(data_rows, col_idx, "col_0", "col_1")

    return {
        "name": case.name,
        "source_path": str(case.source_path),
        "csv_path": str(csv_path),
        # preview_standard_import already reports data rows after header detection.
        "extracted_rows": preview["total_rows"],
        "preview_total_rows": preview["total_rows"],
        "data_start_row": data_start_row,
        "active_recommendations": len(active_recs),
        "confirmed_count": len(confirmed_mappings),
        "unmatched_count": len(unmatched),
        "unsafe_count": len(unsafe),
        "warning_count": len(warnings),
        "non_parent_warning_count": len(non_parent_warnings),
        "error_count": len(errors),
        "execute_status": execute_status,
        "execute_error": execute_error,
        "entry_count": entry_count,
        "tree_error": tree_error,
        "tree_total_nodes": tree_total_nodes,
        "dup_node_id_count": dup_node_id_count,
        "ignored_zero_amount_rows": len(zero_skip),
        "ignored_summary_total_rows": len(summary_skip),
        "top_unmatched": [
            {
                "row_index": r.get("row_index"),
                "code": r.get("client_account_code"),
                "name": r.get("client_account_name"),
            }
            for r in unmatched[:20]
        ],
        "top_unsafe": [
            {
                "row_index": r.get("row_index"),
                "code": r.get("client_account_code"),
                "name": r.get("client_account_name"),
                "picked": _pick_auto_confirm_candidate(r.get("candidates", []) or []),
            }
            for r in unsafe[:20]
        ],
        "non_parent_warnings": non_parent_warnings[:20],
        "errors": errors[:20],
        "elapsed_sec": round(time.time() - t0, 2),
    }


def extract_case(case: SourceCase, tmp_dir: Path) -> Path:
    if case.extractor == "nc6":
        rows = extract_nc6_trial_balance(case.source_path)
    elif case.extractor == "k3":
        rows = extract_k3_trial_balance(case.source_path)
    else:
        raise ValueError(f"unsupported extractor: {case.extractor}")
    output_path = tmp_dir / f"{case.name}.csv"
    write_csv(rows, output_path)
    _print(f"[EXTRACT] {case.name}: rows={len(rows)} csv={output_path}")
    if not rows:
        raise AssertionError(f"no rows extracted: {case.name}")
    return output_path


async def run_acceptance() -> None:
    started = time.time()
    assert_standard_seed_not_changed()

    with tempfile.TemporaryDirectory(prefix="task086_db_trial_balance_") as tmp:
        tmp_dir = Path(tmp)
        csv_paths = {case.name: extract_case(case, tmp_dir) for case in SOURCE_CASES}

        temp_db = tmp_dir / "acceptance.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{temp_db}")
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        summaries: list[dict[str, Any]] = []
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as db:
                seed_result = await seed_standard_accounts(db)
                _print(f"[SEED-DB] {json.dumps(seed_result, ensure_ascii=False, default=str)}")

                for case in SOURCE_CASES:
                    _print(f"\n=== {case.name} ===")
                    summary = await run_one(case, csv_paths[case.name], db)
                    summaries.append(summary)
                    _print(json.dumps(summary, ensure_ascii=False, default=str, indent=2))
        finally:
            await engine.dispose()

    _print("\n=== SUMMARY ===")
    _print(json.dumps(summaries, ensure_ascii=False, default=str, indent=2))

    all_ok = True
    for item in summaries:
        checks = [
            ("extracted_rows", item["extracted_rows"] > 0),
            ("execute_status", item["execute_status"] == "executed"),
            ("entry_count", item["entry_count"] > 0),
            ("unmatched_count", item["unmatched_count"] == 0),
            ("unsafe_count", item["unsafe_count"] == 0),
            ("non_parent_warning_count", item["non_parent_warning_count"] == 0),
            ("error_count", item["error_count"] == 0),
            ("execute_error", item["execute_error"] is None),
            ("tree_error", item["tree_error"] is None),
            ("tree_total_nodes", item["tree_total_nodes"] > 0),
            ("dup_node_id_count", item["dup_node_id_count"] == 0),
        ]
        failed = [name for name, ok in checks if not ok]
        if failed:
            all_ok = False
            _print(f"[FAIL] {item['name']}: {failed}")
        else:
            _print(f"[OK] {item['name']}")

    _print(f"[OVERALL] elapsed_sec={round(time.time() - started, 2)}")
    if not all_ok:
        _print("TASK086_DB_TRIAL_BALANCE_IMPORTS_FAILED")
        sys.exit(1)
    _print("TASK086_DB_TRIAL_BALANCE_IMPORTS_PASSED")


if __name__ == "__main__":
    asyncio.run(run_acceptance())
