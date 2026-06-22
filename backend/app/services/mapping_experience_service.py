"""字段映射经验服务 — 规范化、上下文签名、查找键、歧义判断、推荐与保存"""

import hashlib
import unicodedata
import uuid

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.field_mapping_experience import FieldMappingExperience
from app.services.column_matcher import TYPE_FIELDS


# ── 歧义表头列表 ──────────────────────────────

AMBIGUOUS_HEADERS: set[str] = {
    "借", "借方",
    "贷", "贷方",
    "余额",
    "本期",
    "期初",
    "期末",
    "发生额",
}


# ── 规范化 ────────────────────────────────────

def normalize_header(value: str | None) -> str:
    """标准化表头：NFKC + 去空白 + 去标点 + 小写"""
    if value is None:
        return ""
    text = str(value)
    # Unicode 规范化
    text = unicodedata.normalize("NFKC", text)
    # 去除首尾空白
    text = text.strip()
    # 转小写
    text = text.lower()
    # 去除换行、回车和连续空白
    text = text.replace("\n", "").replace("\r", "").replace("\t", " ")
    import re
    text = re.sub(r"\s+", "", text)
    # 去除常见中英文标点
    punctuation = "()（）[]【】{}：:；;，,。.、/_-—–·．、"
    trans = str.maketrans("", "", punctuation)
    text = text.translate(trans)
    return text


# ── 上下文签名 ────────────────────────────────

def build_context_signature(headers: list[str], column_index: int) -> str:
    """基于前一列+当前列+后一列的标准化表头生成 sha256 上下文签名"""
    normalized = [normalize_header(h) for h in headers]
    prev = normalized[column_index - 1] if column_index > 0 else ""
    curr = normalized[column_index]
    nxt = normalized[column_index + 1] if column_index + 1 < len(normalized) else ""
    raw = f"{prev}|{curr}|{nxt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── 查找键 ────────────────────────────────────

