"""导入服务 — 整合解析、匹配、校验、批量写入"""

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.file_parser import parse_file, parse_file_info, build_columns
from app.services.column_matcher import auto_match, apply_mapping, map_row, map_row_by_column_ids, TYPE_FIELDS
from app.services.validator import validate_rows
from app.services.template_matcher import match_templates, apply_template_to_columns
from app.services.template_service import get_templates

from app.models.trial_balance import TrialBalance
from app.models.journal_entry import JournalEntry
from app.models.subsidiary_ledger import SubsidiaryLedger
from app.models.import_template import ImportTemplate

# 数据类型 → ORM 模型
MODEL_MAP = {
    "trial_balance": TrialBalance,
    "journal": JournalEntry,
    "subsidiary": SubsidiaryLedger,
}


async def preview_import(
    file_path: str,
    data_type: str,
    db: AsyncSession | None = None,
    template_id: str | None = None,
) -> dict:
    """
    预览导入：解析文件并返回匹配结果，不实际写入数据库。
    """
    from app.services.file_parser import parse_file_with_config

    # 先看是否有模板（用于 parse_config）
    template = None
    if db is not None and template_id is not None:
        from uuid import UUID
        t_list = await get_templates(db)
        t_list = [x for x in t_list if str(x.id) == template_id]
        if t_list:
            template = t_list[0]
            if template.data_type != data_type:
                raise ValueError(f"模板数据类型（{template.data_type}）与本次导入类型（{data_type}）不一致")
            if not template.is_active:
                raise ValueError("指定的模板已停用")

    # 使用模板 parse_config 解析文件
    parse_config = template.parse_config if template else None
    headers, rows = parse_file_with_config(file_path, parse_config)
    columns = build_columns(headers, rows[:5])
    match_result = auto_match(headers, data_type)

    result = {
        "file_name": Path(file_path).name,
        "headers": headers,
        "columns": columns,
        "matched": match_result["matched"],
        "unmatched": match_result["unmatched"],
        "missing": match_result["missing"],
        "preview_rows": rows[:5],
        "row_count": len(rows),
        "data_type": data_type,
    }

    # 模板匹配
    if db is not None:
        if template is not None:
            mapping_v2 = apply_template_to_columns(template, columns)
            result["applied_mapping_v2"] = mapping_v2
            result["applied_template_name"] = template.name
            if template.default_values:
                result["template_default_values"] = template.default_values
        else:
            templates = await get_templates(db, data_type=data_type, is_active=True)
            if templates:
                candidates = match_templates(file_path, data_type, templates)
                result["template_candidates"] = candidates

    return result


async def import_data(
    db: AsyncSession,
    company_id: uuid.UUID,
    file_path: str,
    data_type: str,
    column_mapping: dict[str, str] | None = None,
    column_mapping_v2: dict[str, str] | None = None,
    fiscal_year: int | None = None,
    period: int | None = None,
    parse_config: dict | None = None,
    template_default_values: dict | None = None,
) -> dict:
    """
    完整导入流程。

    parse_config: 模板解析配置，用于指定表头行/数据起始行
    template_default_values: 模板默认值 {fiscal_year, period}，优先级低于用户手动传参
    """
    from app.services.file_parser import parse_file_with_config

    # 1. 解析（使用 parse_config）
    headers, raw_rows = parse_file_with_config(file_path, parse_config)
    columns = build_columns(headers, raw_rows[:3])

    # 合并默认值：模板 < 用户手动
    effective_fiscal_year = fiscal_year
    effective_period = period
    if template_default_values:
        if effective_fiscal_year is None:
            effective_fiscal_year = template_default_values.get("fiscal_year")
        if effective_period is None:
            effective_period = template_default_values.get("period")

    known_fields = set(TYPE_FIELDS.get(data_type, []))
    known_fields.add("company_id")

    def _enrich_row(mapped: dict) -> dict:
        """给一行映射数据补充 company_id / fiscal_year / period / extra_fields"""
        mapped["company_id"] = company_id
        if effective_fiscal_year is not None and "fiscal_year" not in mapped:
            mapped["fiscal_year"] = effective_fiscal_year
        if effective_period is not None and "period" not in mapped:
            mapped["period"] = effective_period

        # 分离非标准字段 → extra_fields JSON
        extra = {}
        for key in list(mapped.keys()):
            if key not in known_fields and mapped[key] is not None and mapped[key] != "":
                extra[key] = mapped.pop(key)
        if extra:
            mapped["extra_fields"] = extra
        return mapped

    # 2. 匹配：v2 优先，然后是旧映射，最后自动匹配
    mapped_rows = []
    if column_mapping_v2 is not None:
        # v2：列 ID → 标准字段
        for row in raw_rows:
            mapped = map_row_by_column_ids(row, columns, column_mapping_v2)
            mapped_rows.append(_enrich_row(mapped))
    elif column_mapping is not None:
        # 旧契约：原始表头 → 标准字段 → 反转为 {标准字段: 原始表头}
        field_to_header = {v: k for k, v in column_mapping.items()}
        for row in raw_rows:
            mapped = map_row(row, headers, field_to_header)
            mapped_rows.append(_enrich_row(mapped))
    else:
        # 自动匹配
        match_result = auto_match(headers, data_type)
        field_to_header = match_result["matched"]
        for row in raw_rows:
            mapped = map_row(row, headers, field_to_header)
            mapped_rows.append(_enrich_row(mapped))

    # 3. 校验
    valid_rows, error_rows = await validate_rows(db, company_id, mapped_rows, data_type)
    total = len(raw_rows)

    # 3.5 入库前最终守卫：确保每一行都有 fiscal_year 和 period
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

    # 4. 批量写入
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
