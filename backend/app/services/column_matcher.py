"""列名智能匹配器 — 将中文/英文表头映射到标准字段"""

from difflib import SequenceMatcher

# 目标字段 → 可能的中英文列名
KEYWORD_MAP: dict[str, list[str]] = {
    # === 通用字段 ===
    "account_code": [
        "科目编码", "科目代码", "科目号", "会计科目编码", "会计科目代码",
        "account code", "account_code", "acct_code", "acct code",
        "科目", "会计科目", "account", "account number",
    ],
    "account_name": [
        "科目名称", "科目", "会计科目", "会计科目名称", "科目全称",
        "account name", "account_name", "acct_name", "acct name",
    ],
    "fiscal_year": [
        "会计年度", "年度", "年份", "年",
        "fiscal year", "year", "fiscal_year",
    ],
    "period": [
        "会计期间", "期间", "月份", "月",
        "period", "month", "会计月",
    ],

    # === 科目余额表 ===
    "opening_debit": [
        "期初借方余额", "期初借方", "期初借", "年初借方余额", "年初借方",
        "opening debit", "beginning debit", "期初余额(借)", "期初余额（借）",
        "期初借方金额", "期初余额借方",
        # 多行表头合并后变体（期初余额_借方_金额）
        "期初余额_借方_金额", "期初余额_借方", "期初余额借方金额",
        "本币期初余额借方", "本币期初余额_借方",
    ],
    "opening_credit": [
        "期初贷方余额", "期初贷方", "期初贷", "年初贷方余额", "年初贷方",
        "opening credit", "beginning credit", "期初余额(贷)", "期初余额（贷）",
        "期初贷方金额", "期初余额贷方",
        "期初余额_贷方_金额", "期初余额_贷方", "期初余额贷方金额",
        "本币期初余额贷方", "本币期初余额_贷方",
    ],
    "current_debit": [
        "本期借方发生额", "本期借方", "借方发生额", "本期借",
        "current debit", "debit amount", "dr amount",
        "本期借方金额", "本期发生额(借)", "本期发生额（借）",
        "本期发生_借方_金额", "本期发生_借方", "本期发生借方金额",
        "本期发生额_借方", "本期发生额_借方_金额",
    ],
    "current_credit": [
        "本期贷方发生额", "本期贷方", "贷方发生额", "本期贷",
        "current credit", "credit amount", "cr amount",
        "本期贷方金额", "本期发生额(贷)", "本期发生额（贷）",
        "本期发生_贷方_金额", "本期发生_贷方", "本期发生贷方金额",
        "本期发生额_贷方", "本期发生额_贷方_金额",
    ],
    "ending_debit": [
        "期末借方余额", "期末借方", "期末借", "年末借方余额", "年末借方",
        "ending debit", "closing debit", "期末余额(借)", "期末余额（借）",
        "期末借方金额", "期末余额借方",
        "期末余额_借方_金额", "期末余额_借方", "期末余额借方金额",
    ],
    "ending_credit": [
        "期末贷方余额", "期末贷方", "期末贷", "年末贷方余额", "年末贷方",
        "ending credit", "closing credit", "期末余额(贷)", "期末余额（贷）",
        "期末贷方金额", "期末余额贷方",
        "期末余额_贷方_金额", "期末余额_贷方", "期末余额贷方金额",
    ],

    # === 序时账 / 辅助明细账 ===
    "voucher_no": [
        "凭证号", "凭证编号", "凭证号码", "传票号", "凭证字",
        "voucher no", "voucher_no", "voucher number", "journal no",
        "凭证", "voucher",
    ],
    "voucher_date": [
        "凭证日期", "日期", "记账日期", "制单日期",
        "voucher date", "voucher_date", "date", "entry date",
    ],
    "summary": [
        "摘要", "说明", "备注", "描述",
        "summary", "description", "explanation", "note",
        "摘要说明", "凭证摘要",
    ],
    "debit_amount": [
        "借方金额", "借方", "借", "借方发生",
        "debit", "debit amount", "dr", "dr amount",
        "借方余额", "借方发生额",
    ],
    "credit_amount": [
        "贷方金额", "贷方", "贷", "贷方发生",
        "credit", "credit amount", "cr", "cr amount",
        "贷方余额", "贷方发生额",
    ],
    "attachment_count": [
        "附件数", "附件", "附单据数", "原始凭证张数",
        "attachment", "attachment count", "attachments",
    ],

    # === 辅助核算 ===
    "auxiliary_type": [
        "辅助核算类型", "辅助类型", "核算类型", "辅助核算类别",
        "auxiliary type", "aux_type",
    ],
    "auxiliary_code": [
        "辅助核算编码", "辅助编码", "核算编码",
        "auxiliary code", "aux_code", "辅助核算代码",
    ],
    "auxiliary_name": [
        "辅助核算名称", "辅助名称", "核算名称", "辅助核算",
        "auxiliary name", "aux_name",
        "客户名称", "供应商名称", "部门名称", "项目名称",
    ],
}

# 每种数据类型的必填字段
REQUIRED_FIELDS: dict[str, list[str]] = {
    "trial_balance": [
        "fiscal_year", "period",
        "account_code", "account_name",
    ],
    "journal": [
        "fiscal_year", "period",
        "voucher_no", "voucher_date", "summary",
        "account_code", "account_name",
    ],
    "subsidiary": [
        "fiscal_year", "period",
        "voucher_no", "voucher_date", "summary",
        "account_code", "account_name",
        "auxiliary_type",
    ],
}

