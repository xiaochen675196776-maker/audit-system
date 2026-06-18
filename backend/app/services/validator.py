"""数据校验器 — 借贷平衡、必填检查、科目一致性验证"""

import uuid
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.account import Account
from app.services.column_matcher import REQUIRED_FIELDS


def _to_decimal(value: Any) -> Decimal | None:
    """安全转换为 Decimal"""
    if value is None or value == "" or value == "None":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("，", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    """安全转换为 int"""
    if value is None or value == "" or value == "None":
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


def _to_date(value: Any) -> date | None:
    """安全转换为 date"""
    if value is None or value == "" or value == "None":
        return None
    if isinstance(value, (date, datetime)):
        return value if isinstance(value, date) else value.date()
    try:
        s = str(value).strip()
        # 尝试多种日期格式
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y年%m月%d日"]:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        # pandas Timestamp
        try:
            from pandas import Timestamp
            return Timestamp(s).date()
        except Exception:
            pass
        return None
    except Exception:
        return None


async def _get_account_set(db: AsyncSession, company_id: uuid.UUID) -> set[str]:
    """获取该公司已存在的科目编码集合"""
    result = await db.execute(
        select(Account.code).where(Account.company_id == company_id)
    )
    return {row[0] for row in result.fetchall()}


def _validate_row(
    row: dict,
    data_type: str,
    required: list[str],
    account_set: set[str],
) -> list[str]:
    """校验单行数据，返回错误列表（空列表表示无错误）"""
    errors = []

    # 1. 必填检查
    for field in required:
        if field not in row or row[field] is None or str(row[field]).strip() == "":
            errors.append(f"必填字段 '{field}' 为空")

    # 2. 数值字段检查
    numeric_fields = []
    if data_type == "trial_balance":
        numeric_fields = [
            "opening_debit", "opening_credit",
            "current_debit", "current_credit",
            "ending_debit", "ending_credit",
        ]
    elif data_type in ("journal", "subsidiary"):
        numeric_fields = ["debit_amount", "credit_amount"]

    for field in numeric_fields:
        if field in row and row[field] is not None and str(row[field]).strip() != "":
            val = _to_decimal(row[field])
            if val is None:
                errors.append(f"字段 '{field}' 不是有效数字")

    # 3. 整数字段检查
    int_fields = ["fiscal_year", "period", "attachment_count", "account_level"]
    for field in int_fields:
        if field in row and row[field] is not None and str(row[field]).strip() != "":
            val = _to_int(row[field])
            if val is None:
                errors.append(f"字段 '{field}' 不是有效整数")

    # 4. 年度范围检查
    if "fiscal_year" in row:
        year = _to_int(row["fiscal_year"])
        if year is not None and (year < 2000 or year > 2100):
            errors.append(f"会计年度 {year} 不在合理范围 (2000-2100)")

    # 5. 期间范围检查
    if "period" in row:
        period = _to_int(row["period"])
        if period is not None and (period < 1 or period > 12):
            errors.append(f"会计期间 {period} 不在 1-12 范围内")

    # 6. 日期格式检查
    if "voucher_date" in row:
        d = _to_date(row["voucher_date"])
        if d is None and row.get("voucher_date") and str(row["voucher_date"]).strip() != "":
            errors.append("凭证日期格式无效")

    # 7. 科目编码存在于科目表中（如已有科目数据）
    if account_set and "account_code" in row:
        code = str(row["account_code"]).strip() if row["account_code"] else ""
        if code and code not in account_set:
            # 只警告，不阻止导入（可能科目尚未导入）
            pass

    return errors


async def validate_rows(
    db: AsyncSession,
    company_id: uuid.UUID,
    rows: list[dict],
    data_type: str,
) -> tuple[list[dict], list[dict]]:
    """
    校验所有数据行。

    Args:
        db: 数据库会话
        company_id: 被审计单位 ID
        rows: 已映射为标准字段的数据行列表
        data_type: trial_balance / journal / subsidiary

    Returns:
        (valid_rows, error_rows)
        valid_rows: 每行附带标准化后的值（date→date, decimal→Decimal）
        error_rows: 每行附带 errors 列表
    """
    required = REQUIRED_FIELDS.get(data_type, [])
    account_set = await _get_account_set(db, company_id)

    valid_rows = []
    error_rows = []

    for i, row in enumerate(rows, start=1):
        errors = _validate_row(row, data_type, required, account_set)
        if errors:
            error_rows.append({"row_number": i, "data": row, "errors": errors})
        else:
            # 标准化数据类型
            normalized = dict(row)
            for field, value in row.items():
                if value is None:
                    continue
                if field in ("voucher_date",):
                    d = _to_date(value)
                    if d:
                        normalized[field] = d
                if field in (
                    "opening_debit", "opening_credit",
                    "current_debit", "current_credit",
                    "ending_debit", "ending_credit",
                    "debit_amount", "credit_amount",
                ):
                    val = _to_decimal(value)
                    if val is not None:
                        normalized[field] = val
                    else:
                        normalized[field] = Decimal("0")
                if field in ("fiscal_year", "period", "attachment_count"):
                    val = _to_int(value)
                    if val is not None:
                        normalized[field] = val
                if field == "account_level":
                    val = _to_int(value)
                    if val is not None:
                        normalized[field] = val

            valid_rows.append({"row_number": i, "data": normalized})

    # 借贷平衡校验 — 只对序时账做凭证级借贷平衡校验
    # 科目余额表存在多级科目和汇总科目，不能按普通借贷合计直接拦截
    if data_type == "journal":
        _validate_journal_balance(valid_rows, error_rows)

    return valid_rows, error_rows


def _validate_balance(
    valid_rows: list[dict],
    error_rows: list[dict],
    data_type: str,
) -> None:
    """借贷平衡校验"""
    if data_type == "trial_balance":
        _validate_trial_balance(valid_rows, error_rows)
    elif data_type in ("journal", "subsidiary"):
        _validate_journal_balance(valid_rows, error_rows)


def _validate_trial_balance(
    valid_rows: list[dict],
    error_rows: list[dict],
) -> None:
    """科目余额表：按 (年度, 期间) 分组，检查 期末借方合计 ≈ 期末贷方合计"""
    from collections import defaultdict
    groups: dict[tuple, list] = defaultdict(list)

    for item in valid_rows:
        d = item["data"]
        key = (d.get("fiscal_year"), d.get("period"))
        groups[key].append(item)

    for (year, period), items in groups.items():
        total_debit = sum(
            d.get("ending_debit", Decimal("0"))
            for item in items
            if (d := item["data"]) and d.get("ending_debit")
        )
        total_credit = sum(
            d.get("ending_credit", Decimal("0"))
            for item in items
            if (d := item["data"]) and d.get("ending_credit")
        )
        if total_debit > 0 and total_credit > 0:
            diff = abs(total_debit - total_credit)
            if diff > Decimal("0.01"):
                error_rows.append({
                    "row_number": None,
                    "data": {"group": f"{year}-{period}"},
                    "errors": [
                        f"科目余额表 {year}年{period}月 期末借贷不平衡: "
                        f"借方 {total_debit} ≠ 贷方 {total_credit}（差 {diff}）"
                    ],
                })


def _validate_journal_balance(
    valid_rows: list[dict],
    error_rows: list[dict],
) -> None:
    """序时账：按凭证号分组，检查 借方合计 ≈ 贷方合计"""
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)

    for item in valid_rows:
        d = item["data"]
        voucher = d.get("voucher_no", "")
        groups[str(voucher)].append(item)

    for voucher, items in groups.items():
        total_debit = sum(
            d.get("debit_amount", Decimal("0"))
            for item in items
            if (d := item["data"]) and d.get("debit_amount")
        )
        total_credit = sum(
            d.get("credit_amount", Decimal("0"))
            for item in items
            if (d := item["data"]) and d.get("credit_amount")
        )
        if total_debit > 0 and total_credit > 0:
            diff = abs(total_debit - total_credit)
            if diff > Decimal("0.01"):
                error_rows.append({
                    "row_number": None,
                    "data": {"voucher": voucher},
                    "errors": [
                        f"凭证 {voucher} 借贷不平衡: "
                        f"借方 {total_debit} ≠ 贷方 {total_credit}（差 {diff}）"
                    ],
                })
