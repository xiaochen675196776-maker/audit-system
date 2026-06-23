"""客户科目映射经验服务 — 推荐、保存、冲突处理、停用标准科目警告

推荐优先级：
1. 同一客户历史确认：customer_label + client_account_code + client_account_name
2. 全局映射经验：client_account_code + client_account_name（scope=global）
3. 标准科目代码精确匹配 / 名称相似度候选

停用标准科目规则：
- 历史映射指向停用标准科目时，不自动套用，返回为 warning 候选
- warning 中提示用户该标准科目已停用，需重新选择
"""

import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import select, and_, or_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.client_account_mapping import ClientAccountMapping
from app.models.standard_account import StandardAccount


# ── 名称规范化（与字段映射经验库保持一致） ──────────

def _normalize_name(value: str | None) -> str:
    """标准化科目名称：NFKC + 去空白 + 去标点 + 小写"""
    import unicodedata
    import re
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.strip()
    text = text.lower()
    text = text.replace("\n", "").replace("\r", "").replace("\t", " ")
    text = re.sub(r"\s+", "", text)
    punctuation = "()（）[]【】{}：:；;，,。.、/_-—–·．、"
    trans = str.maketrans("", "", punctuation)
    text = text.translate(trans)
    return text


def _similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度 (0-1)"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ── 推荐 ──────────────────────────────────────────

async def recommend_mappings(
    db: AsyncSession,
    data_type: str,
    client_accounts: list[dict],
    customer_label: str | None = None,
    source_label: str | None = None,
) -> list[dict]:
    """
    为客户科目列表推荐标准科目映射。

    参数：
        data_type: 数据类型 (trial_balance / journal / subsidiary)
        client_accounts: [{"client_account_code": "1001", "client_account_name": "现金"}, ...]
        customer_label: 客户标识（被审计单位名称），为 None 时只查全局经验
        source_label: 来源标识（财务软件名称），可选

    返回：
        [{"client_account_code": ..., "client_account_name": ..., "candidates": [...]}]

    每个 candidate：
        standard_account_id, standard_account_code, standard_account_name,
        score (0-1), source, reason, warning
    """
    results: list[dict] = []

    for ca in client_accounts:
        client_code = ca.get("client_account_code", "") or ""
        client_name = ca.get("client_account_name", "") or ""

        entry = {
            "client_account_code": client_code or None,
            "client_account_name": client_name or None,
            "candidates": [],
        }

        if not client_code and not client_name:
            results.append(entry)
            continue

        # ── 优先级 1：同一客户历史确认 ──────────
        if customer_label and client_code:
            company_history = await _query_history_mapping(
                db, data_type, customer_label, "company",
                client_code, client_name,
            )
            for cam in company_history:
                candidate = await _build_candidate(db, cam, "company_history", score=1.0)
                if candidate:
                    entry["candidates"].append(candidate)

        # ── 优先级 2：全局映射经验 ──────────────
        if client_code:
            global_history = await _query_history_mapping(
                db, data_type, None, "global",
                client_code, client_name,
            )
            for cam in global_history:
                # 跳过与 company_history 重复的
                existing_ids = {c.get("standard_account_id") for c in entry["candidates"]}
                if str(cam.standard_account_id) in existing_ids:
                    continue
                candidate = await _build_candidate(db, cam, "global_history", score=0.9)
                if candidate:
                    entry["candidates"].append(candidate)

        # ── 优先级 3a：标准科目代码精确匹配 ────
        if client_code:
            code_matches = await _query_code_match(db, client_code)
            existing_ids = {c.get("standard_account_id") for c in entry["candidates"]}
            for sa in code_matches:
                if str(sa.id) in existing_ids:
                    continue
                candidate = _build_code_match_candidate(sa)
                entry["candidates"].append(candidate)

        # ── 优先级 3b：标准科目名称相似度 ─────
        if client_name:
            name_matches = await _query_name_similarity(db, client_name, threshold=0.6)
            existing_ids = {c.get("standard_account_id") for c in entry["candidates"]}
            for sa, sim in name_matches:
                if str(sa.id) in existing_ids:
                    continue
                candidate = _build_name_similarity_candidate(sa, sim)
                entry["candidates"].append(candidate)

        results.append(entry)

    return results


