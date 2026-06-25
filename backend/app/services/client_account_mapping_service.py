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
import re
import unicodedata

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_account_mapping import ClientAccountMapping
from app.models.standard_account import StandardAccount


# ── 名称规范化（与字段映射经验库保持一致） ──────────

def _normalize_name(value: str | None) -> str:
    """标准化科目名称：NFKC + 去空白 + 去标点 + 小写"""
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


def _normalize_code(value: str | int | float | None) -> str:
    """标准化科目代码：NFKC + 去空白/分隔符 + 文本型整数数字归一。"""
    if value is None:
        return ""

    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return ""

    text = re.sub(r"\s+", "", text)

    numeric_text = text.replace(",", "").replace("，", "")
    if re.fullmatch(r"\+?\d+(?:\.0+)?", numeric_text):
        return numeric_text.split(".", 1)[0].lstrip("+")

    text = re.sub(r"[\s_\-—–./\\:：;；,，|·．、]+", "", text)
    return text.casefold()


# 标准科目名称常见的显示前缀，匹配前需剥离以便与客户科目名称对齐。
# 例如「减：研发费用」→「研发费用」、「其中：利息费用」→「利息费用」。
_STANDARD_NAME_DISPLAY_PREFIXES = ("减：", "减:", "减", "加：", "加:", "其中：", "其中", "加", "减：".replace("：", ""))


def _canonical_name(value: str | None) -> str:
    """科目名称规范化（用于匹配）：

    - NFKC + 小写
    - 去空白与标点/分隔符（与 _normalize_name 一致）
    - 剥离标准科目的显示前缀：减：/减:/减/加：/加:/其中：/其中
      例如「减：研发费用」→「研发费用」

    客户科目名称一般不带这些前缀，剥离后可让「研发费用」精确命中「减：研发费用」。
    """
    if value is None:
        return ""
    text = _normalize_name(value)
    if not text:
        return ""
    # 反复剥离前缀（处理「减：其中：xxx」之类的叠加，虽然罕见）
    changed = True
    while changed:
        changed = False
        for pfx in _STANDARD_NAME_DISPLAY_PREFIXES:
            if pfx and text.startswith(pfx):
                text = text[len(pfx):]
                changed = True
    return text



def _similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度 (0-1)"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ── 名称锚点（核心科目关键词 → 标准科目名称片段） ────
# 用于从客户明细科目名称中识别核心科目锚点，例如
# 「银行存款_活期户_招商银行沌口支行0801」→ 锚点「银行存款」
# 「财务费用_利息收入」→ 锚点「财务费用」
# 按从长到短排序，保证更具体的锚点优先命中（如「应收账款」优先于「账款」）。
_NAME_ANCHORS: list[str] = [
    "银行存款", "库存现金", "其他货币资金",
    "应收账款", "预付账款", "应收票据", "其他应收款",
    "应付账款", "预收账款", "应付票据", "其他应付款",
    "原材料", "库存商品", "固定资产", "无形资产", "工程物资",
    "短期借款", "长期借款", "应付职工薪酬",
    "实收资本", "资本公积", "盈余公积", "未分配利润",
    "主营业务收入", "其他业务收入", "营业外收入",
    "主营业务成本", "其他业务成本", "营业外支出",
    "管理费用", "销售费用", "财务费用",
    "研发支出_资本化支出", "研发支出_费用化支出", "研发支出", "研发费用",
    "所得税费用", "资产减值损失", "信用减值损失",
    "营业税金及附加", "税金及附加",
    "递延收益", "生产成本", "制造费用",
    "投资收益", "其他收益",
    # TASK-078：补充金融/权益工具相关科目锚点
    "其他权益工具投资", "合同履约成本", "存货跌价准备",
]

# ── 语义别名组（客户代码体系与标准不一致时按经济含义匹配） ──
# 每组定义:
#   canonical: 标准科目 canon 名称
#   client_aliases: 客户科目名称中可能出现的别名
#   standard_aliases: 标准科目 canonical name 应包含的关键词（用于命中）
#   negative_aliases: 不应碰到的反义词（用于冲突拒绝）
_SEMANTIC_ACCOUNT_GROUPS: dict[str, dict] = {
    "prepayments": {
        "canonical": "预付款项",
        "client_aliases": ["预付账款", "预付款", "预付款项", "预付材料款", "预付机物料款"],
        "standard_aliases": ["预付款项", "预付账款"],
        "negative_aliases": ["应收款项融资", "应收账款", "其他应收款"],
    },
    "accumulated_depreciation": {
        "canonical": "累计折旧",
        "client_aliases": ["累计折旧", "固定资产累计折旧"],
        "standard_aliases": ["固定资产累计折旧", "累计折旧"],
        "negative_aliases": ["固定资产原值", "固定资产-原值"],
    },
    "construction_in_progress": {
        "canonical": "在建工程",
        "client_aliases": ["在建工程", "在安装设备", "工程项目", "装修费用"],
        "standard_aliases": ["在建工程", "在建工程原值", "在建工程-原值"],
        "negative_aliases": ["在建工程减值准备", "在建工程-减值准备"],
    },
    "other_receivables": {
        "canonical": "其他应收款",
        "client_aliases": ["其他应收款", "备用金", "押金保证金", "保证金"],
        "standard_aliases": ["其他应收款"],
        "negative_aliases": ["应收账款", "应收款项"],
    },
    "other_payables": {
        "canonical": "其他应付款",
        "client_aliases": ["其他应付款", "应付暂估", "应付其他"],
        "standard_aliases": ["其他应付款"],
        "negative_aliases": ["应付账款"],
    },
    "tax_payable": {
        "canonical": "应交税费",
        "client_aliases": ["应交税费", "应交税金", "应交增值税", "应交所得税", "应交城建税"],
        "standard_aliases": ["应交税费", "应交税金"],
        "negative_aliases": [],
    },
    "advance_receipts": {
        "canonical": "预收款项",
        "client_aliases": ["预收账款", "预收款项", "预收款"],
        "standard_aliases": ["预收款项", "预收账款", "合同负债"],
        "negative_aliases": ["应收账款", "预付款项"],
    },
    "long_term_prepaid_expense": {
        "canonical": "长期待摊费用",
        "client_aliases": ["长期待摊费用", "长期待摊", "待摊费用"],
        "standard_aliases": ["长期待摊费用"],
        "negative_aliases": [],
    },
    "intangible_amortization": {
        "canonical": "无形资产累计摊销",
        "client_aliases": ["无形资产累计摊销", "累计摊销", "无形资产摊销"],
        "standard_aliases": ["无形资产累计摊销", "无形资产-累计摊销", "累计摊销"],
        "negative_aliases": ["无形资产原值", "无形资产-原值"],
    },
    "deferred_income": {
        "canonical": "递延收益",
        "client_aliases": ["递延收益", "与资产相关的递延收益", "与收益相关的递延收益"],
        "standard_aliases": ["递延收益"],
        "negative_aliases": [],
    },
    "production_cost": {
        "canonical": "生产成本",
        "client_aliases": ["生产成本", "基本生产成本", "直接材料", "直接人工", "直接动力", "委外加工费", "委外物资"],
        "standard_aliases": ["生产成本"],
        "negative_aliases": ["农业生产成本", "主营业务成本", "主营业务收入", "应付职工薪酬"],
    },
    "manufacturing_overhead": {
        "canonical": "制造费用",
        "client_aliases": ["制造费用"],
        "standard_aliases": ["制造费用"],
        "negative_aliases": ["应付职工薪酬", "管理费用", "销售费用", "研发费用"],
    },
    "research_expense": {
        "canonical": "研发费用",
        "client_aliases": ["研发费用"],
        "standard_aliases": ["研发费用"],
        "negative_aliases": ["开发支出", "研发支出", "资本化支出", "费用化支出", "油气开发支出", "应付职工薪酬"],
    },
    "rd_capitalized_development": {
        "canonical": "研发支出-资本化支出",
        "client_aliases": ["研发支出_资本化支出", "研发支出-资本化支出", "资本化支出"],
        "standard_aliases": ["研发支出-资本化支出", "研发支出资本化支出"],
        "negative_aliases": ["费用化支出", "研发费用"],
    },
    "rd_expensed_development": {
        "canonical": "研发支出-费用化支出",
        "client_aliases": ["研发支出_费用化支出", "研发支出-费用化支出", "费用化支出"],
        "standard_aliases": ["研发支出-费用化支出", "研发支出费用化支出"],
        "negative_aliases": ["资本化支出", "研发费用"],
    },
    "development_expenditure": {
        "canonical": "开发支出",
        "client_aliases": ["开发支出"],
        "standard_aliases": ["开发支出"],
        "negative_aliases": ["研发费用", "油气开发支出"],
    },
    "investment_income": {
        "canonical": "投资收益",
        "client_aliases": ["投资收益", "交易性金融资产收益"],
        "standard_aliases": ["投资收益"],
        "negative_aliases": ["交易性金融资产", "其他收益"],
    },
    "other_income": {
        "canonical": "其他收益",
        "client_aliases": ["其他收益"],
        "standard_aliases": ["其他收益"],
        "negative_aliases": ["其他综合收益", "其他应收款", "其他权益工具", "投资收益"],
    },
    "fixed_assets": {
        "canonical": "固定资产",
        "client_aliases": ["固定资产"],
        "standard_aliases": ["固定资产", "固定资产原值", "固定资产-原值"],
        "negative_aliases": ["固定资产累计折旧", "固定资产-累计折旧", "固定资产减值准备"],
    },
    "intangible_assets": {
        "canonical": "无形资产",
        "client_aliases": ["无形资产"],
        "standard_aliases": ["无形资产", "无形资产原值", "无形资产-原值"],
        "negative_aliases": ["无形资产累计摊销", "无形资产-累计摊销", "无形资产减值准备"],
    },
    "paid_in_capital": {
        "canonical": "实收资本",
        "client_aliases": ["实收资本"],
        "standard_aliases": ["实收资本"],
        "negative_aliases": ["资本公积"],
    },
}


