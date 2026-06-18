"""导入服务 — 整合解析、匹配、校验、批量写入"""

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.file_parser import parse_file, parse_file_info
from app.services.column_matcher import auto_match, apply_mapping, map_row, TYPE_FIELDS
from app.services.validator import validate_rows

from app.models.trial_balance import TrialBalance
from app.models.journal_entry import JournalEntry
from app.models.subsidiary_ledger import SubsidiaryLedger

# 数据类型 → ORM 模型
MODEL_MAP = {
    "trial_balance": TrialBalance,
    "journal": JournalEntry,
    "subsidiary": SubsidiaryLedger,
}


async def preview_import(file_path: str, data_type: str) -> dict:
    """
    预览导入：解析文件并返回匹配结果，不实际写入数据库。

    Returns:
        {
            "file_name": "...",
            "headers": [...],
            "matched": {...},
            "unmatched": [...],
            "missing": [...],
            "preview_rows": [[...], ...],
            "row_count": 1000
        }
    """
    info = parse_file_info(file_path)
    match_result = auto_match(info["headers"], data_type)

    return {
        "file_name": info["file_name"],
        "headers": info["headers"],
        "matched": match_result["matched"],
        "unmatched": match_result["unmatched"],
        "missing": match_result["missing"],
        "preview_rows": info["preview_rows"],
        "row_count": info["row_count"],
        "data_type": data_type,
    }


async def import_data(
    db: AsyncSession,
    company_id: uuid.UUID,
    file_path: str,
    data_type: str,
    column_mapping: dict[str, str] | None = None,
    fiscal_year: int | None = None,
    period: int | None = None,
) -> dict:
    """
    完整导入流程：
    1. 解析文件
    2. 列匹配（自动或使用用户映射）
    3. 数据校验
    4. 批量写入
    5. 返回结果
    """
    # 1. 解析
    headers, raw_rows = parse_file(file_path)

    # 2. 匹配
    if column_mapping is None:
        # 自动匹配：auto_match 返回 {"标准字段": "原始表头"}
        match_result = auto_match(headers, data_type)
        field_to_header = match_result["matched"]
    else:
        # 用户映射：传入 {"原始表头": "标准字段"}，需要反转
        field_to_header = {v: k for k, v in column_mapping.items()}

    # 3. 将原始行转为标准字典
    known_fields = set(TYPE_FIELDS.get(data_type, []))
    known_fields.add("company_id")  # 不是 TYPE_FIELDS 但需要传入模型

    mapped_rows = []
    for row in raw_rows:
        mapped = map_row(row, headers, field_to_header)
        mapped["company_id"] = company_id
        # 手动指定的会计年度/期间（文件中无此列时使用）
        if fiscal_year is not None and "fiscal_year" not in mapped:
            mapped["fiscal_year"] = fiscal_year
        if period is not None and "period" not in mapped:
            mapped["period"] = period

        # 分离非标准字段 → extra_fields JSON
        extra = {}
        for key in list(mapped.keys()):
            if key not in known_fields and mapped[key] is not None and mapped[key] != "":
                extra[key] = mapped.pop(key)
        if extra:
            mapped["extra_fields"] = extra

        mapped_rows.append(mapped)

    # 4. 校验
    valid_rows, error_rows = await validate_rows(db, company_id, mapped_rows, data_type)
    total = len(raw_rows)

    # 4.5 入库前最终守卫：确保每一行都有 fiscal_year 和 period
    # （防止文件无此列且用户未传手动参数时穿透到数据库 NOT NULL 约束）
    _valid_rows_filtered = []
    for item in valid_rows:
        d = item["data"]
        row_errors = []
        if "fiscal_year" not in d or d["fiscal_year"] is None:
            row_errors.append("缺少会计年度（fiscal_year），请在文件中包含该列或通过导入参数手动指定")
        if "period" not in d or d["period"] is None:
            row_errors.append("缺少会计期间（period），请在文件中包含该列或通过导入参数手动指定")
        if row_errors:
            error_rows.append({"row_number": item["row_number"], "data": d, "errors": row_errors})
        else:
            _valid_rows_filtered.append(item)
    valid_rows = _valid_rows_filtered

    # 5. 批量写入
    model_class = MODEL_MAP.get(data_type)
    if model_class is None:
        raise ValueError(f"未知的数据类型: {data_type}")

    success_count = 0
    objects = []
    for item in valid_rows:
        data = item["data"]
        obj = model_class(**data)
        objects.append(obj)

    if objects:
        db.add_all(objects)
        await db.flush()
        success_count = len(objects)

    return {
        "total": total,
        "success": success_count,
        "errors": [
            {"row": e.get("row_number"), "message": "; ".join(e["errors"])}
            for e in error_rows
        ],
        "file_name": Path(file_path).name,
        "data_type": data_type,
    }