async def _query_history_mapping(
    db: AsyncSession,
    data_type: str,
    customer_label: str | None,
    scope: str,
    client_code: str,
    client_name: str,
) -> list[ClientAccountMapping]:
    """查询历史映射经验"""
    conditions = [
        ClientAccountMapping.data_type == data_type,
        ClientAccountMapping.is_active == True,
        ClientAccountMapping.scope == scope,
    ]

    if scope == "company":
        conditions.append(ClientAccountMapping.customer_label == customer_label)
    else:
        # global scope: customer_label should be null
        conditions.append(ClientAccountMapping.customer_label == None)

    # 优先按代码匹配，再按名称
    if client_code:
        conditions.append(ClientAccountMapping.client_account_code == client_code)
    elif client_name:
        conditions.append(ClientAccountMapping.client_account_name == client_name)

    stmt = (
        select(ClientAccountMapping)
        .where(and_(*conditions))
        .order_by(desc(ClientAccountMapping.usage_count), desc(ClientAccountMapping.last_used_at))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _query_code_match(db: AsyncSession, client_code: str) -> list[StandardAccount]:
    """查询标准科目代码精确匹配"""
    stmt = select(StandardAccount).where(
        and_(
            StandardAccount.account_code == client_code,
            StandardAccount.is_active == True,
        )
    ).limit(3)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _query_name_similarity(
    db: AsyncSession, client_name: str, threshold: float = 0.6
) -> list[tuple[StandardAccount, float]]:
    """查询标准科目名称相似度（数据库层粗筛后用 Python 精算）"""
    normalized_input = _normalize_name(client_name)
    if not normalized_input or len(normalized_input) < 2:
        return []

    # 获取所有活跃标准科目（第一版不做复杂索引）
    stmt = select(StandardAccount).where(StandardAccount.is_active == True)
    result = await db.execute(stmt)
    all_accounts = list(result.scalars().all())

    matches: list[tuple[StandardAccount, float]] = []
    for sa in all_accounts:
        sim = _similarity(normalized_input, _normalize_name(sa.account_name))
        if sim >= threshold:
            matches.append((sa, sim))

    # 按相似度降序，最多返回 5 个
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches[:5]


async def _build_candidate(
    db: AsyncSession,
    cam: ClientAccountMapping,
    source: str,
    score: float,
) -> dict | None:
    """从映射经验构造候选，检查标准科目是否已停用"""
    sa = None
    if cam.standard_account_id:
        sa_stmt = select(StandardAccount).where(StandardAccount.id == cam.standard_account_id)
        sa_result = await db.execute(sa_stmt)
        sa = sa_result.scalar_one_or_none()

    if sa is None:
        return {
            "standard_account_id": str(cam.standard_account_id) if cam.standard_account_id else None,
            "standard_account_code": cam.standard_account_code_snapshot or "(已删除)",
            "standard_account_name": cam.standard_account_name_snapshot or "(已删除)",
            "score": score,
            "source": source,
            "reason": "历史映射经验（标准科目已不存在）",
            "warning": "标准科目已被删除，请重新选择启用的标准科目",
        }

    if not sa.is_active:
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": score,
            "source": source,
            "reason": f"历史映射经验 → {sa.account_code} {sa.account_name}",
            "warning": f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目",
        }

    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": score,
        "source": source,
        "reason": f"历史映射经验 → {sa.account_code} {sa.account_name}",
        "warning": None,
    }


def _build_code_match_candidate(sa: StandardAccount) -> dict:
    """从代码精确匹配构造候选"""
    assert sa.is_active is True  # _query_code_match 已过滤
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": 0.95,
        "source": "code_match",
        "reason": f"科目代码精确匹配 → {sa.account_code} {sa.account_name}",
        "warning": None,
    }


def _build_name_similarity_candidate(sa: StandardAccount, similarity: float) -> dict:
    """从名称相似度构造候选"""
    score = round(0.7 + (similarity - 0.6) * 0.5, 2)  # 0.6→0.7, 1.0→0.9
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": min(score, 0.92),
        "source": "name_similarity",
        "reason": f"科目名称相似（相似度 {similarity:.0%}）→ {sa.account_code} {sa.account_name}",
        "warning": None if similarity >= 0.85 else f"名称相似度仅 {similarity:.0%}，建议人工确认",
    }


# ── 保存 ──────────────────────────────────────────