def _split_name_tokens(name: str) -> list[str]:
    """按 _ - / 空格 括号等分隔符拆分科目名称片段"""
    if not name:
        return []
    text = unicodedata.normalize("NFKC", str(name))
    # 把常见分隔符统一成分隔空格
    text = re.sub(r"[_\-—–/\\|·．、:：;；,，()（）\[\]【】{}\s]+", " ", text)
    return [t.strip() for t in text.split(" ") if t.strip()]


def _detect_name_anchor(name: str) -> str | None:
    """从客户科目名称中识别核心科目锚点，返回最长的命中锚点（规范化前的中文原文）。"""
    if not name:
        return None
    # 先在完整名称里直接查找子串（处理「银行存款_活期户_...」整体作为一段的情况）
    full = str(name)
    # 优先匹配最长的锚点
    for anchor in _NAME_ANCHORS:
        if anchor in full:
            return anchor
    # 再按分隔符拆分后逐片段匹配
    tokens = _split_name_tokens(full)
    for anchor in _NAME_ANCHORS:
        for token in tokens:
            if anchor in token:
                return anchor
    return None



# ── 语义别名匹配 ──────────────────────────────────

def _detect_semantic_group(client_name: str | None) -> str | None:
    """从客户科目名称中识别语义组 key，返回第一个命中组的 key 或 None。

    优先级：
    1. 多段名称语义分流（研发支出_费用化支出 vs 研发支出_资本化支出）
    2. 根科目优先（如「生产成本_*」→ production_cost）
    3. 全名 alias 扫描（兼容 TASK-064 已有规则）
    """
    if not client_name:
        return None
    norm = _normalize_name(client_name)
    if not norm:
        return None

    tokens = _split_name_tokens(client_name)
    first = tokens[0] if tokens else str(client_name)
    first_norm = _normalize_name(first)
    all_token_norms = [_normalize_name(t) for t in tokens]

    # ── 优先级 1：多段名称语义分流 ──
    # 研发支出_费用化支出 → rd_expensed_development (170402)；研发支出_资本化支出 → rd_capitalized_development (170401)
    if first_norm == _normalize_name("研发支出"):
        expensed = _normalize_name("费用化支出")
        capitalized = _normalize_name("资本化支出")
        if expensed in all_token_norms or expensed in norm:
            return "rd_expensed_development"
        if capitalized in all_token_norms or capitalized in norm:
            return "rd_capitalized_development"

    # 投资收益明细 → investment_income
    if first_norm == _normalize_name("投资收益"):
        return "investment_income"

    # 其他收益 → other_income
    if first_norm == _normalize_name("其他收益"):
        return "other_income"

    # ── 优先级 2：根科目优先 ──
    root_priority = [
        ("deferred_income", ["递延收益"]),
        ("production_cost", ["生产成本"]),
        ("manufacturing_overhead", ["制造费用"]),
        ("fixed_assets", ["固定资产"]),
        ("intangible_assets", ["无形资产"]),
        ("paid_in_capital", ["实收资本"]),
    ]
    for group_key, aliases in root_priority:
        for alias in aliases:
            if _normalize_name(alias) in first_norm:
                return group_key

    # ── 优先级 3：回退全名 alias 扫描 ──
    for group_key, group_def in _SEMANTIC_ACCOUNT_GROUPS.items():
        for alias in group_def.get("client_aliases", []):
            alias_norm = _normalize_name(alias)
            if alias_norm and alias_norm in norm:
                return group_key
    return None


def _standard_account_matches_semantic_group(sa: StandardAccount, group_key: str) -> bool:
    """检查标准科目是否命中指定语义组（启用科目 + canonical name 匹配 standard_aliases）。"""
    if not sa.is_active:
        return False
    group_def = _SEMANTIC_ACCOUNT_GROUPS.get(group_key)
    if not group_def:
        return False
    sa_canonical = _canonical_name(sa.account_name)
    if not sa_canonical:
        return False
    for alias in group_def.get("standard_aliases", []):
        alias_norm = _normalize_name(alias)
        if alias_norm and alias_norm in sa_canonical:
            return True
    return False


def _standard_account_conflicts_semantic_group(sa: StandardAccount, group_key: str) -> bool:
    """检查标准科目是否命中语义组的 negative_aliases（冲突拒绝）。"""
    group_def = _SEMANTIC_ACCOUNT_GROUPS.get(group_key)
    if not group_def:
        return False
    sa_canonical = _canonical_name(sa.account_name)
    if not sa_canonical:
        return False
    for alias in group_def.get("negative_aliases", []):
        alias_norm = _normalize_name(alias)
        if alias_norm and alias_norm in sa_canonical:
            return True
    return False


async def _query_semantic_alias_match(
    db: AsyncSession,
    group_key: str,
) -> list[StandardAccount]:
    """在标准科目表中查询命中语义组 standard_aliases 的启用科目。"""
    group_def = _SEMANTIC_ACCOUNT_GROUPS.get(group_key)
    if not group_def:
        return []
    # 查询所有启用标准科目，按名称 canonical 匹配
    stmt = select(StandardAccount).where(StandardAccount.is_active == True)
    result = await db.execute(stmt)
    all_active = result.scalars().all()

    matches: list[StandardAccount] = []
    conflicts: list[StandardAccount] = []
    for sa in all_active:
        if _standard_account_matches_semantic_group(sa, group_key):
            # 额外检查不冲突
            if not _standard_account_conflicts_semantic_group(sa, group_key):
                matches.append(sa)
            else:
                conflicts.append(sa)

    # 优先级：名称完全等价 > 名称包含
    def _sort_key(sa: StandardAccount) -> tuple[int, int]:
        canonical = _normalize_name(group_def.get("canonical", ""))
        sa_canonical = _canonical_name(sa.account_name)
        # exact match first
        exact = 0 if canonical and canonical == sa_canonical else 1
        # shorter name (more generic) preferred
        length = len(sa_canonical)
        return (exact, length)

    matches.sort(key=_sort_key)
    return matches


