"""科目余额表层级识别与金额拆分转换引擎 — TASK-042

提供纯函数式转换能力，不依赖数据库：
1. 客户科目层级识别（代码前缀 / Excel 缩进 / 平铺）
2. 末级叶子行判定
3. 父级金额与子级汇总校验
4. 单列金额按标准科目方向拆借贷 / 用户覆盖借贷
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable


# ── 常量 ───────────────────────────────────────────

VALID_DIRECTIONS = ("debit", "credit")
VALID_SPLIT_MODES = (
    "two_column",
    "single_by_direction",
    "single_by_source_direction",
    "single_as_debit",
    "single_as_credit",
)
VALID_LEVEL_SOURCES = ("code_prefix", "indent_suggested", "flat")


# ── 数据类 ─────────────────────────────────────────

@dataclass
class AmountConfig:
    """单行金额映射配置 — 说明该行各个期间金额列的拆分方式"""
    period_type: str  # "opening" | "current" | "ending"
    mode: str  # two_column | single_by_direction | single_as_debit | single_as_credit
    debit_field: str | None = None   # two_column 模式下的借方字段名
    credit_field: str | None = None  # two_column 模式下的贷方字段名
    amount_field: str | None = None  # 单列模式下的金额字段名
    direction_column_id: str | None = None  # single_by_source_direction 模式下的源方向列

    def __post_init__(self):
        if self.mode not in VALID_SPLIT_MODES:
            raise ValueError(f"不支持的模式: {self.mode}，可选: {', '.join(VALID_SPLIT_MODES)}")
        if self.mode == "two_column":
            if not self.debit_field or not self.credit_field:
                raise ValueError("two_column 模式必须提供 debit_field 和 credit_field")
            if self.amount_field:
                raise ValueError("two_column 模式不应提供 amount_field")
        else:
            if not self.amount_field:
                raise ValueError(f"{self.mode} 模式必须提供 amount_field")
            if self.debit_field or self.credit_field:
                raise ValueError(f"{self.mode} 模式不应提供 debit_field/credit_field")


@dataclass
class RowInput:
    """待转换的原始行输入"""
    row_index: int
    client_account_code: str | None = None
    client_account_name: str | None = None
    indent_level: int | None = None
    values: dict[str, Any] = field(default_factory=dict)
    amount_configs: list[AmountConfig] = field(default_factory=list)
    standard_direction: str | None = None  # 该行目标标准科目余额方向


@dataclass
class TransformResult:
    """转换后的单行结果"""
    row_index: int
    client_account_code: str | None = None
    client_account_name: str | None = None
    original_indent: int | None = None

    # 层级
    level: int | None = None
    parent_key: str | None = None  # 父级的科目代码（有代码时）或 parent_row_index 字符串
    is_leaf: bool = False
    is_summary: bool = False  # 有子级的父级行
    level_source: str = "flat"  # code_prefix | indent_suggested | flat

    # 金额六列
    opening_debit: Decimal = field(default_factory=lambda: Decimal("0"))
    opening_credit: Decimal = field(default_factory=lambda: Decimal("0"))
    current_debit: Decimal = field(default_factory=lambda: Decimal("0"))
    current_credit: Decimal = field(default_factory=lambda: Decimal("0"))
    ending_debit: Decimal = field(default_factory=lambda: Decimal("0"))
    ending_credit: Decimal = field(default_factory=lambda: Decimal("0"))

    # 问题
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class BatchTransformResult:
    """批量转换结果"""
    rows: list[TransformResult]
    global_warnings: list[str] = field(default_factory=list)
    global_errors: list[str] = field(default_factory=list)


# ── 工具函数 ───────────────────────────────────────

def _safe_decimal(value: Any) -> Decimal | None:
    """安全转换为 Decimal"""
    if value is None or value == "" or value == "None":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        s = str(value).replace(",", "").replace("，", "").strip()
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    """安全转换为 int"""
    if value is None or value == "" or value == "None":
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


# ── 层级识别 ───────────────────────────────────────

def _find_direct_parent_code(code: str, all_codes: set[str]) -> str | None:
    """在已有代码集中找到 code 的最长前缀（存在且不等于自身）。
    
    TASK-081 优化：从末尾逐步缩短代码，用 set 查找，O(len(code)) 替代 O(n)。
    """
    # 从末尾逐步缩短，找到最短前缀命中
    for end in range(len(code) - 1, 0, -1):
        candidate = code[:end]
        if candidate in all_codes and candidate != code:
            return candidate
    return None


def _is_parent_of_any(code: str, all_codes: set[str]) -> bool:
    """判断 code 是否是 all_codes 中某个代码的前缀。
    
    TASK-081 优化：按长度分段，优先查短代码；预排序避免全量扫描。
    """
    # 仅检查长度大于 code 的代码（作为前缀，子级一定更长）
    if not hasattr(_is_parent_of_any, "_sorted_codes"):
        return _is_parent_of_any_linear(code, all_codes)
    for other in _is_parent_of_any._sorted_codes:
        if len(other) <= len(code):
            continue
        if other.startswith(code):
            return True
        # 由于排序，一旦 other 的 prefix 不匹配，后续也不会匹配
        if other > code:
            break
    return False


def _is_parent_of_any_linear(code: str, all_codes: set[str]) -> bool:
    """fallback 线性扫描"""
    for other in all_codes:
        if other != code and other.startswith(code):
            return True
    return False


def detect_hierarchy_by_code(
    rows: list[RowInput],
) -> tuple[
    list[dict],  # per-row hierarchy info
    list[str],   # warnings
]:
    """
    按科目代码前缀推断层级。

    规则：
    - 有代码的行按前缀匹配找父级。
    - 没有其他代码以该代码为前缀 → 末级（is_leaf=True）。
    - 有其他代码以该代码为前缀 → 父级（is_summary=True）。
    - 有代码但找不到父级前缀 → level=1。
    - 无代码的行暂时保留 level=None，后续由其他策略填充。

    返回：
        hierarchy: list[dict] 附带 level, parent_key, is_leaf, is_summary
        warnings: list[str]
    """
    # 收集所有有代码的行
    code_to_row = {}
    for r in rows:
        if r.client_account_code:
            code = r.client_account_code.strip()
            if code in code_to_row:
                # 重复代码：后面的行可能被当作叶子候选
                pass
            code_to_row[code] = r

    all_codes = set(code_to_row.keys())
    # TASK-081：预排序代码集，加速 _is_parent_of_any
    _is_parent_of_any._sorted_codes = sorted(all_codes)
    warnings: list[str] = []

    results: list[dict] = []

    for r in rows:
        info = {
            "row_index": r.row_index,
            "level": None,
            "parent_key": None,
            "is_leaf": True,
            "is_summary": False,
            "level_source": "flat",
        }

        code = r.client_account_code.strip() if r.client_account_code else ""

        if not code:
            # 无代码，留给缩进或平铺策略
            results.append(info)
            continue

        if code not in all_codes:
            results.append(info)
            continue

        # 找父级
        parent_code = _find_direct_parent_code(code, all_codes)

        # 计算层级：遍历祖先链，level = ancestor_count + 1
        if parent_code:
            ancestor_count = 1  # 至少有一个父级
            current = parent_code
            while current:
                grandparent = _find_direct_parent_code(current, all_codes)
                if grandparent:
                    ancestor_count += 1
                    current = grandparent
                else:
                    break
            info["level"] = ancestor_count + 1
            info["parent_key"] = parent_code
        else:
            info["level"] = 1
            info["parent_key"] = None

        # 是否有子级（以该代码为前缀的其他代码）
        has_children = _is_parent_of_any(code, all_codes)
        if has_children:
            info["is_leaf"] = False
            info["is_summary"] = True
        else:
            info["is_leaf"] = True
            info["is_summary"] = False

        info["level_source"] = "code_prefix"

        results.append(info)

    return results, warnings


def detect_hierarchy_by_indent(
    rows: list[RowInput],
) -> tuple[list[dict], list[str]]:
    """
    按 Excel 缩进生成建议层级。

    规则：
    - 有 indent_level 的行按缩进深度生成 suggested_level = indent_level + 1。
    - 缩进相邻的行，后一行如果缩进更深则前一行是父级（is_summary=True）。
    - 最后一层缩进行的下一行要么缩进更浅要么是结尾 → 标记 is_leaf。
    - level_source = "indent_suggested" 需要用户确认。

    注意：只处理 indent_level 不为 None 的行；其他行 level 保留 None。
    """
    results: list[dict] = []
    warnings: list[str] = []

    # 收集所有有缩进的行
    indexed_rows = [(i, r) for i, r in enumerate(rows) if r.indent_level is not None]
    if not indexed_rows:
        for r in rows:
            results.append({
                "row_index": r.row_index,
                "level": None,
                "parent_key": None,
                "is_leaf": True,
                "is_summary": False,
                "level_source": "flat",
            })
        return results, warnings

    for idx, row in enumerate(rows):
        info = {
            "row_index": row.row_index,
            "level": None,
            "parent_key": None,
            "is_leaf": True,
            "is_summary": False,
            "level_source": "flat",
        }

        if row.indent_level is None:
            results.append(info)
            continue

        suggested_level = row.indent_level + 1
        info["level"] = suggested_level
        info["level_source"] = "indent_suggested"

        # 找缩进父级：往前面找第一行 indent_level 更浅的
        parent_idx = None
        for j in range(idx - 1, -1, -1):
            prev_row = rows[j]
            if prev_row.indent_level is not None and prev_row.indent_level < row.indent_level:
                parent_idx = prev_row.row_index
                break

        if parent_idx is not None:
            info["parent_key"] = str(parent_idx)

        # 判断是否有子级：向后找下一行缩进更深
        has_child = False
        for j in range(idx + 1, len(rows)):
            next_row = rows[j]
            if next_row.indent_level is not None:
                if next_row.indent_level > row.indent_level:
                    has_child = True
                break

        if has_child:
            info["is_leaf"] = False
            info["is_summary"] = True
        else:
            info["is_leaf"] = True
            info["is_summary"] = False

        results.append(info)

    return results, warnings


def assign_flat_hierarchy(
    rows: list[RowInput],
) -> list[dict]:
    """
    无代码无缩进时使用平铺策略：所有有数据的行均为末级（level=1, is_leaf=True）。
    """
    results: list[dict] = []
    for r in rows:
        results.append({
            "row_index": r.row_index,
            "level": 1,
            "parent_key": None,
            "is_leaf": True,
            "is_summary": False,
            "level_source": "flat",
        })
    return results


def merge_hierarchy(
    code_results: list[dict],
    indent_results: list[dict] | None,
    flat_results: list[dict] | None,
) -> list[dict]:
    """
    合并层级策略结果：代码前缀优先 > 缩进建议 > 平铺。

    对有代码的行使用 code_results，否则有缩进则用 indent_results，
    否则用 flat_results。
    """
    n = len(code_results)
    merged: list[dict] = []

    for i in range(n):
        cr = code_results[i]
        # 如果代码层级已被识别到，用它
        if cr["level"] is not None and cr["level_source"] == "code_prefix":
            merged.append(cr)
        elif indent_results and i < len(indent_results) and indent_results[i]["level"] is not None:
            merged.append(indent_results[i])
        elif flat_results and i < len(flat_results):
            merged.append(flat_results[i])
        else:
            # fallback to flat
            merged.append({
                "row_index": cr["row_index"],
                "level": 1,
                "parent_key": None,
                "is_leaf": True,
                "is_summary": False,
                "level_source": "flat",
            })

    return merged


# ── 父级金额校验 ──────────────────────────────────────

def validate_parent_amounts(
    rows: list[TransformResult],
    hierarchy: list[dict],
) -> list[str]:
    """
    校验父级金额与子级末级汇总是否一致。

    对每个标记为 is_summary=True 的父级行：
    - 递归收集全部后代末级（包括孙级及更深层）。
    - 本期借贷发生额按借方/贷方分别比较。
    - 期初/期末余额按借贷净额（借方 - 贷方）比较，避免借贷双列分别比较的误报。

    返回全局 warnings 列表。
    """
    warnings: list[str] = []

    # 构建索引
    row_map: dict[int, TransformResult] = {r.row_index: r for r in rows}
    hier_map: dict[int, dict] = {}
    for h in hierarchy:
        hier_map[h["row_index"]] = h

    # 收集父级 → 子级映射
    parent_to_children: dict[int, list[int]] = defaultdict(list)
    for h in hierarchy:
        pk = h.get("parent_key")
        if pk is not None:
            parent_row = None
            for r in rows:
                if r.client_account_code and r.client_account_code.strip() == pk:
                    parent_row = r.row_index
                    break
            if parent_row is None:
                try:
                    parent_row = int(pk)
                except (ValueError, TypeError):
                    parent_row = None
            if parent_row is not None:
                parent_to_children[parent_row].append(h["row_index"])

    # 递归收集全部后代末级
    def _collect_descendant_leaf_indices(parent_idx: int) -> list[int]:
        leaf_indices: list[int] = []
        stack = list(parent_to_children.get(parent_idx, []))
        while stack:
            idx = stack.pop(0)
            h = hier_map.get(idx, {})
            if h.get("is_leaf", True):
                leaf_indices.append(idx)
            else:
                stack.extend(parent_to_children.get(idx, []))
        return leaf_indices

    def _signed_balance(debit: Decimal, credit: Decimal) -> Decimal:
        return debit - credit

    # 校验每个父级
    for parent_row_idx, child_indices in parent_to_children.items():
        if not child_indices:
            continue
        parent_row = row_map.get(parent_row_idx)
        if not parent_row:
            continue

        # 递归收集全部后代末级
        all_leaf_indices = _collect_descendant_leaf_indices(parent_row_idx)
        leaf_children = [row_map[idx] for idx in all_leaf_indices if idx in row_map]

        if not leaf_children:
            continue

        eps = Decimal("0.01")

        # ── 期初/期末按借贷净额比较 ──
        parent_opening_net = _signed_balance(parent_row.opening_debit, parent_row.opening_credit)
        child_opening_net = sum((_signed_balance(c.opening_debit, c.opening_credit) for c in leaf_children), Decimal("0"))
        diff_opening = abs(parent_opening_net - child_opening_net)
        if diff_opening > eps:
            warnings.append(
                f"行 {parent_row_idx}「{parent_row.client_account_name or parent_row.client_account_code or '未知'}」"
                f"父级期初净额 {parent_opening_net} 与全部后代末级净额汇总 {child_opening_net} 不一致（差 {diff_opening}）"
            )

        parent_ending_net = _signed_balance(parent_row.ending_debit, parent_row.ending_credit)
        child_ending_net = sum((_signed_balance(c.ending_debit, c.ending_credit) for c in leaf_children), Decimal("0"))
        diff_ending = abs(parent_ending_net - child_ending_net)
        if diff_ending > eps:
            warnings.append(
                f"行 {parent_row_idx}「{parent_row.client_account_name or parent_row.client_account_code or '未知'}」"
                f"父级期末净额 {parent_ending_net} 与全部后代末级净额汇总 {child_ending_net} 不一致（差 {diff_ending}）"
            )

        # ── 本期发生额仍按借方/贷方分别比较 ──
        sum_current_debit = sum((c.current_debit for c in leaf_children), Decimal("0"))
        sum_current_credit = sum((c.current_credit for c in leaf_children), Decimal("0"))
        diff_cd = abs(parent_row.current_debit - sum_current_debit)
        diff_cc = abs(parent_row.current_credit - sum_current_credit)
        if diff_cd > eps:
            warnings.append(
                f"行 {parent_row_idx}「{parent_row.client_account_name or parent_row.client_account_code or '未知'}」"
                f"父级本期借方发生额 {parent_row.current_debit} 与全部后代末级汇总 {sum_current_debit} 不一致（差 {diff_cd}）"
            )
        if diff_cc > eps:
            warnings.append(
                f"行 {parent_row_idx}「{parent_row.client_account_name or parent_row.client_account_code or '未知'}」"
                f"父级本期贷方发生额 {parent_row.current_credit} 与全部后代末级汇总 {sum_current_credit} 不一致（差 {diff_cc}）"
            )

    return warnings


# ── 金额拆分 ────────────────────────────────────────

def _split_single_amount(
    amount: Decimal,
    direction: str | None,
    split_mode: str,
    source_direction: str | None = None,
) -> tuple[Decimal, Decimal, list[str], list[str]]:
    """
    将单个金额按 split_mode 拆成 (debit, credit)。

    Args:
        amount: 原始金额
        direction: 标准科目余额方向（debit/credit/None）
        split_mode: single_by_direction / single_by_source_direction / single_as_debit / single_as_credit
        source_direction: 源表方向列的值（single_by_source_direction 模式专用）

    Returns:
        (debit, credit, warnings, errors)
    """
    warnings: list[str] = []
    errors: list[str] = []

    if amount == Decimal("0"):
        return Decimal("0"), Decimal("0"), warnings, errors

    if split_mode == "single_by_source_direction":
        # 按源表方向列的值拆借贷
        sd = (source_direction or "").strip()
        sd_lower = sd.lower()
        # 借方方向
        if sd in ("借", "借方", "debit", "dr") or sd_lower in ("debit", "dr"):
            if amount > 0:
                return amount, Decimal("0"), warnings, errors
            else:
                # 负数在借方列 = 实际是贷方，会计系统中常见，不产生 warning
                return Decimal("0"), abs(amount), warnings, errors
        # 贷方方向
        elif sd in ("贷", "贷方", "credit", "cr") or sd_lower in ("credit", "cr"):
            if amount > 0:
                return Decimal("0"), amount, warnings, errors
            else:
                # 负数在贷方列 = 实际是借方
                return abs(amount), Decimal("0"), warnings, errors
        # 平 / 空方向
        elif sd == "" or sd == "平" or sd_lower in ("flat", "balanced"):
            # 平且金额非零 → warning
            if amount != Decimal("0"):
                warnings.append(f"源方向为「平」但金额非零 {amount}，按借方处理")
                return amount, Decimal("0"), warnings, errors
            else:
                return Decimal("0"), Decimal("0"), warnings, errors
        else:
            errors.append(f"无法识别的源方向值 '{sd}'，请手动指定借/贷方")
            return Decimal("0"), Decimal("0"), warnings, errors

    elif split_mode == "single_as_debit":
        if amount > 0:
            return amount, Decimal("0"), warnings, errors
        else:
            # 负数金额在会计中是正常现象（红字冲销/调整分录），按绝对值进贷方
            return Decimal("0"), abs(amount), warnings, errors

    elif split_mode == "single_as_credit":
        if amount > 0:
            return Decimal("0"), amount, warnings, errors
        else:
            # 负数金额在会计中是正常现象（红字冲销/调整分录），按绝对值进借方
            return abs(amount), Decimal("0"), warnings, errors

    elif split_mode == "single_by_direction":
        if direction is None:
            errors.append("标准科目余额方向缺失，无法按标准方向拆分，请手动指定借/贷方")
            return Decimal("0"), Decimal("0"), warnings, errors

        if direction == "debit":
            if amount > 0:
                return amount, Decimal("0"), warnings, errors
            else:
                # 负数金额在会计中是正常现象，按绝对值拆分到贷方
                return Decimal("0"), abs(amount), warnings, errors
        elif direction == "credit":
            if amount > 0:
                return Decimal("0"), amount, warnings, errors
            else:
                # 负数金额在会计中是正常现象，按绝对值拆分到借方
                return abs(amount), Decimal("0"), warnings, errors
        else:
            errors.append(f"标准科目余额方向 '{direction}' 无效")
            return Decimal("0"), Decimal("0"), warnings, errors

    else:
        errors.append(f"不支持的拆分模式: {split_mode}")
        return Decimal("0"), Decimal("0"), warnings, errors


def transform_amounts(
    rows: list[RowInput],
) -> tuple[list[TransformResult], list[str], list[str]]:
    """
    对每行按 amount_configs 映射拆分金额到标准借贷六列。

    支持：
    - two_column：直接从 values 读 debit_field/credit_field 的值
    - single_*：从 values 读 amount_field 再按方向拆分

    Returns:
        (results, global_warnings, global_errors)
    """
    results: list[TransformResult] = []
    global_warnings: list[str] = []
    global_errors: list[str] = []

    for row in rows:
        result = TransformResult(
            row_index=row.row_index,
            client_account_code=row.client_account_code,
            client_account_name=row.client_account_name,
            original_indent=row.indent_level,
        )

        if not row.amount_configs:
            # 没有配置，假设已经是完整的六列
            v = row.values
            result.opening_debit = _safe_decimal(v.get("opening_debit")) or Decimal("0")
            result.opening_credit = _safe_decimal(v.get("opening_credit")) or Decimal("0")
            result.current_debit = _safe_decimal(v.get("current_debit")) or Decimal("0")
            result.current_credit = _safe_decimal(v.get("current_credit")) or Decimal("0")
            result.ending_debit = _safe_decimal(v.get("ending_debit")) or Decimal("0")
            result.ending_credit = _safe_decimal(v.get("ending_credit")) or Decimal("0")
            results.append(result)
            continue

        # 按配置逐期间处理
        for cfg in row.amount_configs:
            period = cfg.period_type

            if cfg.mode == "two_column":
                debit_val = _safe_decimal(row.values.get(cfg.debit_field or "")) or Decimal("0")
                credit_val = _safe_decimal(row.values.get(cfg.credit_field or "")) or Decimal("0")

                if period == "opening":
                    result.opening_debit = debit_val
                    result.opening_credit = credit_val
                elif period == "current":
                    result.current_debit = debit_val
                    result.current_credit = credit_val
                elif period == "ending":
                    result.ending_debit = debit_val
                    result.ending_credit = credit_val

            else:
                # 单列金额拆分
                raw_amount_val = row.values.get(cfg.amount_field or "")
                # 空金额（None / 空字符串 / 纯空白）按 0 处理，不产生 warning
                if raw_amount_val is None or (isinstance(raw_amount_val, str) and raw_amount_val.strip() == ""):
                    raw_amount = Decimal("0")
                else:
                    raw_amount = _safe_decimal(raw_amount_val)
                    if raw_amount is None:
                        w = f"行 {row.row_index} 期间 {period} 金额字段 '{cfg.amount_field}' 无法解析为数字"
                        result.warnings.append(w)
                        continue

                # 获取源方向列的值（single_by_source_direction 模式）
                source_dir = None
                if cfg.mode == "single_by_source_direction" and cfg.direction_column_id:
                    source_dir_val = row.values.get(cfg.direction_column_id)
                    source_dir = str(source_dir_val).strip() if source_dir_val is not None else ""

                debit, credit, wlist, elist = _split_single_amount(
                    raw_amount, row.standard_direction, cfg.mode, source_direction=source_dir,
                )

                result.warnings.extend(wlist)
                result.errors.extend(elist)

                if period == "opening":
                    result.opening_debit = debit
                    result.opening_credit = credit
                elif period == "current":
                    result.current_debit = debit
                    result.current_credit = credit
                elif period == "ending":
                    result.ending_debit = debit
                    result.ending_credit = credit

        results.append(result)

    # ── 汇总错误和警告 ──
    for r in results:
        if r.warnings:
            for w in r.warnings:
                global_warnings.append(f"行 {r.row_index}: {w}")
        if r.errors:
            for e in r.errors:
                global_errors.append(f"行 {r.row_index}: {e}")

    return results, global_warnings, global_errors


# ── 总控函数 ────────────────────────────────────────

def transform_rows(
    rows: list[RowInput],
    hierarchy_mode: str = "auto",
) -> BatchTransformResult:
    """
    全流程转换：层级识别 + 金额拆分 + 父级校验。

    Args:
        rows: 原始行输入列表
        hierarchy_mode: "auto" (自动选择策略) | "code" | "indent" | "flat"

    Returns:
        BatchTransformResult 包含转换结果、警告、错误
    """
    all_warnings: list[str] = []
    all_errors: list[str] = []

    # ── 步骤1: 层级识别 ──
    code_hier, cw = detect_hierarchy_by_code(rows)
    all_warnings.extend(cw)

    indent_hier, iw = detect_hierarchy_by_indent(rows)
    all_warnings.extend(iw)

    flat_hier = assign_flat_hierarchy(rows)

    if hierarchy_mode == "code":
        merged_hier = code_hier
    elif hierarchy_mode == "indent":
        merged_hier = indent_hier
    elif hierarchy_mode == "flat":
        merged_hier = flat_hier
    else:
        # auto: 代码前缀优先 > 缩进建议 > 平铺
        merged_hier = merge_hierarchy(code_hier, indent_hier, flat_hier)

    # ── 步骤2: 金额拆分 ──
    results, tw, te = transform_amounts(rows)
    all_warnings.extend(tw)
    all_errors.extend(te)

    # ── 步骤3: 将层级信息写入 results ──
    for i, result in enumerate(results):
        if i < len(merged_hier):
            h = merged_hier[i]
            result.level = h["level"]
            result.parent_key = h["parent_key"]
            result.is_leaf = h["is_leaf"]
            result.is_summary = h["is_summary"]
            result.level_source = h["level_source"]

    # ── 步骤4: 父级金额校验 ──
    parent_warnings = validate_parent_amounts(results, merged_hier)
    all_warnings.extend(parent_warnings)

    return BatchTransformResult(
        rows=results,
        global_warnings=all_warnings,
        global_errors=all_errors,
    )


# ── 便捷函数 ────────────────────────────────────────

def get_leaf_rows(
    batch_result: BatchTransformResult,
) -> list[TransformResult]:
    """从批量结果中提取末级叶子行"""
    return [r for r in batch_result.rows if r.is_leaf and not r.is_summary]


def get_summary_rows(
    batch_result: BatchTransformResult,
) -> list[TransformResult]:
    """从批量结果中提取汇总父级行"""
    return [r for r in batch_result.rows if r.is_summary]


def has_blocking_errors(batch_result: BatchTransformResult) -> bool:
    """是否有阻止入库的错误"""
    return len(batch_result.global_errors) > 0