async def save_mapping(
    db: AsyncSession,
    data_type: str,
    customer_label: str | None,
    client_account_code: str | None,
    client_account_name: str | None,
    standard_account_id: uuid.UUID,
    standard_account_code: str,
    standard_account_name: str,
    source: str = "user_confirmed",
    confidence: float = 1.0,
    allow_overwrite: bool = False,
) -> dict:
    """
    保存或更新客户科目到标准科目的映射经验。

    参数：
        data_type: 数据类型
        customer_label: 客户标识，None 表示全局经验
        client_account_code: 客户科目代码
        client_account_name: 客户科目名称
        standard_account_id: 标准科目 ID
        standard_account_code: 标准科目代码快照
        standard_account_name: 标准科目名称快照
        source: 来源 (user_confirmed / user_corrected)
        confidence: 置信度 0-1
        allow_overwrite: 是否允许覆盖冲突映射（用户显式确认）

    返回：
        {"status": "created"|"updated"|"conflict", "mapping_id": ..., "conflict_detail": ...}
    """
    scope = "company" if customer_label else "global"
    normalized_name = _normalize_name(client_account_name) if client_account_name else None

    # 查找同客户、同客户科目、同 data_type 的现有 active 映射
    conditions = [
        ClientAccountMapping.data_type == data_type,
        ClientAccountMapping.is_active == True,
    ]

    if scope == "company":
        conditions.append(ClientAccountMapping.customer_label == customer_label)
    else:
        conditions.append(ClientAccountMapping.customer_label == None)

    if client_account_code:
        conditions.append(ClientAccountMapping.client_account_code == client_account_code)
    if client_account_name:
        conditions.append(ClientAccountMapping.client_account_name == client_account_name)

    stmt = select(ClientAccountMapping).where(and_(*conditions))
    result = await db.execute(stmt)
    existing_list = result.scalars().all()

    # 如果没有完全匹配的，尝试只用代码匹配
    if not existing_list and client_account_code:
        conditions_code = [
            ClientAccountMapping.data_type == data_type,
            ClientAccountMapping.is_active == True,
            ClientAccountMapping.client_account_code == client_account_code,
        ]
        if scope == "company":
            conditions_code.append(ClientAccountMapping.customer_label == customer_label)
        else:
            conditions_code.append(ClientAccountMapping.customer_label == None)
        stmt_code = select(ClientAccountMapping).where(and_(*conditions_code))
        result_code = await db.execute(stmt_code)
        existing_list = list(result_code.scalars().all())

    # 检查是否存在冲突（不同标准科目的映射）
    for existing in existing_list:
        if existing.standard_account_id != standard_account_id:
            if not allow_overwrite:
                return {
                    "status": "conflict",
                    "mapping_id": None,
                    "conflict_detail": {
                        "existing_mapping_id": str(existing.id),
                        "existing_standard_account_id": str(existing.standard_account_id) if existing.standard_account_id else None,
                        "existing_standard_account_code": existing.standard_account_code_snapshot,
                        "existing_standard_account_name": existing.standard_account_name_snapshot,
                        "message": (
                            f"客户科目「{client_account_code or '?'} {client_account_name or '?'}」"
                            f"已有映射到「{existing.standard_account_code_snapshot} {existing.standard_account_name_snapshot}」，"
                            f"确认覆盖为「{standard_account_code} {standard_account_name}」？"
                        ),
                    },
                }
            else:
                # 允许覆盖：停用旧映射
                existing.is_active = False
                existing.usage_count = (existing.usage_count or 0) + 1

    # 查找完全相同的映射（相同标准科目）
    same_mapping = None
    for existing in existing_list:
        if existing.standard_account_id == standard_account_id:
            same_mapping = existing
            break

    if same_mapping:
        # 更新相同映射：累加使用计数
        same_mapping.usage_count = (same_mapping.usage_count or 0) + 1
        same_mapping.last_used_at = datetime.now(timezone.utc)
        same_mapping.confidence = max(same_mapping.confidence, confidence)
        await db.flush()
        return {
            "status": "updated",
            "mapping_id": str(same_mapping.id),
            "conflict_detail": None,
        }

    # 新建映射经验
    new_mapping = ClientAccountMapping(
        data_type=data_type,
        customer_label=customer_label,
        source_label=None,
        client_account_code=client_account_code,
        client_account_name=client_account_name,
        normalized_client_account_name=normalized_name,
        standard_account_id=standard_account_id,
        standard_account_code_snapshot=standard_account_code,
        standard_account_name_snapshot=standard_account_name,
        confidence=confidence,
        scope=scope,
        usage_count=0,
        last_used_at=datetime.now(timezone.utc),
        is_active=True,
    )
    db.add(new_mapping)
    await db.flush()

    return {
        "status": "created",
        "mapping_id": str(new_mapping.id),
        "conflict_detail": None,
    }