def _build_semantic_alias_candidate(
    sa: StandardAccount,
    group_key: str,
    client_name: str,
) -> dict:
    """从语义别名匹配构造安全候选。"""
    group_def = _SEMANTIC_ACCOUNT_GROUPS.get(group_key, {})
    canonical = group_def.get("canonical", group_key)
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": 0.93,
        "source": "semantic_alias",
        "reason": f"语义别名匹配：客户「{client_name}」≈ 标准「{canonical}」",
        "warning": None,
    }


def _history_name_value(cam: ClientAccountMapping) -> str:
    """取历史映射的规范化客户科目名称，兼容旧数据未填 normalized 字段。"""
    return cam.normalized_client_account_name or _normalize_name(cam.client_account_name)


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
        normalized_client_code = _normalize_code(client_code)
        normalized_client_name = _normalize_name(client_name)

        entry = {
            "client_account_code": client_code or None,
            "client_account_name": client_name or None,
            "candidates": [],
        }

        if not client_code and not client_name:
            results.append(entry)
            continue

        # ── 优先级 1：同一客户历史确认 ──────────
        if customer_label and (normalized_client_code or normalized_client_name):
            company_history = await _query_history_mapping(
                db, data_type, customer_label, "company",
                client_code, client_name,
            )
            for cam in company_history:
                candidate = await _build_candidate(db, cam, "company_history", score=1.0)
                if candidate:
                    entry["candidates"].append(candidate)

        # ── 优先级 2：全局映射经验 ──────────────
        if normalized_client_code or normalized_client_name:
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
        if normalized_client_code:
            code_matches = await _query_code_match(db, client_code)
            existing_ids = {c.get("standard_account_id") for c in entry["candidates"]}
            for sa in code_matches:
                if str(sa.id) in existing_ids:
                    continue
                candidate = _build_code_match_candidate(sa, client_name)
                entry["candidates"].append(candidate)

        # ── 优先级 3b：标准科目名称精确匹配 ────
        if normalized_client_name:
            name_exact_matches = await _query_name_exact_match(db, client_name)
            existing_ids = {c.get("standard_account_id") for c in entry["candidates"]}
            for sa in name_exact_matches:
                if str(sa.id) in existing_ids:
                    continue
                candidate = _build_name_exact_candidate(sa)
                entry["candidates"].append(candidate)

        # ── 优先级 3c：语义别名匹配 ──
        # 客户科目名称命中语义别名组时，按经济含义匹配标准科目（代码可不一致）。
        # 放在代码精确匹配之后、弱相似度之前，安全语义候选优先于兜底前缀/锚点。
        if normalized_client_name:
            group_key = _detect_semantic_group(client_name)
            if group_key:
                semantic_matches = await _query_semantic_alias_match(db, group_key)
                existing_ids = {c.get("standard_account_id") for c in entry["candidates"]}
                for sa in semantic_matches:
                    if str(sa.id) in existing_ids:
                        continue
                    candidate = _build_semantic_alias_candidate(sa, group_key, client_name)
                    entry["candidates"].append(candidate)

        # ── 优先级 3d：标准科目名称相似度 ─────
        if normalized_client_name:
            name_matches = await _query_name_similarity(db, client_name, threshold=0.6)
            existing_ids = {c.get("standard_account_id") for c in entry["candidates"]}
            for sa, sim in name_matches:
                if str(sa.id) in existing_ids:
                    continue
                candidate = _build_name_similarity_candidate(sa, sim)
                entry["candidates"].append(candidate)

        # ── 优先级 4a：客户明细代码最长标准科目前缀（父级） ──
        # 客户明细科目代码（如 10020108）没有精确匹配时，按最长标准科目代码前缀
        # 匹配到上级标准科目（如 1002 银行存款）。这是兜底候选，带 warning 不自动确认。
        # 兜底候选优先于普通 name_similarity 候选（替换弱相似候选，保留精确/历史候选）。
        if normalized_client_code:
            prefix_match = await _query_code_prefix_parent(db, client_code)
            for sa in prefix_match:
                _add_fallback_candidate(
                    entry, _build_code_prefix_parent_candidate(sa, client_code, client_name, ca)
                )

        # ── 优先级 4b：代码类别锚点（客户代码体系与标准不一致时） ──
        # 客户用 6604 表示研发费用，但标准科目库无 6604，只有「660201 减：研发费用」时，
        # 按 6604→研发费用 的类别锚点去标准科目表按名称匹配。兜底候选，带 warning 不自动确认。
        if normalized_client_code:
            category_matches = await _query_code_category_anchor(db, client_code)
            for sa in category_matches:
                _add_fallback_candidate(
                    entry, _build_code_category_anchor_candidate(sa, client_code, client_name, ca)
                )

        # ── 优先级 4c：名称锚点匹配 ──
        # 客户明细科目名称包含核心科目锚点（如「银行存款_活期户_...」含「银行存款」）
        # 时，匹配到名称（剥离显示前缀后）等于/包含该锚点的标准科目。
        # 兜底候选，带 warning 不自动确认。
        if normalized_client_name:
            anchor = _detect_name_anchor(client_name)
            if anchor:
                anchor_matches = await _query_name_anchor_match(db, anchor)
                for sa in anchor_matches:
                    _add_fallback_candidate(
                        entry, _build_name_anchor_candidate(sa, anchor, client_name, ca)
                    )

        # ── 优先级 3 冲突收口：exact code 命中父级、exact/前缀 name 命中更具体子级 ──
        # 当客户代码精确命中标准父级（code_match），但客户名称精确/首段命中另一更精确
        # 标准子级科目时，名称强语义命中应优先；原 code_match 必须降级为
        # code_match_conflict（warning 非空、score<0.9），不得作为安全自动确认候选。
        # 详见 TASK-068 / TASK-070。
        if normalized_client_name:
            await _resolve_exact_code_vs_exact_name_conflict(db, entry, client_name)

        # ── 统一候选排序（TASK-077）：所有候选构造、冲突降级、兜底补充完成后，
        # 用 _sort_candidates 重排，保证安全候选（warning is None 且 score >= 0.9）
        # 始终排在所有 warning/低分候选前。否则 code_match_conflict 等带 warning 候选
        # 仍可能因加入顺序靠前而被自动确认盲取 candidates[0] 错导入。
        entry["candidates"] = _sort_candidates(entry["candidates"])

        # 兜底候选去重后可能仍较多，限制最多 10 个（保留已加入的顺序：高优先级在前）
        if len(entry["candidates"]) > 10:
            entry["candidates"] = entry["candidates"][:10]

        results.append(entry)

    return results


# 兜底候选（code_prefix_parent / code_category_anchor / name_anchor）可替换的弱候选来源
_FALLBACK_REPLACEABLE_SOURCES = {"name_similarity"}
# 兜底候选来源集合：不同兜底来源指向同一标准科目时允许共存
_FALLBACK_SOURCES = {"code_prefix_parent", "code_category_anchor", "name_anchor"}