# 每种数据类型需要的字段
TYPE_FIELDS: dict[str, list[str]] = {
    "trial_balance": [
        "fiscal_year", "period",
        "account_code", "account_name", "account_level",
        "opening_debit", "opening_credit",
        "current_debit", "current_credit",
        "ending_debit", "ending_credit",
    ],
    "journal": [
        "fiscal_year", "period",
        "voucher_no", "voucher_date", "summary",
        "account_code", "account_name",
        "debit_amount", "credit_amount", "attachment_count",
    ],
    "subsidiary": [
        "fiscal_year", "period",
        "voucher_no", "voucher_date", "summary",
        "account_code", "account_name",
        "debit_amount", "credit_amount",
        "auxiliary_type", "auxiliary_code", "auxiliary_name",
        "attachment_count",
    ],
}


def similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度（0~1）"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# 负向匹配规则：这些表头不能映射到某些字段（防止误判）
NEGATIVE_MATCH: dict[str, list[str]] = {
    "period": [
        "本币期间异动", "期间异动", "本期异动", "本月异动",
        "本币发生异动", "期间发生异动",
    ],
    "fiscal_year": [
        "本币本年累计", "本年累计", "本年异动", "本年发生",
        "本币累计", "累计发生",
    ],
}


def _is_negative_match(header: str, field: str) -> bool:
    """检查表头是否匹配负向规则"""
    patterns = NEGATIVE_MATCH.get(field, [])
    cleaned = header.strip()
    for pattern in patterns:
        if pattern in cleaned:
            return True
    return False


def match_column(header: str, target_fields: list[str]) -> tuple[str | None, float]:
    """
    将单个表头匹配到目标字段。

    Returns:
        (matched_field, confidence) — matched_field 为 None 表示未匹配
    """
    best_field = None
    best_score = 0.0
    cleaned = header.strip()

    for field in target_fields:
        # 负向匹配检查
        if _is_negative_match(cleaned, field):
            continue
        keywords = KEYWORD_MAP.get(field, [field])
        for kw in keywords:
            score = similarity(cleaned, kw)
            # 包含匹配加分
            if kw.lower() in cleaned.lower() or cleaned.lower() in kw.lower():
                score = max(score, 0.85)
            if score > best_score:
                best_score = score
                best_field = field

    # 置信度阈值
    if best_score >= 0.6:
        return best_field, best_score
    return None, best_score


def auto_match(headers: list[str], data_type: str) -> dict:
    """
    自动匹配整组表头到目标字段。

    Args:
        headers: 从文件解析出的表头列表
        data_type: trial_balance / journal / subsidiary

    Returns:
        {
            "matched": {"标准字段": "原始表头", ...},
            "unmatched": ["未匹配的表头", ...],
            "missing": ["缺少的必填字段", ...],
            "data_type": "journal"
        }
    """
    target_fields = TYPE_FIELDS.get(data_type, [])
    if not target_fields:
        raise ValueError(f"未知的数据类型: {data_type}（可选: trial_balance / journal / subsidiary）")

    matched = {}
    unmatched = []

    for header in headers:
        field, score = match_column(header, target_fields)
        if field is not None and field not in matched:
            matched[field] = header
        else:
            unmatched.append(header)

    # 检查缺少的必填字段
    required = REQUIRED_FIELDS.get(data_type, [])
    missing = [f for f in required if f not in matched]

    return {
        "matched": matched,
        "unmatched": unmatched,
        "missing": missing,
        "data_type": data_type,
    }


def apply_mapping(headers: list[str], mapping: dict[str, str]) -> dict[str, str]:
    """
    应用用户手动映射。

    Args:
        headers: 原始表头列表
        mapping: {"标准字段": "原始表头", ...}

    Returns:
        {"标准字段": "原始表头", ...}
    """
    result = {}
    for field, header in mapping.items():
        if header in headers:
            result[field] = header
    return result


def map_row(row: list, headers: list[str], mapping: dict[str, str]) -> dict:
    """
    将一行原始数据按映射转换为标准字段字典。

    Args:
        row: 原始数据行
        headers: 原始表头
        mapping: {"标准字段": "原始表头", ...}

    Returns:
        {"account_code": "1001", "account_name": "现金", ...}
    """
    result = {}
    for field, header in mapping.items():
        if header in headers:
            idx = headers.index(header)
            if idx < len(row):
                result[field] = row[idx]
    return result


def map_row_by_column_ids(row: list, columns: list[dict], mapping_v2: dict[str, str]) -> dict:
    """
    按列 ID 映射一行原始数据（v2 映射契约）。

    与 map_row() 的区别：通过稳定的 column_id → index 定位列，
    不受重复表头影响。

    Args:
        row: 原始数据行
        columns: build_columns() 返回的列描述符列表
        mapping_v2: {"col_001": "voucher_date", "col_010": "summary", ...}

    Returns:
        {"voucher_date": "2024-01-15", "summary": "采购原材料", ...}
    """
    # 构建 column_id → index 快速查找
    col_index: dict[str, int] = {}
    for c in columns:
        col_index[c["column_id"]] = c["index"]

    result: dict[str, object] = {}
    for col_id, field in mapping_v2.items():
        if col_id in col_index:
            idx = col_index[col_id]
            if idx < len(row):
                result[field] = row[idx]
    return result
