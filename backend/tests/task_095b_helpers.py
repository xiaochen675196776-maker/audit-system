from __future__ import annotations

import os
import tempfile
import uuid

import openpyxl
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.standard_account import StandardAccount


FIELD_MAPPINGS = [
    {"column_id": "col_0", "field_name": "account_code"},
    {"column_id": "col_1", "field_name": "account_name"},
    {
        "column_id": "col_2",
        "field_name": "ending_debit",
        "period_type": "ending",
        "split_mode": "two_column",
        "debit_column_id": "col_2",
        "credit_column_id": "col_3",
    },
    {
        "column_id": "col_3",
        "field_name": "ending_credit",
        "period_type": "ending",
        "split_mode": "two_column",
        "debit_column_id": "col_2",
        "credit_column_id": "col_3",
    },
]


def make_excel(rows: list[list[str]]) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["account_code", "account_name", "ending_debit", "ending_credit"])
    for row in rows:
        ws.append(row)
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    wb.save(tmp.name)
    tmp.close()
    return tmp.name


def remove_file(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


async def seed_accounts(
    db: AsyncSession,
    accounts: list[dict],
) -> dict[str, StandardAccount]:
    out: dict[str, StandardAccount] = {}
    for item in accounts:
        account = StandardAccount(
            account_code=item["code"],
            account_name=item["name"],
            balance_direction=item.get("direction", "debit"),
            account_category=item.get("category", "asset"),
            level=item.get("level", 1),
            is_leaf=item.get("is_leaf", True),
            is_active=item.get("is_active", True),
        )
        db.add(account)
        await db.flush()
        out[item["code"]] = account
    return out


def node_mapping_payload(node: dict, account: StandardAccount) -> dict:
    return {
        "node_key": node["node_key"],
        "representative_row_index": node.get("representative_row_index"),
        "standard_account_id": account.id,
        "standard_account_code": account.account_code,
        "standard_account_name": account.account_name,
        "mapping_action": "anchor",
        "apply_to_descendants": True,
        "selection_source": "user_confirmed",
    }


def row_mapping_payload(row_index: int, client_code: str, client_name: str, account: StandardAccount) -> dict:
    return {
        "row_index": row_index,
        "client_account_code": client_code,
        "client_account_name": client_name,
        "standard_account_id": account.id,
        "standard_account_code": account.account_code,
        "standard_account_name": account.account_name,
        "mapping_action": "anchor",
        "apply_to_descendants": True,
        "selection_source": "user_confirmed",
    }


def as_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