def _add_fallback_candidate(entry: dict, candidate: dict) -> None:
    """添加兜底候选（前缀/锚点）。

    规则：
    - 若已存在指向同一标准科目的「高优先级」候选（历史/精确代码/精确名称），则跳过。
    - 若仅存在指向同一标准科目的弱候选（name_similarity），则用更有语义的兜底候选替换它。
    - 不同兜底来源（如前缀 + 锚点）指向同一标准科目时，允许共存，提供更丰富依据。
    """
    sa_id = candidate.get("standard_account_id")
    candidates = entry["candidates"]

    for idx, existing in enumerate(candidates):
        if existing.get("standard_account_id") != sa_id:
            continue
        existing_source = existing.get("source")
        # 已有同标准科目的兜底候选（不同来源）：共存
        if existing_source in _FALLBACK_SOURCES and existing_source != candidate.get("source"):
            candidates.append(candidate)
            return
        # 已有弱相似候选：替换为更有语义的兜底候选
        if existing_source in _FALLBACK_REPLACEABLE_SOURCES:
            candidates[idx] = candidate
            return
        # 已有高优先级候选（历史/精确），跳过兜底
        return

    # 无重复，直接追加
    candidates.append(candidate)


# ── TASK-068 / TASK-070：exact code vs name 冲突收口 ───
# source 优先级权重，用于冲突收口后的候选重排。
# 遵循既有优先级：company_history > global_history > 安全 code_match/name_exact/name_prefix
# > semantic_alias/name_anchor > 兜底/warning 候选。
_CANDIDATE_SOURCE_PRIORITY: dict[str, int] = {
    "company_history": 0,
    "global_history": 1,
    "code_match": 2,
    "name_exact": 2,
    "name_prefix": 2,
    "semantic_alias": 3,
    "code_prefix_parent": 4,
    "name_anchor": 4,
    "code_category_anchor": 4,
    "name_similarity": 5,
    "code_match_conflict": 6,
    "history_conflict": 6,
}


def _candidate_priority(c: dict) -> tuple[int, float]:
    """候选排序键：先按来源优先级，再按 score 降序（负值升序）。"""
    source = c.get("source", "")
    return (_CANDIDATE_SOURCE_PRIORITY.get(source, 9), -float(c.get("score", 0) or 0))


# 安全候选阈值：warning 为空且 score >= 该值视为「可自动确认安全候选」。
_SAFE_CANDIDATE_MIN_SCORE = 0.9


def _is_safe_candidate(c: dict) -> bool:
    """判定是否为安全候选：warning 为空且 score >= 0.9。"""
    if c.get("warning"):
        return False
    try:
        return float(c.get("score", 0) or 0) >= _SAFE_CANDIDATE_MIN_SCORE
    except (TypeError, ValueError):
        return False


def _sort_candidates(candidates: list[dict]) -> list[dict]:
    """统一候选排序：安全候选必须排在所有非安全候选前。

    规则（TASK-077）：
    1. 先按「是否安全候选」分区：safe（warning is None 且 score >= 0.9）在前，
       non-safe（warning 非空或 score < 0.9）在后。
    2. 安全候选内部按既有来源优先级排序，再按 score 降序。
    3. 非安全候选内部同样按来源优先级、score 降序，但整体排在安全候选之后。

    这样无论 code_match_conflict 由 _build_code_match_candidate 直接产生还是由
    _resolve_exact_code_vs_exact_name_conflict 降级产生，只要有安全候选，安全候选
    永远排在 candidates[0]，避免自动确认盲取 warning 首项导致的错导入。
    """
    safe = [c for c in candidates if _is_safe_candidate(c)]
    non_safe = [c for c in candidates if not _is_safe_candidate(c)]
    safe.sort(key=_candidate_priority)
    non_safe.sort(key=_candidate_priority)
    return safe + non_safe


def _pick_auto_confirm_candidate(candidates: list[dict]) -> dict | None:
    """自动选中推荐候选：优先取第一条安全候选；无安全候选时回退到首项。

    供后端导入链路使用，避免盲取 candidates[0] 命中 warning 候选。
    """
    if not candidates:
        return None
    safe = next((c for c in candidates if _is_safe_candidate(c)), None)
    return safe if safe is not None else candidates[0]


def _resolve_exact_code_vs_exact_name_conflict_sync(entry: dict, strong_name: dict) -> bool:
    """同步收口：把与「名称强语义」候选指向不同标准科目的 code_match 降级为
    code_match_conflict。返回是否发生降级。"""
    candidates = entry["candidates"]
    best_name_id = strong_name.get("standard_account_id")
    code_candidates = [c for c in candidates if c.get("source") == "code_match"]
    if not code_candidates:
        return False

    conflicted = False
    for code_candidate in code_candidates:
        if code_candidate.get("standard_account_id") == best_name_id:
            # 代码与名称指向同一标准科目：不冲突，保持安全 code_match
            continue
        # 代码命中与名称强语义命中指向不同标准科目 → 降级 code_match
        code_candidate["source"] = "code_match_conflict"
        code_candidate["score"] = min(float(code_candidate.get("score", 0.75) or 0.75), 0.75)
        code_candidate["reason"] = (
            f"代码相同但名称更精确匹配标准科目「{strong_name.get('standard_account_code')} "
            f"{strong_name.get('standard_account_name')}」→ {code_candidate.get('standard_account_code')} "
            f"{code_candidate.get('standard_account_name')}"
        )
        code_candidate["warning"] = (
            f"代码相同但名称不一致：客户科目名称更精确匹配标准科目"
            f"「{strong_name.get('standard_account_code')} {strong_name.get('standard_account_name')}」，"
            f"不应自动归入「{code_candidate.get('standard_account_code')} {code_candidate.get('standard_account_name')}」，请人工确认"
        )
        conflicted = True
    return conflicted


def _pick_exact_strong_name_candidate(
    candidates: list[dict],
    client_name: str,
) -> dict | None:
    """从候选中挑选 name_exact 强名称候选（规范化标准名称 == 规范化客户名称）。

    返回该候选或 None。name_prefix 由 _query_name_prefix_match 按需在冲突收口中查询。
    """
    norm_client = _normalize_name(client_name)
    if not norm_client:
        return None
    for nc in candidates:
        if nc.get("source") != "name_exact":
            continue
        if _normalize_name(nc.get("standard_account_name", "")) == norm_client:
            return nc
    return None


async def _resolve_exact_code_vs_exact_name_conflict(
    db: AsyncSession,
    entry: dict,
    client_name: str,
) -> None:
    """当 exact code 命中与「名称强语义」命中（name_exact / name_prefix）指向不同标准
    科目时，让名称强语义命中优先，并把代码精确命中降级为 code_match_conflict
    （warning 非空、score<0.9），不得作为安全自动确认候选。

    强名称候选来源：
    - name_exact：标准名规范化 == 客户名规范化（TASK-068），已由候选构造阶段产生；
    - name_prefix：客户名称首段/开头明确命中更精确标准子级名称（TASK-070），
      仅在存在冲突 code_match（指向父级）时按需查询并追加为安全候选，避免污染
      「银行存款明细」「主营业务成本-暂估」等本应由 name_anchor/前缀兜底处理的场景。

    若发生降级则重排候选，使名称强语义命中排在冲突 code_match 前。
    详见 TASK-068 / TASK-070。
    """
    candidates = entry["candidates"]
    code_candidates = [c for c in candidates if c.get("source") == "code_match"]
    if not code_candidates:
        return
    norm_client = _normalize_name(client_name)
    if not norm_client:
        return

    # 1) 优先用 name_exact 强候选
    strong_name = _pick_exact_strong_name_candidate(candidates, client_name)
    if strong_name is not None:
        if _resolve_exact_code_vs_exact_name_conflict_sync(entry, strong_name):
            candidates.sort(key=_candidate_priority)
        return

    # 2) 无 name_exact：按需查询 name_prefix 强候选。先把候选已占用 id 收集起来，
    #    避免追加重复候选（含已被 code_match 等占用的标准科目）。
    #    name_prefix 仅在它指向与某个 code_match 不同标准科目（即存在潜在冲突）时才有意义，
    #    否则不应在主流程添加，以免抢占 name_anchor/前缀兜底的位置。
    existing_ids = {c.get("standard_account_id") for c in candidates}
    code_ids = {c.get("standard_account_id") for c in code_candidates}

    prefix_matches = await _query_name_prefix_match(db, client_name)
    if not prefix_matches:
        return
    # 取最具体（canonical 名最长）的命中标准科目
    best_prefix_sa = max(
        prefix_matches,
        key=lambda sa: len(_canonical_name(sa.account_name)),
    )
    best_prefix_id = str(best_prefix_sa.id)
    # 该 name_prefix 强候选不能指向某个已存在的 code_match（否则就是同科目，无冲突）
    if best_prefix_id in code_ids:
        return

    # 若已经有更高/同等优先级候选指向该子级，则无需再追加 name_prefix
    if best_prefix_id in existing_ids:
        existing_for_id = next(c for c in candidates if c.get("standard_account_id") == best_prefix_id)
        existing_source = existing_for_id.get("source")
        # 已有 name_exact/历史/安全道等，无需追加 name_prefix 占位来制造冲突
        if existing_source in {"company_history", "global_history", "name_exact", "semantic_alias"}:
            strong_name = existing_for_id
            if _resolve_exact_code_vs_exact_name_conflict_sync(entry, strong_name):
                candidates.sort(key=_candidate_priority)
            return

    strong_name = _build_name_prefix_candidate(best_prefix_sa, client_name)
    candidates.append(strong_name)
    if _resolve_exact_code_vs_exact_name_conflict_sync(entry, strong_name):
        candidates.sort(key=_candidate_priority)


