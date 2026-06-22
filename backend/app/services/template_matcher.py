"""模板匹配器 — 表头指纹 + 签名安全校验 + 评分 + 负向规则"""

from difflib import SequenceMatcher

from app.services.file_parser import build_columns, parse_file
from app.services.column_matcher import TYPE_FIELDS, REQUIRED_FIELDS, NEGATIVE_MATCH, auto_match
from app.models.import_template import ImportTemplate


# 签名匹配安全阈值
SIGNATURE_SAFE_THRESHOLD = 0.55  # 低于此值视为不匹配


def build_fingerprint(
    headers: list[str], data_type: str
) -> dict:
    """构建表头指纹。"""
    columns = build_columns(headers)
    fp: dict[str, str | list] = {}
    for c in columns:
        fp[c["column_id"]] = c["normalized_header"]

    fp["_meta"] = {
        "total_columns": len(columns),
        "data_type": data_type,
        "duplicate_headers": [
            {"header": c["normalized_header"], "count": c["duplicate_group"]["total"]}
            for c in columns
            if c["duplicate_group"] is not None
        ],
        "empty_headers": [
            c["column_id"] for c in columns if not c["normalized_header"]
        ],
    }
    return fp


def _header_similarity(a: str, b: str) -> float:
    """两个表头的相似度（0~1），忽略大小写和首尾空格"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _check_signature_match(
    template_sig: dict,
    columns: list[dict],
) -> tuple[float, list[str], list[str]]:
    """
    校验模板签名与当前文件列的匹配程度。

    Returns:
        (match_ratio, matched_details, mismatch_details)
    """
    sig_items = [
        (k, v) for k, v in template_sig.items()
        if isinstance(v, str) and v and not k.startswith("_")
    ]
    if not sig_items:
        return 0.0, [], ["模板无有效签名"]

    # 构建 col_id → index 快速查找
    col_index: dict[str, int] = {}
    for c in columns:
        col_index[c["column_id"]] = c["index"]

    matched_details = []
    mismatch_details = []

    for col_id, sig_header in sig_items:
        if col_id in col_index:
            idx = col_index[col_id]
            if idx < len(columns):
                file_header = columns[idx]["normalized_header"]
            else:
                file_header = ""
        else:
            file_header = ""

        sim = _header_similarity(sig_header, file_header)
        if sim >= 0.7:
            matched_details.append(f"{sig_header} ≈ {file_header} ({col_id})")
        else:
            mismatch_details.append(
                f"模板期望「{sig_header}」({col_id})，文件为「{file_header}」"
            )

    match_count = len(matched_details)
    total = len(sig_items)
    ratio = match_count / total if total > 0 else 0.0
    return ratio, matched_details, mismatch_details


def match_templates(
    file_path: str,
    data_type: str,
    templates: list[ImportTemplate],
) -> list[dict]:
    """匹配所有启用模板，按分数降序返回候选列表。"""
    headers, rows = parse_file(file_path)
    columns = build_columns(headers, rows[:3])
    file_fp = build_fingerprint(headers, data_type)

    candidates = []
    for t in templates:
        if t.data_type != data_type or not t.is_active:
            continue
        result = _score_template(t, file_fp, columns, headers)
        if result is not None:
            candidates.append(result)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def _score_template(
    template: ImportTemplate,
    file_fp: dict,
    columns: list[dict],
    headers: list[str],
) -> dict | None:
    """对单个模板评分，签名不匹配则大幅降分"""
    sig = template.header_signature or {}
    rules = template.column_rules or {}
    targets = set(TYPE_FIELDS.get(template.data_type, []))
    required = set(REQUIRED_FIELDS.get(template.data_type, []))

    warnings = []
    matched_fields = []
    missing_fields = []

    # 1. 字段覆盖率
    total_targets = len(targets)
    if total_targets == 0:
        return None

    for field in targets:
        if field in rules.values():
            matched_fields.append(field)
        else:
            missing_fields.append(field)

    coverage = len(matched_fields) / total_targets

    # 2. 签名匹配度（替换纯 Jaccard）
    signature_ratio, sig_matched, sig_mismatches = _check_signature_match(sig, columns)
    if signature_ratio < SIGNATURE_SAFE_THRESHOLD:
        # 签名不匹配 → 严重降分
        score = coverage * 40
        warnings.append(
            f"模板签名与当前文件表头不匹配（相似度 {int(signature_ratio * 100)}%），"
            f"候选不可靠"
        )
    else:
        score = coverage * 50 + signature_ratio * 50

    # 3. 降分规则
    missing_required = required - set(matched_fields)
    if missing_required:
        penalty = len(missing_required) * 10
        score = max(0, score - penalty)
        warnings.append(f"缺必填字段：{'、'.join(sorted(missing_required))}")

    if template.data_type != file_fp.get("_meta", {}).get("data_type", template.data_type):
        score = max(0, score - 20)
        warnings.append("数据类型不一致")

    dup_metas = file_fp.get("_meta", {}).get("duplicate_headers", [])
    if dup_metas:
        dup_strs = [f"「{d['header']}」出现 {d['count']} 次" for d in dup_metas[:3]]
        warnings.append(f"文件包含重复表头：{'；'.join(dup_strs)}" + (
            "..." if len(dup_metas) > 3 else ""
        ))

    negative_hits = _check_negative_patterns(columns)
    if negative_hits:
        score = max(0, score - 5)
        warnings.extend(negative_hits)

    score = round(min(100, score))

    return {
        "template_id": str(template.id),
        "name": template.name,
        "score": score,
        "matched_fields": matched_fields,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "source_label": template.source_label,
    }


def _check_negative_patterns(columns: list[dict]) -> list[str]:
    """检查文件中是否有负向匹配模式"""
    warnings = []
    for c in columns:
        nh = c["normalized_header"]
        if not nh:
            continue
        for field, patterns in NEGATIVE_MATCH.items():
            for pattern in patterns:
                if pattern in nh:
                    warnings.append(
                        f"表头「{nh}」疑似含\"{pattern}\"，"
                        f"已排除与「{field}」的自动匹配"
                    )
                    break
    return warnings[:3]


def apply_template_to_columns(
    template: ImportTemplate,
    columns: list[dict],
) -> dict[str, str]:
    """
    将模板的 column_rules 应用到文件的列上，生成 column_mapping_v2。

    规则：
    1. 先校验签名匹配 — 不匹配则拒绝套用
    2. 签名匹配后，按 column_id → index 定位生成映射
    """
    sig = template.header_signature or {}
    ratio, _, mismatches = _check_signature_match(sig, columns)

    if ratio < SIGNATURE_SAFE_THRESHOLD:
        raise ValueError(
            f"模板「{template.name}」与当前文件表头不匹配"
            f"（相似度 {int(ratio * 100)}%），"
            f"无法安全套用。{'；'.join(mismatches[:3])}"
        )

    rules = template.column_rules or {}
    mapping_v2: dict[str, str] = {}

    # 列 ID 存在于文件 → 直接使用
    file_col_ids = {c["column_id"] for c in columns}
    for col_id, rule in rules.items():
        if rule == "ignore" or not rule:
            continue
        if col_id in file_col_ids:
            mapping_v2[col_id] = rule

    # 签名匹配但列 ID 不完全对应 → 按序号匹配作为 fallback
    if not mapping_v2 and rules:
        template_cols = sorted(
            [(int(k.replace("col_", "")), v) for k, v in rules.items()
             if k.startswith("col_") and v != "ignore"],
            key=lambda x: x[0],
        )
        for idx, (col_num, rule) in enumerate(template_cols):
            if idx < len(columns):
                mapping_v2[columns[idx]["column_id"]] = rule

    return mapping_v2