def build_lookup_key(
    company_id: uuid.UUID | None,
    data_type: str,
    software_code: str,
    layout_fingerprint: str,
    source_header_normalized: str,
    context_signature: str,
) -> str:
    """构建经验查找键（不唯一）"""
    cid = str(company_id) if company_id else "_global"
    parts = [
        cid,
        data_type,
        software_code or "",
        layout_fingerprint or "",
        source_header_normalized,
        context_signature,
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


# ── 歧义判断 ──────────────────────────────────

def is_ambiguous_header(normalized_header: str) -> bool:
    """判断标准化表头是否属于歧义表头"""
    return normalized_header in AMBIGUOUS_HEADERS


# ── 推荐 ──────────────────────────────────────

async def recommend_from_experience(
    db: AsyncSession,
    company_id: uuid.UUID | None,
    data_type: str,
    columns: list[dict],
) -> dict[str, dict]:
    """
    从经验库推荐字段映射，按 column_id 返回建议。

    优先级：同客户上下文 > 全局上下文 > 同客户 header-only > 全局 header-only
    """
    from sqlalchemy import select, and_, or_

    suggestions: dict[str, dict] = {}
    headers = [c.get("header", "") for c in columns]

    for c in columns:
        col_id = c["column_id"]
        col_idx = c["index"]
        nh = normalize_header(c.get("header", ""))
        if not nh:
            continue

        ctx = build_context_signature(headers, col_idx)
        ambiguous = is_ambiguous_header(nh)

        # 查询所有匹配经验
        stmt = select(FieldMappingExperience).where(
            and_(
                FieldMappingExperience.data_type == data_type,
                FieldMappingExperience.source_header_normalized == nh,
                FieldMappingExperience.is_active == True,
            )
        )
        result = await db.execute(stmt)
        experiences = result.scalars().all()

        best = _pick_best_experience(experiences, company_id, ctx, nh, ambiguous)
        if best is not None:
            suggestions[col_id] = best

    return suggestions


def _pick_best_experience(
    experiences: list,
    company_id: uuid.UUID | None,
    context_signature: str,
    normalized_header: str,
    ambiguous: bool,
) -> dict | None:
    """从经验列表中选出最佳匹配，按优先级返回"""
    cid_str = str(company_id) if company_id else None
    ambiguous_flag = ambiguous

    # 分级收集
    same_company_ctx = []
    global_ctx = []
    same_company_header = []
    global_header = []

    for exp in experiences:
        exp_cid = str(exp.company_id) if exp.company_id else None
        same_ctx = (exp.context_signature == context_signature)
        same_company = (cid_str is not None and exp_cid == cid_str)

        if same_company and same_ctx:
            same_company_ctx.append(exp)
        elif not same_company and same_ctx:
            global_ctx.append(exp)
        elif same_company and not same_ctx:
            same_company_header.append(exp)
        elif not same_company and not same_ctx:
            global_header.append(exp)

    # 按优先级选择
    target = None
    source = ""
    confidence = 0.0

    if same_company_ctx:
        target = same_company_ctx[0]
        source = "company_experience"
        confidence = 1.0
    elif global_ctx:
        target = global_ctx[0]
        source = "global_experience"
        confidence = 0.9
    elif not ambiguous_flag and same_company_header:
        target = same_company_header[0]
        source = "company_experience"
        confidence = 0.85
    elif not ambiguous_flag and global_header:
        target = global_header[0]
        source = "global_experience"
        confidence = 0.75
    else:
        return None

    return {
        "target_field": target.target_field,
        "source": source,
        "confidence": confidence,
        "experience_id": str(target.id),
    }


# ── 保存 ──────────────────────────────────────

async def save_mapping_experiences(
    db: AsyncSession,
    company_id: uuid.UUID,
    data_type: str,
    columns: list[dict],
    mapping_confirmations: dict,
) -> None:
    """导入成功后保存用户确认的字段映射经验"""
    from sqlalchemy import select, and_

    targets = set(TYPE_FIELDS.get(data_type, []))
    headers = [c.get("header", "") for c in columns]

    for col_id, conf in mapping_confirmations.items():
        target_field = conf.get("target_field", "")
        confirmation_type = conf.get("confirmation_type", "")

        # 过滤规则
        if target_field in ("ignore", "__ignore__", ""):
            continue
        if confirmation_type not in ("user_confirmed", "user_corrected"):
            continue
        if target_field not in targets:
            continue

        # 找到对应列
        col = next((c for c in columns if c["column_id"] == col_id), None)
        if col is None:
            continue

        original_header = col.get("header", "")
        if not original_header:
            continue

        nh = normalize_header(original_header)
        col_idx = col["index"]
        ctx = build_context_signature(headers, col_idx)
        lookup = build_lookup_key(company_id, data_type, "", "", nh, ctx)

        # 查找现有 active 经验
        stmt = select(FieldMappingExperience).where(
            and_(
                FieldMappingExperience.lookup_key == lookup,
                FieldMappingExperience.is_active == True,
            )
        )
        result = await db.execute(stmt)
        existing = result.scalars().all()

        if existing:
            old = existing[0]
            if old.target_field == target_field:
                # 相同目标：累加
                old.use_count += 1
                old.success_count += 1
                old.last_used_at = func.now()
            else:
                # 不同目标：停用旧 + 建新
                old.use_count += 1
                old.conflict_count += 1
                old.is_active = False
                new_exp = FieldMappingExperience(
                    company_id=company_id,
                    data_type=data_type,
                    source_header_original=original_header,
                    source_header_normalized=nh,
                    source_column_index=col_idx,
                    context_signature=ctx,
                    target_field=target_field,
                    confirmation_type=confirmation_type,
                    lookup_key=lookup,
                    use_count=1,
                    success_count=1,
                    conflict_count=0,
                    is_active=True,
                    last_used_at=func.now(),
                )
                db.add(new_exp)
        else:
            # 无历史：新建
            new_exp = FieldMappingExperience(
                company_id=company_id,
                data_type=data_type,
                source_header_original=original_header,
                source_header_normalized=nh,
                source_column_index=col_idx,
                context_signature=ctx,
                target_field=target_field,
                confirmation_type=confirmation_type,
                lookup_key=lookup,
                use_count=1,
                success_count=1,
                conflict_count=0,
                is_active=True,
                last_used_at=func.now(),
            )
            db.add(new_exp)

    await db.flush()