async def _query_history_mapping(
    db: AsyncSession,
    data_type: str,
    customer_label: str | None,
    scope: str,
    client_code: str,
    client_name: str,
) -> list[ClientAccountMapping]:
    """查询历史映射经验"""
    normalized_code = _normalize_code(client_code)
    normalized_name = _normalize_name(client_name)
    if not normalized_code and not normalized_name:
        return []

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

    stmt = (
        select(ClientAccountMapping)
        .where(and_(*conditions))
        .order_by(desc(ClientAccountMapping.usage_count), desc(ClientAccountMapping.last_used_at))
    )
    result = await db.execute(stmt)
    mappings = list(result.scalars().all())

    matched: list[tuple[int, ClientAccountMapping]] = []
    for cam in mappings:
        code_matches = (
            bool(normalized_code)
            and _normalize_code(cam.client_account_code) == normalized_code
        )
        name_matches = (
            bool(normalized_name)
            and _history_name_value(cam) == normalized_name
        )
        if code_matches or name_matches:
            # 同一历史来源内，代码命中优先于名称命中；再按使用频次和最后使用时间排序。
            matched.append((0 if code_matches else 1, cam))

    matched.sort(
        key=lambda item: (
            item[0],
            -(item[1].usage_count or 0),
            -(item[1].last_used_at.timestamp() if item[1].last_used_at else 0),
        )
    )
    return [cam for _, cam in matched]


async def _query_code_match(db: AsyncSession, client_code: str) -> list[StandardAccount]:
    """查询标准科目代码精确匹配"""
    normalized_code = _normalize_code(client_code)
    if not normalized_code:
        return []

    stmt = select(StandardAccount)
    result = await db.execute(stmt)
    matches = [
        sa for sa in result.scalars().all()
        if _normalize_code(sa.account_code) == normalized_code
    ]
    matches.sort(key=lambda sa: (not sa.is_active, sa.account_code))
    return matches[:3]


async def _query_name_exact_match(db: AsyncSession, client_name: str) -> list[StandardAccount]:
    """查询标准科目名称规范化后的精确匹配。

    注意：此处用 _normalize_name（不去「减：/加：/其中：」显示前缀）。
    带显示前缀的标准科目（如「减：研发费用」）不应被客户「研发费用」自动确认匹配，
    那属于锚点兜底（_query_name_anchor_match），需带 warning 由用户确认。
    """
    normalized_name = _normalize_name(client_name)
    if not normalized_name:
        return []

    stmt = select(StandardAccount)
    result = await db.execute(stmt)
    matches = [
        sa for sa in result.scalars().all()
        if _normalize_name(sa.account_name) == normalized_name
    ]
    matches.sort(key=lambda sa: (not sa.is_active, sa.account_code))
    return matches[:5]


async def _query_name_anchor_match(db: AsyncSession, anchor: str) -> list[StandardAccount]:
    """按名称锚点匹配标准科目（剥离显示前缀后比较）。

    优先级：
    1. canonical 标准科目名 == canonical anchor（精确）
    2. canonical 标准科目名 contains canonical anchor（包含，如 anchor「研发费用」命中「研发费用-资本化」）

    active 标准科目优先；精确优于包含；同优先级按代码升序。最多返回 5 个。
    """
    canonical_anchor = _canonical_name(anchor)
    if not canonical_anchor:
        return []

    stmt = select(StandardAccount)
    result = await db.execute(stmt)
    all_accounts = list(result.scalars().all())

    exact: list[StandardAccount] = []
    contains: list[StandardAccount] = []
    for sa in all_accounts:
        canonical_sa = _canonical_name(sa.account_name)
        if not canonical_sa:
            continue
        if canonical_sa == canonical_anchor:
            exact.append(sa)
        elif canonical_anchor in canonical_sa:
            contains.append(sa)

    exact.sort(key=lambda sa: (not sa.is_active, sa.account_code))
    contains.sort(key=lambda sa: (not sa.is_active, sa.account_code))
    return (exact + contains)[:5]



async def _query_name_similarity(
    db: AsyncSession, client_name: str, threshold: float = 0.6
) -> list[tuple[StandardAccount, float]]:
    """查询标准科目名称相似度（数据库层粗筛后用 Python 精算）。

    用 _normalize_name（不去显示前缀），避免「研发费用」与「减：研发费用」
    因剥离前缀后完全相同而被高相似度自动确认。带前缀的标准科目由锚点兜底处理。
    """
    normalized_input = _normalize_name(client_name)
    if not normalized_input or len(normalized_input) < 2:
        return []

    stmt = select(StandardAccount)
    result = await db.execute(stmt)
    all_accounts = list(result.scalars().all())

    matches: list[tuple[StandardAccount, float]] = []
    for sa in all_accounts:
        sim = _similarity(normalized_input, _normalize_name(sa.account_name))
        if sim >= threshold:
            matches.append((sa, sim))

    # 按相似度、启用状态降序，最多返回 5 个
    matches.sort(key=lambda x: (x[1], x[0].is_active), reverse=True)
    return matches[:5]


async def _query_code_prefix_parent(db: AsyncSession, client_code: str) -> list[StandardAccount]:
    """按最长标准科目代码前缀匹配上级标准科目。

    客户明细科目代码（如 10020108）没有精确匹配时，找到标准科目表中
    代码是该客户代码前缀、且最长（最贴近）的标准科目（如 1002）。
    排除与客户代码完全相等的情况（那属于精确匹配，应已由 code_match 处理）。
    """
    normalized_code = _normalize_code(client_code)
    if not normalized_code or len(normalized_code) < 4:
        # 代码太短时前缀匹配噪声大，不做
        return []

    stmt = select(StandardAccount)
    result = await db.execute(stmt)
    all_accounts = list(result.scalars().all())

    candidates: list[tuple[int, StandardAccount]] = []  # (前缀长度, sa)
    for sa in all_accounts:
        sa_code = _normalize_code(sa.account_code)
        if not sa_code or sa_code == normalized_code:
            continue
        # 标准科目代码必须是客户代码的真前缀（标准科目更短，且客户代码以它开头）
        if normalized_code.startswith(sa_code):
            candidates.append((len(sa_code), sa))

    if not candidates:
        return []
    # 取最长前缀（最贴近明细的父级）；同长度时启用优先、代码升序
    candidates.sort(key=lambda item: (item[0], item[1].is_active, item[1].account_code), reverse=True)
    # 只返回最长前缀对应的标准科目（可能有并列，最多 3 个）
    best_len = candidates[0][0]
    best = [sa for length, sa in candidates if length == best_len]
    best.sort(key=lambda sa: (not sa.is_active, sa.account_code))
    return best[:3]


