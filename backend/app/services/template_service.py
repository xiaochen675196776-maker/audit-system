"""导入模板服务 — 模板 CRUD + 样本生成 + 模板测试"""

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.import_template import ImportTemplate
from app.services.file_parser import parse_file, build_columns
from app.services.column_matcher import auto_match, TYPE_FIELDS, REQUIRED_FIELDS, match_column


# ── CRUD ──────────────────────────────────────────────

async def get_templates(
    db: AsyncSession,
    data_type: str | None = None,
    is_active: bool | None = None,
) -> list[ImportTemplate]:
    """查询模板列表，按 data_type / is_active 筛选"""
    stmt = select(ImportTemplate)
    if data_type is not None:
        stmt = stmt.where(ImportTemplate.data_type == data_type)
    if is_active is not None:
        stmt = stmt.where(ImportTemplate.is_active == is_active)
    stmt = stmt.order_by(ImportTemplate.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_template(db: AsyncSession, template_id: uuid.UUID) -> ImportTemplate | None:
    """获取单个模板"""
    stmt = select(ImportTemplate).where(ImportTemplate.id == template_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_template(db: AsyncSession, data: dict) -> ImportTemplate:
    """创建模板"""
    template = ImportTemplate(**data)
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


async def update_template(
    db: AsyncSession, template_id: uuid.UUID, data: dict
) -> ImportTemplate | None:
    """更新模板（部分更新）"""
    template = await get_template(db, template_id)
    if template is None:
        return None
    for key, value in data.items():
        if value is not None and hasattr(template, key):
            setattr(template, key, value)
    await db.flush()
    await db.refresh(template)
    return template


async def delete_template(db: AsyncSession, template_id: uuid.UUID) -> bool:
    """删除模板"""
    template = await get_template(db, template_id)
    if template is None:
        return False
    await db.delete(template)
    await db.flush()
    return True


# ── 样本生成 ──────────────────────────────────────────

async def from_sample(file_path: str, data_type: str, template_name: str | None = None) -> dict:
    """从样本文件生成模板草稿（不保存到数据库）"""
    headers, raw_rows = parse_file(file_path)
    columns = build_columns(headers, raw_rows[:3])
    match_result = auto_match(headers, data_type)

    # 构建 header_signature
    header_signature = {}
    for c in columns:
        key = c["column_id"]
        header_signature[key] = c["normalized_header"]

    # 构建 column_rules：按列顺序逐列匹配，处理重复表头
    column_rules = {}
    known_fields = set(TYPE_FIELDS.get(data_type, []))

    # 标准字段 → 是否已分配（防止重复表头覆盖）
    assigned_fields: set[str] = set()

    for c in columns:
        col_id = c["column_id"]
        nh = c["normalized_header"]

        # 尝试将此列匹配到标准字段
        matched_field = None
        for field, header in match_result["matched"].items():
            if field in assigned_fields:
                continue  # 该标准字段已分配到前面的列
            # 检查原始表头或规范化表头是否匹配
            if c["header"] == header or nh == header.strip():
                matched_field = field
                break

        if matched_field is not None:
            column_rules[col_id] = matched_field
            assigned_fields.add(matched_field)
        else:
            # 辅助字段
            if nh:
                extra_name = _sanitize_extra_field_name(nh, len(assigned_fields) + 1)
            else:
                extra_name = f"custom_{len(assigned_fields) + 1}"
            column_rules[col_id] = extra_name

    # 未匹配的列（在 columns 中不存在但 auto_match 匹配了）→ 不处理

    return {
        "name": template_name or f"{data_type}_模板_{Path(file_path).stem}",
        "data_type": data_type,
        "source_label": None,
        "is_active": False,
        "header_signature": header_signature,
        "parse_config": {"header_row": 0, "data_start_row": 1, "encoding": "auto"},
        "column_rules": column_rules,
        "default_values": {},
        "matched_count": len(match_result["matched"]),
        "unmatched_count": len(match_result["unmatched"]),
        "missing_count": len(match_result["missing"]),
    }


def _sanitize_extra_field_name(header: str, idx: int) -> str:
    """将表头转为合法的辅助字段名（拼音/缩写）"""
    # 简单策略：取前 20 个字符 + 索引防冲突
    clean = header.strip().replace(" ", "_").replace("（", "").replace("）", "")
    clean = clean.replace("(", "").replace(")", "").replace("，", "").replace("。", "")
    if len(clean) > 20:
        clean = clean[:20]
    return f"field_{clean}_{idx}" if clean else f"custom_{idx}"


# ── 模板测试 ──────────────────────────────────────────

async def test_template(template: ImportTemplate, file_path: str) -> dict:
    """用文件测试模板，返回套用结果（含签名校验 + parse_config 生效）"""
    from app.services.file_parser import parse_file_with_config

    parse_config = template.parse_config or {}
    headers, raw_rows = parse_file_with_config(file_path, parse_config)
    columns = build_columns(headers, raw_rows[:3])

    targets = set(TYPE_FIELDS.get(template.data_type, []))
    required = set(REQUIRED_FIELDS.get(template.data_type, []))

    column_rules = template.column_rules or {}
    hit_fields = []
    missing_fields = []
    warnings = []
    column_mapping_v2: dict[str, str] = {}

    # ── 签名安全校验 ──
    from app.services.template_matcher import _check_signature_match, SIGNATURE_SAFE_THRESHOLD
    sig = template.header_signature or {}
    sig_ratio, sig_matched, sig_mismatches = _check_signature_match(sig, columns)

    if sig and sig_ratio < SIGNATURE_SAFE_THRESHOLD:
        # 签名不匹配 → 拒绝
        applicable = False
        message = (
            f"模板「{template.name}」与当前文件表头不匹配"
            f"（相似度 {int(sig_ratio * 100)}%），无法安全套用。"
        )
        if sig_mismatches:
            message += f" {'；'.join(sig_mismatches[:3])}"
        return {
            "applicable": applicable,
            "hit_fields": [],
            "missing_fields": list(targets),
            "warnings": [message],
            "column_mapping_v2": {},
            "message": message,
        }

    # 标准字段 → 是否已映射
    mapped_fields: set[str] = set()
    for col_id, rule in column_rules.items():
        if rule == "ignore" or not rule:
            continue
        if rule in targets:
            mapped_fields.add(rule)
            column_mapping_v2[col_id] = rule
            hit_fields.append(rule)
        else:
            column_mapping_v2[col_id] = rule
            hit_fields.append(rule)

    # 缺失的标准字段
    for f in targets:
        if f not in mapped_fields:
            missing_fields.append(f)

    # 必填字段缺失 → 警告
    for f in required:
        if f not in mapped_fields:
            warnings.append(f"必填字段「{f}」未在模板中映射，导入时需手动补充")

    # 重复表头警告
    dup_counts: dict[str, int] = {}
    for c in columns:
        nh = c["normalized_header"]
        if nh:
            dup_counts[nh] = dup_counts.get(nh, 0) + 1
    for nh, count in dup_counts.items():
        if count > 1:
            warnings.append(f"表头「{nh}」出现 {count} 次，模板将使用列 ID 区分，不受重复影响")

    applicable = len(hit_fields) > 0
    message = _build_test_message(applicable, len(hit_fields), len(missing_fields), warnings)

    return {
        "applicable": applicable,
        "hit_fields": hit_fields,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "column_mapping_v2": column_mapping_v2,
        "message": message,
    }


def _build_test_message(
    applicable: bool, hit: int, missing: int, warnings: list[str]
) -> str:
    """生成测试结果的中文消息"""
    parts = []
    if applicable:
        parts.append(f"✓ 模板可套用，命中 {hit} 个字段")
    else:
        parts.append("✗ 模板不可套用，未命中任何标准字段")
    if missing > 0:
        parts.append(f"缺失 {missing} 个标准字段")
    if warnings:
        # 只取前两条警告写入消息
        parts.append("; ".join(warnings[:2]))
    return "。".join(parts) + "。" if parts else "无匹配字段。"