# 客户科目代码类别 → 标准科目名称锚点。
# 用于客户代码体系与标准代码体系不一致的场景：客户用 6604 表示研发费用，
# 但标准科目库里没有 6604，只有「660201 减：研发费用」。此时按代码类别对应的
# 名称锚点去标准科目表找候选（经 _query_name_anchor_match 命中）。
# 键为客户代码前缀（最长优先匹配），值为该类别对应的标准科目名称锚点。
_CODE_CATEGORY_ANCHORS: list[tuple[str, str]] = [
    # 资产
    ("1001", "库存现金"),
    ("1002", "银行存款"),
    ("1012", "其他货币资金"),
    ("1121", "应收票据"),
    ("1122", "应收账款"),
    ("1123", "预付账款"),  # 预付款项
    ("1221", "其他应收款"),
    ("1401", "原材料"),
    ("1405", "库存商品"),
    ("1601", "固定资产"),
    ("1701", "无形资产"),
    # TASK-079：补充投资性房地产 / 长期股权投资 / 使用权资产 / 租赁负债
    ("1511", "长期股权投资"),
    ("1521", "投资性房地产"),
    ("1523", "投资性房地产"),  # 减值准备也按投资性房地产归入
    ("1705", "使用权资产原值"),     # 客户明细代码 → 164101
    ("1706", "使用权资产累计折旧"),  # 客户明细代码 → 1642
    # 负债
    ("2201", "应付票据"),
    ("2202", "应付账款"),
    ("2203", "预收账款"),
    ("2211", "应付职工薪酬"),
    ("2501", "长期借款"),
    # 权益
    ("4001", "实收资本"),
    ("4101", "资本公积"),
    ("4104", "未分配利润"),
    # 损益
    ("6001", "主营业务收入"),
    ("6401", "主营业务成本"),
    ("6301", "营业外收入"),
    ("6601", "销售费用"),
    ("6602", "管理费用"),
    ("6603", "财务费用"),
    ("6604", "研发费用"),
    ("6711", "营业外支出"),
    ("6801", "所得税费用"),
]


def _detect_code_category_anchor(client_code: str) -> str | None:
    """根据客户科目代码前缀，返回对应的名称锚点（最长前缀优先）。"""
    normalized_code = _normalize_code(client_code)
    if not normalized_code:
        return None
    # 按前缀长度从长到短匹配，保证更具体的类别优先
    for prefix, anchor in sorted(_CODE_CATEGORY_ANCHORS, key=lambda x: len(x[0]), reverse=True):
        if normalized_code.startswith(prefix):
            return anchor
    return None


async def _query_code_category_anchor(db: AsyncSession, client_code: str) -> list[StandardAccount]:
    """按客户代码类别锚点查询标准科目。

    客户代码体系与标准不一致时（如客户 6604 研发费用，标准无 6604），
    按代码类别对应的名称锚点（6604→研发费用）去标准科目表按名称匹配
    （经 _query_name_anchor_match，命中「减：研发费用」等带前缀的标准科目）。
    """
    anchor = _detect_code_category_anchor(client_code)
    if not anchor:
        return []
    return await _query_name_anchor_match(db, anchor)



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

    # 检查历史映射是否存在名称冲突（防止旧错配继续作为安全候选）
    conflict = _check_standard_name_conflict(sa, cam.client_account_name)
    if conflict:
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": min(score, 0.75),
            "source": f"{source}_conflict",
            "reason": f"历史映射与当前客户科目名称冲突：{conflict}",
            "warning": conflict,
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


def _check_standard_name_conflict(
    sa: StandardAccount, client_name: str | None,
) -> str | None:
    """判断标准科目与客户名称是否存在强冲突。

    返回 None 表示不冲突；返回字符串表示冲突原因。
    用于历史映射候选的安全校验，防止旧错配继续作为安全候选。
    """
    if not client_name or not sa:
        return None

    sa_name = sa.account_name or ""
    sa_code = sa.account_code or ""
    client_norm = _normalize_name(client_name)

    # 规则 1：备抵/减值/准备类标准科目，但客户名称没有减值/准备语义
    if _has_negative_reserve_semantics(sa_name):
        # 客户名称中无减值/准备/坏账/跌价/累计折旧/累计摊销等语义
        reserve_keywords = ["减值", "准备", "坏账", "跌价", "累计折旧", "累计摊销",
                            "减值准备", "减值损失"]
        if not any(kw in client_norm for kw in reserve_keywords):
            return f"标准科目「{sa_code} {sa_name}」是备抵/减值类，但客户科目名称「{client_name}」无减值语义"

    # 规则 2：标准是研发费用（660201），但客户名称含 研发支出_费用化支出 或 研发支出_资本化支出
    if "660201" in sa_code or "研发费用" in sa_name:
        if any(kw in client_norm for kw in ["研发支出", "资本化支出", "费用化支出"]):
            return f"标准科目「{sa_code} {sa_name}」是研发费用，但客户科目「{client_name}」含研发支出语义"

    # 规则 3：标准是研发支出-费用化支出（170402），但客户名称是纯研发费用（无费用化支出语义）
    if "170402" in sa_code or "研发支出-费用化支出" in sa_name:
        if "研发费用" in client_norm and "费用化支出" not in client_norm:
            return f"标准科目「{sa_code} {sa_name}」是研发支出-费用化，但客户科目「{client_name}」是纯研发费用"

    # 规则 4：标准是研发支出-资本化支出（170401），但客户名称含费用化支出
    if "170401" in sa_code or "研发支出-资本化支出" in sa_name:
        if "费用化支出" in client_norm:
            return f"标准科目「{sa_code} {sa_name}」是研发支出-资本化，但客户科目「{client_name}」含费用化支出"

    return None


def _build_code_match_candidate(
    sa: StandardAccount,
    client_name: str | None = None,
) -> dict:
    """从代码精确匹配构造候选。

    若客户名称包含名称锚点（如「预付账款」），但标准科目 canonical name 不包含该锚点，
    则判定为代码冲突，降级为 code_match_conflict，带 warning 且 score 降低，
    不会被前端自动确认。
    """
    if client_name:
        conflict = _check_code_match_name_conflict(sa, client_name)
        if conflict:
            return {
                "standard_account_id": str(sa.id),
                "standard_account_code": sa.account_code,
                "standard_account_name": sa.account_name,
                "score": conflict["score"],
                "source": "code_match_conflict",
                "reason": f"科目代码相同但名称锚点不一致 → {sa.account_code} {sa.account_name}",
                "warning": conflict["warning"],
            }

    return _build_standard_account_candidate(
        sa,
        source="code_match",
        score=0.95,
        reason_prefix="科目代码精确匹配",
    )


# ── TASK-072：备抵/减值类名称检测 ──
_NEGATIVE_RESERVE_TOKENS = (
    "减值准备", "资产减值损失", "坏账准备", "跌价准备",
    "累计折旧", "累计摊销", "减值", "准备",
)


def _has_negative_reserve_semantics(name: str | None) -> bool:
    """判断科目名称是否包含备抵/减值语义（减值准备、累计折旧等）。"""
    canonical = _canonical_name(name)
    if not canonical:
        return False
    return any(_normalize_name(token) in canonical for token in _NEGATIVE_RESERVE_TOKENS)


def _check_code_match_name_conflict(
    sa: StandardAccount,
    client_name: str,
) -> dict | None:
    """检测代码精确匹配是否与名称锚点冲突。

    从客户科目名称中识别 name_anchor（如「预付账款_预付材料款」→「预付账款」），
    对标准科目名称做 canonical 处理（剥离「加：/减：/其中：」等显示前缀），
    若客户 name_anchor 存在但标准科目 canonical name 不包含该 anchor，
    返回冲突信息 dict，否则返回 None（安全）。

    TASK-072 补充：当标准科目为备抵/减值类（如减：在建工程-减值准备），
    即使客户名称 anchor 是其子串（如「在建工程」），也必须检测客户名称
    是否体现了减值语义。若客户名称无减值含义，则代码相同也不安全，
    必须降级为冲突候选。
    """
    # ── TASK-072：备抵/减值类科目冲突检测（优先于锚点检测） ──
    # 标准科目为备抵/减值类（如「减值准备」「累计折旧」等），
    # 但客户名称不体现减值语义时，必须降级，即使锚点无法识别。
    # 例如：标准「减：在建工程-减值准备」，客户「在建工程_生产线」
    # _detect_name_anchor 找不到锚点，但标准名含「减值准备」→ 冲突。
    if _has_negative_reserve_semantics(sa.account_name) and not _has_negative_reserve_semantics(client_name):
        score = 0.72
        warning = (
            f"代码相同但标准科目为备抵/减值类「{sa.account_name}」，"
            f"客户名称「{client_name}」未体现减值/准备/累计折旧等含义，请勿自动归入"
        )
        if not sa.is_active:
            warning = f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"
        return {"score": score, "warning": warning}

    anchor = _detect_name_anchor(client_name)
    if not anchor:
        # 客户名称没有可识别的锚点，无法判断冲突
        return None

    # canonical 处理标准科目名称：剥离显示前缀
    sa_canonical = _canonical_name(sa.account_name)
    if not sa_canonical:
        return None

    # 锚点已在 canonical 标准名称中 → 安全
    anchor_norm = _normalize_name(anchor)
    if anchor_norm and anchor_norm in sa_canonical:
        return None

    # 锚点不在标准科目名称中 → 名称冲突
    score = 0.75
    warning = (
        f"代码相同但名称锚点不一致：客户为「{anchor}」，标准为"
        f"「{sa.account_name}」，请人工确认"
    )
    if not sa.is_active:
        warning = f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"

    return {"score": score, "warning": warning}


def _build_name_exact_candidate(sa: StandardAccount) -> dict:
    """从名称规范化精确匹配构造候选"""
    return _build_standard_account_candidate(
        sa,
        source="name_exact",
        score=0.94,
        reason_prefix="科目名称精确匹配",
    )


# ── TASK-070：客户名称首段/开头命中更精确标准子级名称 ──
# 用于「1411 包装物_纸箱」这类带明细后缀的科目：客户代码命中标准父级 `1411 周转材料`，
# 但客户名称首段「包装物」是更精确的标准子级 `141101 包装物`。此时应把子级作为强语义
# 安全候选，并把冲突的父级 code_match 降级，避免自动归入父级。
# 过于泛化的标准名称（资产/负债/费用…）不作为自动安全匹配依据，避免误匹配。
_GENERIC_NAME_PREFIX_BLOCKLIST = {
    "资产", "负债", "权益", "收入", "成本", "费用", "其他", "减", "加", "净",
    "合计", "小计", "总计", "余额", "明细", "类",
}


def _standard_name_is_generic(canonical_name: str) -> bool:
    """判断规范化后的标准科目名称是否过于泛化，不应作为 name_prefix 自动安全匹配依据。"""
    if not canonical_name:
        return True
    if canonical_name in _GENERIC_NAME_PREFIX_BLOCKLIST:
        return True
    # 单字或长度 < 2 的标准名过于模糊
    if len(canonical_name) < 2:
        return True
    return False


def _client_name_starts_with_standard_name(
    client_name: str | None,
    standard_name: str | None,
) -> bool:
    """判断客户科目名称是否以标准科目名称开头（canonical 比较）。

    规则：
    - 双方 canonical 名称非空；
    - 客户 canonical == 标准 canonical：视为命中（精确，亦由 name_exact 覆盖，但保留作为兼容入口）；
    - 客户 canonical 以标准 canonical 开头：命中（如「包装物纸箱」以「包装物」开头）；
    - 客户名称第一分段 token canonical == 标准 canonical：命中（如「包装物_纸箱」第一段「包装物」）。
    """
    client_canonical = _canonical_name(client_name)
    standard_canonical = _canonical_name(standard_name)
    if not client_canonical or not standard_canonical:
        return False
    if client_canonical == standard_canonical:
        return True
    if client_canonical.startswith(standard_canonical):
        return True
    tokens = _split_name_tokens(client_name or "")
    if tokens:
        first_token = _canonical_name(tokens[0])
        return bool(first_token) and first_token == standard_canonical
    return False


async def _query_name_prefix_match(
    db: AsyncSession,
    client_name: str,
) -> list[StandardAccount]:
    """查询客户名称首段/开头明确命中的、更精确的标准科目（强名称前缀候选）。

    限制（避免误匹配）：
    - 标准科目 active；
    - 标准 canonical 名称非泛化（不命中 blocklist、长度 >= 2）；
    - 客户名称以标准名称开头或首段等于标准名称；
    - 排除客户 canonical 与标准 canonical 完全相等（已由 name_exact 处理）。

    优先级：更长（更具体）的标准名称优先；同长按代码升序。最多 5 个。
    """
    client_canonical = _canonical_name(client_name)
    if not client_canonical or len(client_canonical) < 2:
        return []

    stmt = select(StandardAccount)
    result = await db.execute(stmt)
    all_accounts = list(result.scalars().all())

    matches: list[StandardAccount] = []
    for sa in all_accounts:
        if not sa.is_active:
            continue
        sa_canonical = _canonical_name(sa.account_name)
        if _standard_name_is_generic(sa_canonical):
            continue
        if sa_canonical == client_canonical:
            # 精确相等交由 name_exact 处理，避免重复
            continue
        if _client_name_starts_with_standard_name(client_name, sa.account_name):
            matches.append(sa)

    matches.sort(key=lambda sa: (-len(_canonical_name(sa.account_name)), sa.account_code))
    return matches[:5]


def _build_name_prefix_candidate(sa: StandardAccount, client_name: str) -> dict:
    """从客户名称首段/开头命中更精确标准子级名称构造安全候选。

    安全（warning=None, score=0.93）：客户名称明显以更精确标准科目名称开头，
    语义精确度高于父级代码命中，应优先自动确认到该子级。详见 TASK-070。
    """
    candidate = _build_standard_account_candidate(
        sa,
        source="name_prefix",
        score=0.93,
        reason_prefix="客户科目名称首段匹配更精确标准科目",
    )
    candidate["reason"] = (
        f"客户科目名称首段/开头匹配更精确标准科目 → {sa.account_code} {sa.account_name}"
    )
    return candidate


def _build_name_similarity_candidate(sa: StandardAccount, similarity: float) -> dict:
    """从名称相似度构造候选"""
    score = round(0.7 + (similarity - 0.6) * 0.5, 2)  # 0.6→0.7, 1.0→0.9
    warning = None if similarity >= 0.85 else f"名称相似度仅 {similarity:.0%}，建议人工确认"
    if not sa.is_active:
        warning = f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": min(score, 0.92),
        "source": "name_similarity",
        "reason": f"科目名称相似（相似度 {similarity:.0%}）→ {sa.account_code} {sa.account_name}",
        "warning": warning,
    }


def _is_safe_auto_rollup(sa: StandardAccount, client_name: str | None, context: dict | None = None) -> bool:
    """判断客户明细科目是否可安全自动归入该标准科目（父级汇总/锚点匹配）。

    条件：
    1. 标准科目 active
    2. 从客户名称中可识别名称锚点
    3. 该锚点存在于标准科目的 canonical name 中
    4. 行上下文允许参与入库：is_leaf 不为 False、is_summary 不为 True、
       participates_in_entry 不为 False（缺失这些 key 时视为允许）

    满足全部条件时返回 True，允许构建 warning=None、score>=0.9 的安全候选。
    """
    if not sa.is_active:
        return False
    if not client_name:
        return False
    # 行级上下文检查：非末级/汇总行/不入库行不得安全自动归入
    if context:
        if context.get("is_leaf") is False:
            return False
        if context.get("is_summary") is True:
            return False
        if context.get("participates_in_entry") is False:
            return False
    anchor = _detect_name_anchor(client_name)
    if anchor:
        sa_canonical = _canonical_name(sa.account_name)
        if not sa_canonical:
            return False
        anchor_norm = _normalize_name(anchor)
        # 安全要求：anchor 与标准 canonical name 完全等价或以 anchor 开头。
        # 「固定资产原值」以「固定资产」开头 → 安全
        # 「农业生产成本」不以「生产成本」开头 → 不安全
        if anchor_norm and sa_canonical == anchor_norm:
            return True
        if anchor_norm and sa_canonical.startswith(anchor_norm):
            return True

    # TASK-078：放宽明细代码安全归入。
    # 当客户明细科目名称首段/开头明确以标准科目名称开头（如「工程物资\设备」→标准 1605 工程物资），
    # 或首段恰好等于标准科目名称时，允许安全归入该上级标准科目，不再无脑 warning。
    if _client_name_starts_with_standard_name(client_name, sa.account_name):
        # 排除备抵/减值类父标准科目：客户名称未体现减值语义时，不能安全汇总到
        # 「累计折旧」「存货跌价准备」等准备科目（避免「减值准备 _xxx」误命中）。
        if _has_negative_reserve_semantics(sa.account_name) and not _has_negative_reserve_semantics(client_name):
            return False
        return True

    # TASK-079：客户代码类别锚点安全匹配（如 1122 → 应收账款 → 112201 应收账款）。
    # 当客户代码所属类别（code_category_anchor）对应的标准科目名称包含该锚点，
    # 且标准科目非备抵/减值类，认定为安全归入。
    # 但当客户名称是测试占位符（如「明细科目」）时，不安全：无法证明经济含义一致。
    if context and context.get("client_account_code"):
        _GENERIC_CLIENT_NAMES_SET = {"明细科目", "明细", "xxx", "未知", "测试", "test"}
        if not (client_name and _normalize_name(client_name) in _GENERIC_CLIENT_NAMES_SET):
            cat_anchor = _detect_code_category_anchor(context["client_account_code"])
            if cat_anchor:
                sa_canonical = _canonical_name(sa.account_name)
                cat_norm = _normalize_name(cat_anchor)
                if cat_norm and sa_canonical and (
                    sa_canonical == cat_norm or sa_canonical.startswith(cat_norm)
                ):
                    # 类别锚点精确匹配时，即便标准是备抵/减值类也安全
                    return True

    # TASK-078：纯代码前缀明细（如金蝶 1123.001 业务款项 / 1222.001 内部关联方）
    # 名称为通用明细后缀，无法识别锚点；客户代码就是标准代码 + 数字后缀时，
    # 只要标准科目不是备抵/减值类，安全归入该上级标准科目。
    # 但当客户名称是测试占位符（如「明细科目」「xxx」）时，不安全：无法证明经济含义一致。
    _GENERIC_CLIENT_NAMES = {"明细科目", "明细", "xxx", "未知", "测试", "test"}
    if client_name and _normalize_name(client_name) in _GENERIC_CLIENT_NAMES:
        return False
    ctx_client_code = None
    if context:
        ctx_client_code = context.get("client_account_code") or context.get("client_code")
    if ctx_client_code:
        client_norm = _normalize_code(ctx_client_code)
        sa_norm = _normalize_code(sa.account_code)
        if (sa_norm and client_norm != sa_norm
                and client_norm.startswith(sa_norm)
                and len(client_norm) > len(sa_norm)):
            # 后缀必须全部是数字（如 1123.001 -> 1123001，后缀 "001"）
            suffix = client_norm[len(sa_norm):]
            if suffix.isdigit():
                # 代码前缀直接确认父子关系时，即使标准科目是备抵/减值类也安全
                # 例如客户 1602003 前缀命中标准 1602 累计折旧 → 安全
                # _check_code_match_name_conflict 会在 code_match 层防止误冲突
                return True

    return False


def _build_code_prefix_parent_candidate(
    sa: StandardAccount,
    client_code: str,
    client_name: str | None = None,
    context: dict | None = None,
) -> dict:
    """从客户明细代码最长标准科目前缀构造候选（父级汇总）。

    若名称锚点与标准科目 canonical name 一致，则视为安全自动归入
    （warning=None, score=0.92）；否则为兜底候选（带 warning, score=0.85）。
    """
    if _is_safe_auto_rollup(sa, client_name, context):
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": 0.92,
            "source": "code_prefix_parent",
            "reason": f"明细代码前缀安全归入上级科目 → {sa.account_code} {sa.account_name}",
            "warning": None,
        }
    score = 0.85
    warning = (
        f"按客户明细科目代码「{client_code}」前缀推荐至上级标准科目"
        f"「{sa.account_code} {sa.account_name}」，请确认是否汇总到该标准科目"
    )
    if not sa.is_active:
        warning = f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": score,
        "source": "code_prefix_parent",
        "reason": f"明细代码前缀匹配上级科目 → {sa.account_code} {sa.account_name}",
        "warning": warning,
    }


def _build_name_anchor_candidate(
    sa: StandardAccount,
    anchor: str,
    client_name: str,
    context: dict | None = None,
) -> dict:
    """从名称锚点构造候选。

    若锚点与标准科目 canonical name 一致，视为安全自动归入（warning=None, score=0.92）；
    否则为兜底候选（带 warning, score=0.86）。
    """
    if _is_safe_auto_rollup(sa, client_name, context):
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": 0.92,
            "source": "name_anchor",
            "reason": f"名称锚点「{anchor}」安全归入 → {sa.account_code} {sa.account_name}",
            "warning": None,
        }
    score = 0.86
    warning = (
        f"按客户科目名称中的「{anchor}」锚点推荐至标准科目"
        f"「{sa.account_code} {sa.account_name}」，请确认是否归入该标准科目"
    )
    if not sa.is_active:
        warning = f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": score,
        "source": "name_anchor",
        "reason": f"名称锚点「{anchor}」匹配 → {sa.account_code} {sa.account_name}",
        "warning": warning,
    }


def _build_code_category_anchor_candidate(
    sa: StandardAccount,
    client_code: str,
    client_name: str | None = None,
    context: dict | None = None,
) -> dict:
    """从客户代码类别锚点构造候选。

    若名称锚点与标准科目 canonical name 一致，视为安全自动归入（warning=None, score=0.92）；
    否则为兜底候选（带 warning, score=0.86）。
    """
    if _is_safe_auto_rollup(sa, client_name, context):
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": 0.92,
            "source": "code_category_anchor",
            "reason": f"代码类别锚点安全归入 → {sa.account_code} {sa.account_name}",
            "warning": None,
        }
    score = 0.86
    warning = (
        f"按客户科目代码「{client_code}」类别/名称锚点推荐至标准科目"
        f"「{sa.account_code} {sa.account_name}」，请确认是否归入该标准科目"
    )
    if not sa.is_active:
        warning = f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": score,
        "source": "code_category_anchor",
        "reason": f"代码类别锚点匹配 → {sa.account_code} {sa.account_name}",
        "warning": warning,
    }


def _build_standard_account_candidate(
    sa: StandardAccount,
    *,
    source: str,
    score: float,
    reason_prefix: str,
) -> dict:
    """从标准科目直接匹配构造候选，停用科目只能作为警告候选。"""
    warning = None
    if not sa.is_active:
        warning = f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"

    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": score,
        "source": source,
        "reason": f"{reason_prefix} → {sa.account_code} {sa.account_name}",
        "warning": warning,
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
