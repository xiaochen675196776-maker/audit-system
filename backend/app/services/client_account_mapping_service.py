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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Literal

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_account_mapping import ClientAccountMapping
from app.models.standard_account import StandardAccount


# ── TASK-087：统一名称兼容性评估结果 ────────────────────


@dataclass
class CompatibilityResult:
    """客户科目名称与标准科目的语义兼容性判定结果。"""
    status: Literal["compatible", "conflict", "unknown"]
    reason: str
    evidence: list[str] = field(default_factory=list)
    detected_group: str | None = None


# ── 旧科目编码→新标准科目编码 crosswalk ──────────────
# 用于老账套/老准则科目编码体系映射到当前标准科目。
# key: 旧编码（可能带点分层级，取第一段/前缀匹配）
# value: 应映射到的标准科目代码
_OLD_CODE_CROSSWALK: dict[str, str] = {
    # 资产类
    "101": "1001",    # 现金 → 库存现金
    "102": "1002",    # 银行存款 → 银行存款
    "109": "1012",    # 其他货币资金 → 其他货币资金
    "1009": "1012",   # 其他货币资金（含基金）→ 其他货币资金
    "111": "1101",    # 短期投资 → 交易性金融资产
    "1111": "112101", # 应收票据 → 应收票据
    "112": "112101",  # 应收票据 → 应收票据
    "113": "112201",  # 应收账款 → 应收账款
    "1131": "112201", # 应收账款 → 应收账款
    "114": "112402",  # 坏账准备 → 坏账准备（应收账款）
    "115": "112401",  # 预付账款 → 预付款项
    "1151": "112401", # 预付账款 → 预付款项
    "119": "122101",  # 其他应收款 → 其他应收款
    "121": "1403",    # 材料采购 → 原材料（或材料采购）
    "122": "1403",    # 在途物资 → 原材料
    "123": "1403",    # 原材料 → 原材料
    "1231": "122102", # 坏账准备 → 减：其他应收款-坏账准备（按客户用途归入）
    "124": "1405",    # 库存商品 → 库存商品
    "128": "141101",  # 包装物 → 包装物
    "129": "141102",  # 低值易耗品 → 低值易耗品
    "131": "140601",  # 半成品 → 半成品
    "137": "1405",    # 产成品 → 库存商品
    "139": "147101",  # 存货跌价准备 → 存货-资产减值损失
    "141": "1901",    # 待摊费用 → 其他流动资产
    "151": "151101",  # 长期股权投资 → 长期股权投资-原值
    "161": "160101",  # 固定资产 → 固定资产原值
    "165": "1602",    # 累计折旧 → 累计折旧
    "1651": "164101", # 使用权资产 → 使用权资产-原值（客户用 1651 体系）
    "169": "160401",  # 在建工程 → 在建工程-原值
    "171": "170101",  # 无形资产 → 无形资产-原值
    "181": "1801",    # 长期待摊费用 → 长期待摊费用
    "1802": "1801",   # 长期待摊费用（软件等）→ 长期待摊费用
    "1807": "1811",   # 递延所得税资产
    "191": "1902",    # 其他非流动资产 → 其他非流动资产
    # 负债类
    "201": "2001",    # 短期借款 → 短期借款
    "202": "2201",    # 应付票据 → 应付票据
    "203": "2202",    # 应付账款 → 应付账款
    "204": "2203",    # 预收账款 → 预收款项
    "209": "2241",    # 其他应付款 → 其他应付款
    "211": "2211",    # 应付工资 → 应付职工薪酬
    "2121": "2211",   # 应付福利费 → 应付职工薪酬
    "2131": "2241",   # 其他应交款 → 其他应付款
    "214": "2221",    # 应交税金 → 应交税费
    "2171": "2221",   # 应交税费
    "221": "2501",    # 长期借款 → 长期借款
    "223": "2701",    # 应付债券 → 长期应付款
    "229": "2241",    # 其他长期负债 → 其他应付款
    # 权益类
    "301": "4001",    # 实收资本 → 股本（实收资本）
    "311": "4003",    # 资本公积 → 资本公积
    "312": "4101",    # 盈余公积 → 盈余公积
    "313": "4101",    # 公益金 → 盈余公积
    "321": "4103",    # 本年利润 → 未分配利润
    "322": "4105",    # 利润分配 → 利润分配
    # 成本类
    "401": "5001",    # 生产成本 → 生产成本
    "405": "5101",    # 制造费用 → 制造费用
    # 损益类
    "501": "6001",    # 产品销售收入 → 主营业务收入
    "502": "6401",    # 产品销售成本 → 主营业务成本
    "503": "6602",    # 产品销售费用/其他费用 → 管理费用
    "504": "6602",    # 管理费用 → 管理费用
    "511": "6051",    # 其他业务收入 → 其他业务收入
    "512": "6402",    # 其他业务支出 → 其他业务成本
    "521": "6602",    # 管理费用/研发费用明细 → 结合父级路径
    "522": "6601",    # 销售费用 → 销售费用
    "531": "6111",    # 投资收益 → 投资收益
    "541": "6301",    # 营业外收入 → 营业外收入
    "542": "6711",    # 营业外支出 → 营业外支出
    "550": "6801",    # 所得税 → 所得税费用
    "560": "6901",    # 以前年度损益调整 → 以前年度损益调整
    # 费用明细类（常见明细科目代码段）
    "4107": "660201", # 研发费用明细 → 研发费用
    "6121": "6117",   # 其他收益相关 → 其他收益
    "2132": "2241",   # 其他应付款明细（保证金等）
    "2151": "2211",   # 应付职工薪酬明细
    "2181": "2241",   # 其他应付款明细（个人往来等）
    "5407": "6401",   # 主营业务成本明细
    "5701": "6801",   # 所得税费用明细
    # 研发支出/费用相关
    "5301": "660201",  # 研发支出/研发费用 → 研发费用
}

# ── 泛化叶子名（不能仅凭名称匹配，必须结合父级路径） ──
_GENERIC_LEAF_NAMES: set[str] = {
    "工资", "职工福利", "福利费", "社保", "公积金", "工会经费", "职工教育经费",
    "折旧费", "摊销费", "材料费", "水电费", "办公费", "差旅费", "交通费",
    "业务招待费", "通讯费", "租赁费", "修理费", "保险费", "聘请中介机构费",
    "咨询费", "诉讼费", "排污费", "绿化费", "税金", "其他费用", "其他",
    "检测费", "试验检验费", "委托外部研究开发费用",
    "行政管理类", "生产经营类",
    "充电场站", "办公租赁",
    "职工薪酬", "劳务费", "运输费", "装卸费", "包装费", "广告费",
}


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
    # TASK-088：alias 必须在分词边界上匹配（作为完整 token 或开头），避免 "保证金" 误命中 "其他应付款_保证金"
    for group_key, group_def in _SEMANTIC_ACCOUNT_GROUPS.items():
        for alias in group_def.get("client_aliases", []):
            alias_norm = _normalize_name(alias)
            if not alias_norm:
                continue
            # 检查是否作为完整 token 出现或出现在名称开头
            if alias_norm in all_token_norms:
                return group_key
            if norm.startswith(alias_norm):
                return group_key
    return None


def _standard_account_matches_semantic_group(sa: StandardAccount, group_key: str) -> bool:
    """检查标准科目是否命中指定语义组（None/True 视为启用，仅 False 时拒绝）。"""
    if sa.is_active is False:
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


# ── TASK-087：统一名称语义兼容性评估器 ──────────────────

def evaluate_name_compatibility(
    standard_account: StandardAccount,
    *,
    client_account_name: str | None,
    parent_client_account_name: str | None = None,
    ancestor_names: list[str] | None = None,
    client_account_full_path: str | None = None,
) -> CompatibilityResult:
    """统一评估客户科目名称与标准科目的语义兼容性。

    所有候选源（code_match / crosswalk / parent_inherited / code_category_anchor 等）
    必须通过此评估器后才能判定为安全候选。禁止各来源各自实现零散冲突判断。

    返回 CompatibilityResult: compatible / conflict / unknown
    """
    evidence: list[str] = []

    # ── 构建客户名称上下文 ──
    client_norm = _normalize_name(client_account_name)
    parent_norm = _normalize_name(parent_client_account_name)
    ancestor_norms = [_normalize_name(a) for a in (ancestor_names or [])]
    path_norm = _normalize_name(client_account_full_path)
    # TASK-088：完整路径语义分析（用于辅助判断—当当前名称缺失上下文时提供兜底）
    path_group = _detect_semantic_group(client_account_full_path) if client_account_full_path else None
    path_anchor = _detect_name_anchor(client_account_full_path) if client_account_full_path else None
    path_is_reserve = _has_negative_reserve_semantics(client_account_full_path) if client_account_full_path else False
    if client_account_full_path:
        evidence.append(f"full_path={client_account_full_path}")
    if path_group:
        evidence.append(f"path_semantic_group={path_group}")
    evidence.append(f"client_name={client_account_name or '(空)'}")

    # ── 规则 0：客户端名称缺失 ──
    if not client_norm:
        return CompatibilityResult(
            status="unknown",
            reason="客户科目名称为空，无法进行名称语义兼容性判断",
            evidence=evidence,
        )

    # ── 构建标准科目信息 ──
    sa_name = standard_account.account_name or ""
    sa_code = standard_account.account_code or ""
    sa_canonical = _canonical_name(sa_name)
    sa_norm = _normalize_name(sa_name)

    evidence.append(f"standard={sa_code} {sa_name}")

    # ── 规则 1：名称规范化后完全一致 ──
    # 但标准名称含「减：/加：/其中：」时不视为精确一致（需人工确认）
    if client_norm == sa_norm:
        # 检查标准名称是否带显示前缀
        for pfx in _STANDARD_NAME_DISPLAY_PREFIXES:
            if pfx and sa_name.lstrip().startswith(pfx):
                return CompatibilityResult(
                    status="unknown",
                    reason=f"名称一致但标准科目带显示前缀「{pfx}」，需人工确认经济含义",
                    evidence=evidence,
                )
        return CompatibilityResult(
            status="compatible",
            reason="客户科目名称与标准科目名称完全一致",
            evidence=evidence,
        )

    # ── 规则 2：客户名称过于泛化，无法判断 ──
    generic_norm = {_normalize_name(n) for n in _GENERIC_LEAF_NAMES}
    # 规则2增强：完整路径可提供上下文，避免泛化名草率退回unknown
    if client_norm in generic_norm and not parent_norm and not ancestor_norms and not path_group:
        return CompatibilityResult(
            status="unknown",
            reason=f"客户名称「{client_account_name}」过于泛化且无父级上下文，无法判断兼容性",
            evidence=evidence,
        )

    # ── 规则 3：语义组检测 ──
    client_group = _detect_semantic_group(client_account_name)
    # 也尝试用父级名称检测语义组
    parent_group = _detect_semantic_group(parent_client_account_name) if parent_client_account_name else None
    # 用祖先名称检测语义组
    ancestor_groups: list[str] = []
    for anc_name in (ancestor_names or []):
        g = _detect_semantic_group(anc_name)
        if g and g not in ancestor_groups:
            ancestor_groups.append(g)

    effective_group = (
        client_group
        or parent_group
        or (ancestor_groups[0] if ancestor_groups else None)
        or path_group
    )

    if effective_group:
        evidence.append(f"semantic_group={effective_group}")
        # TASK-088：标记语义组来源（当前名称 → 父级 → 最近祖先 → 完整路径）
        nearest_ancestor_group = ancestor_groups[0] if ancestor_groups else None
        if effective_group == path_group and not (client_group or parent_group or nearest_ancestor_group):
            evidence.append("semantic_group_from=full_path")
        # 检查标准科目是否属于同一语义组
        if _standard_account_matches_semantic_group(standard_account, effective_group):
            reason = f"客户科目语义组「{effective_group}」与标准科目一致"
            if effective_group == path_group and not (client_group or parent_group or nearest_ancestor_group):
                reason = f"当前名称泛化，依据完整科目路径识别为语义组「{effective_group}」"
            return CompatibilityResult(
                status="compatible",
                reason=reason,
                evidence=evidence,
                detected_group=effective_group,
            )
        # 检查标准科目是否冲突
        if _standard_account_conflicts_semantic_group(standard_account, effective_group):
            return CompatibilityResult(
                status="conflict",
                reason=f"客户科目属于语义组「{effective_group}」，但标准科目属于冲突类别",
                evidence=evidence,
                detected_group=effective_group,
            )

    # ── 规则 4：备抵/减值冲突检测 ──
    sa_is_reserve = _has_negative_reserve_semantics(sa_name)
    client_is_reserve = _has_negative_reserve_semantics(client_account_name)
    # TASK-088：完整路径中的备抵语义可作为辅助证据
    effective_client_is_reserve = client_is_reserve or path_is_reserve
    if path_is_reserve and not client_is_reserve:
        evidence.append("reserve_context_from=full_path")
    if sa_is_reserve and not effective_client_is_reserve:
        return CompatibilityResult(
            status="conflict",
            reason=f"标准科目「{sa_code} {sa_name}」是备抵/减值类，但客户名称无减值语义",
            evidence=evidence,
        )
    if effective_client_is_reserve and not sa_is_reserve:
        return CompatibilityResult(
            status="conflict",
            reason=f"客户名称含备抵/减值语义，但标准科目「{sa_code} {sa_name}」是原值/非备抵类",
            evidence=evidence,
        )
    # TASK-088：双方均有备抵语义（含路径提供）且上下文一致 → 兼容
    if effective_client_is_reserve and sa_is_reserve:
        evidence.append("reserve_semantics=match")
        return CompatibilityResult(
            status="compatible",
            reason=f"客户科目与标准科目「{sa_code} {sa_name}」均有备抵/减值语义",
            evidence=evidence,
        )

    # ── 规则 5：名称锚点冲突检测 ──
    anchor = _detect_name_anchor(client_account_name)
    # TASK-088：当前名称无锚点时，回退到完整路径中的锚点
    if not anchor:
        anchor = path_anchor
        if anchor:
            evidence.append(f"path_anchor={anchor}")
    if anchor and sa_canonical:
        anchor_norm = _normalize_name(anchor)
        if anchor_norm and anchor_norm not in sa_canonical:
            # 锚点不在标准科目 canonical name 中 → 冲突
            return CompatibilityResult(
                status="conflict",
                reason=f"客户名称锚点「{anchor}」不在标准科目「{sa_name}」中",
                evidence=evidence,
            )

    # ── 规则 6：研发支出方向检测（费用化 vs 资本化） ──
    # TASK-088：完整路径中也参与研发方向判断
    rd_keyword_in_client = "研发支出" in client_norm or "研发费用" in client_norm
    rd_keyword_in_path = path_norm and ("研发支出" in path_norm or "研发费用" in path_norm)
    if rd_keyword_in_client or rd_keyword_in_path:
        client_tokens = _split_name_tokens(client_account_name or "")
        client_token_norms = [_normalize_name(t) for t in client_tokens]
        # 合并路径 token 提供额外上下文
        if path_norm and client_account_full_path:
            path_tokens = _split_name_tokens(client_account_full_path)
            client_token_norms.extend([_normalize_name(t) for t in path_tokens])
        has_expensing = any(t in client_token_norms for t in
                           [_normalize_name("费用化支出"), _normalize_name("费用化")])
        has_capitalizing = any(t in client_token_norms for t in
                               [_normalize_name("资本化支出"), _normalize_name("资本化")])
        if has_expensing and ("资本化支出" in sa_canonical or "资本化" in sa_canonical
                              or "660201" not in sa_code):
            # 客户是费用化，目标是资本化 → 冲突
            if "研发支出-资本化" in sa_canonical or "170401" in sa_code:
                return CompatibilityResult(
                    status="conflict",
                    reason="客户科目含费用化支出语义，目标为资本化支出，方向冲突",
                    evidence=evidence,
                )
        if has_capitalizing and ("费用化支出" in sa_canonical or "费用化" in sa_canonical
                                  or "660201" in sa_code):
            # 客户是资本化，目标是费用化 → 冲突
            if "研发支出-费用化" in sa_canonical or "170402" in sa_code:
                return CompatibilityResult(
                    status="conflict",
                    reason="客户科目含资本化支出语义，目标为费用化支出，方向冲突",
                    evidence=evidence,
                )
        # 研发支出无费用化/资本化上下文时 → unknown
        if not has_expensing and not has_capitalizing:
            if client_group is None and parent_group is None and path_group is None:
                if "研发支出" in client_norm and client_norm == _normalize_name("研发支出"):
                    return CompatibilityResult(
                        status="unknown",
                        reason="研发支出未明确费用化或资本化方向，需人工确认",
                        evidence=evidence,
                    )
            # 研发费用 客户名 vs 资本化支出 标准 → conflict without context
            if "研发费用" in client_norm and ("资本化" in sa_canonical or "170401" in sa_code):
                return CompatibilityResult(
                    status="conflict",
                    reason="客户为研发费用，目标为资本化支出，方向冲突",
                    evidence=evidence,
                )

    # ── 规则 7：父级/祖先上下文辅助判断 ──
    if parent_group and parent_group != effective_group:
        evidence.append(f"parent_group={parent_group}")
    if ancestor_groups:
        evidence.append(f"ancestor_groups={ancestor_groups}")

    # ── 规则 7.5：客户名称以标准名称开头（不含前缀后缀变化） ──
    # 例如"周转材料_在用"以"周转材料"开头，同时代码也一致 → compatible
    if client_account_name and sa_canonical:
        # 检查客户 canonical name 是否以标准 canonical name 开头
        client_canonical = _canonical_name(client_account_name)
        if client_canonical and sa_canonical and len(client_canonical) > len(sa_canonical):
            if client_canonical.startswith(sa_canonical):
                # 排除备抵冲突
                if _has_negative_reserve_semantics(sa_name) and not _has_negative_reserve_semantics(client_account_name):
                    return CompatibilityResult(
                        status="conflict",
                        reason=f"标准科目是备抵类，客户名称无减值语义",
                        evidence=evidence,
                    )
                return CompatibilityResult(
                    status="compatible",
                    reason=f"客户名称以标准科目名称开头（{sa_name}）",
                    evidence=evidence,
                )

    # ── 规则 8：无法判定 → unknown ──
    return CompatibilityResult(
        status="unknown",
        reason="无法确定名称语义兼容性，需人工确认",
        evidence=evidence,
    )


# ── TASK-085：标准科目内存索引 ──────────────────────────
# 避免大文件（如 205201 18984 唯一科目）逐次 select(StandardAccount) 全表扫描。
# recommend_mappings 入口一次性加载全部标准科目到内存，后续 _query_* 用纯 Python 过滤。
# 过滤逻辑与原 DB 查询完全等价，仅把"DB 全表扫描 + Python 过滤"换成"内存列表过滤"。


class _StandardAccountIndex:
    """标准科目内存索引：一次性加载后供各 _query_* 函数复用。

    索引维度（与各 _query_* 的过滤逻辑一一对应）：
      - all_accounts: 全部标准科目（含停用），供 code/name 精确、anchor、similarity、prefix 遍历
      - all_active: 仅启用标准科目，供 semantic_alias、name_prefix 遍历
      - by_norm_code: {normalized_code: [StandardAccount]}
      - by_norm_name: {normalized_name: [StandardAccount]}
    """

    __slots__ = ("all_accounts", "all_active", "by_norm_code", "by_norm_name",
                 "semantic_groups_by_sa_id", "negative_tokens_by_sa_id")

    def __init__(self, all_accounts: list[StandardAccount]):
        self.all_accounts = list(all_accounts)
        self.all_active = [sa for sa in all_accounts if sa.is_active]
        self.by_norm_code: dict[str, list[StandardAccount]] = {}
        self.by_norm_name: dict[str, list[StandardAccount]] = {}
        # TASK-087：预计算每个标准科目的语义组归属和备抵标记
        self.semantic_groups_by_sa_id: dict[str, list[str]] = {}
        self.negative_tokens_by_sa_id: dict[str, bool] = {}
        for sa in all_accounts:
            nc = _normalize_code(sa.account_code)
            if nc:
                self.by_norm_code.setdefault(nc, []).append(sa)
            nn = _normalize_name(sa.account_name)
            if nn:
                self.by_norm_name.setdefault(nn, []).append(sa)
            sa_id = str(sa.id)
            # 预计算语义组归属
            sa_groups = []
            for gk, gd in _SEMANTIC_ACCOUNT_GROUPS.items():
                if _standard_account_matches_semantic_group(sa, gk):
                    sa_groups.append(gk)
            if sa_groups:
                self.semantic_groups_by_sa_id[sa_id] = sa_groups
            # 预计算备抵标记
            self.negative_tokens_by_sa_id[sa_id] = _has_negative_reserve_semantics(sa.account_name)


async def _load_standard_account_index(db: AsyncSession) -> _StandardAccountIndex:
    """一次性加载全部标准科目到内存索引。"""
    result = await db.execute(select(StandardAccount))
    return _StandardAccountIndex(list(result.scalars().all()))


async def _query_semantic_alias_match(
    db: AsyncSession,
    group_key: str,
    sa_index: _StandardAccountIndex | None = None,
) -> list[StandardAccount]:
    """在标准科目表中查询命中语义组 standard_aliases 的启用科目。"""
    group_def = _SEMANTIC_ACCOUNT_GROUPS.get(group_key)
    if not group_def:
        return []
    # 查询所有启用标准科目，按名称 canonical 匹配
    if sa_index is not None:
        all_active = sa_index.all_active
    else:
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
    has_negatives = bool(group_def.get("negative_aliases", []))
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": 0.95,
        "source": "semantic_alias",
        "reason": f"语义别名匹配：客户「{client_name}」≈ 标准「{canonical}」",
        "warning": None,
        # TASK-087：增加统一兼容性字段
        "auto_confirmable": True,
        "compatibility_status": "compatible",
        "compatibility_reason": f"语义组「{group_key}」匹配",
        "evidence": [f"semantic_group={group_key}", f"canonical={canonical}",
                      f"negative_aliases_exist={has_negatives}"],
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

    # TASK-085：一次性加载全部标准科目到内存索引，避免逐次全表扫描
    sa_index = await _load_standard_account_index(db)

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
            code_matches = await _query_code_match(db, client_code, sa_index=sa_index)
            existing_ids = {c.get("standard_account_id") for c in entry["candidates"]}
            for sa in code_matches:
                if str(sa.id) in existing_ids:
                    continue
                candidate = _build_code_match_candidate(
                    sa, client_name,
                    parent_client_account_name=ca.get("parent_client_account_name"),
                    ancestor_names=ca.get("ancestor_names") or [],
                    client_account_full_path=ca.get("client_account_full_path"),
                )
                entry["candidates"].append(candidate)

        # ── 优先级 3b：标准科目名称精确匹配 ────
        if normalized_client_name:
            name_exact_matches = await _query_name_exact_match(db, client_name, sa_index=sa_index)
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
                semantic_matches = await _query_semantic_alias_match(db, group_key, sa_index=sa_index)
                existing_ids = {c.get("standard_account_id") for c in entry["candidates"]}
                for sa in semantic_matches:
                    if str(sa.id) in existing_ids:
                        continue
                    candidate = _build_semantic_alias_candidate(sa, group_key, client_name)
                    entry["candidates"].append(candidate)

        # ── 优先级 3c2：旧科目编码 crosswalk ──
        # TASK-080：老账套/老准则科目编码（如 101=现金, 502=产品销售成本）
        # 按静态映射表直接匹配到新标准科目。
        if normalized_client_code and not entry["candidates"]:
            crosswalk_code = _lookup_old_code_crosswalk(client_code)
            if crosswalk_code:
                crosswalk_matches = await _query_crosswalk_match(db, crosswalk_code)
                for sa in crosswalk_matches:
                    candidate = _build_crosswalk_candidate(
                        sa, client_code, client_name, crosswalk_code,
                        parent_client_account_name=ca.get("parent_client_account_name"),
                        ancestor_names=ca.get("ancestor_names") or [],
                        client_account_full_path=ca.get("client_account_full_path"),
                    )
                    entry["candidates"].append(candidate)

        # ── 优先级 3c3：父级继承 ──
        # TASK-080：当行有父级科目且父级有安全映射候选时，子级（尤其是泛化叶子名）
        # 应继承父级映射，而不是通过名称相似度误配到无关科目。
        # 如果已有候选全是低质量 name_similarity（score<0.9 或带 warning），
        # 父级继承候选应替换它们。
        parent_code = ca.get("parent_client_account_code")
        parent_name = ca.get("parent_client_account_name")
        ancestor_codes = ca.get("ancestor_codes") or []
        ancestor_names = ca.get("ancestor_names") or []

        # 检查现有候选是否全是弱候选
        existing_candidates = entry.get("candidates", [])
        has_only_weak = bool(existing_candidates) and all(
            c.get("warning") is not None or float(c.get("score", 0) or 0) < 0.9
            for c in existing_candidates
        )

        if not entry["candidates"] or has_only_weak:

            # 尝试按父代码在 crosswalk 中查找
            parent_crosswalk = None
            parent_codes_to_try = []
            if parent_code:
                parent_codes_to_try.append(parent_code)
            parent_codes_to_try.extend(ancestor_codes)

            for pc in parent_codes_to_try:
                parent_crosswalk = _lookup_old_code_crosswalk(pc)
                if parent_crosswalk:
                    break
                # 试试点分第一段
                parts = pc.replace(".", " ").replace("-", " ").split()
                for part in parts:
                    cw = _lookup_old_code_crosswalk(part)
                    if cw:
                        parent_crosswalk = cw
                        break
                if parent_crosswalk:
                    break

            # 如果 crosswalk 没找到，尝试按代码前缀在标准科目中查找
            if not parent_crosswalk and parent_codes_to_try:
                for pc in parent_codes_to_try:
                    prefix_matches = await _query_code_prefix_parent(db, pc, sa_index=sa_index)
                    if prefix_matches:
                        sa = prefix_matches[0]
                        parent_crosswalk = sa.account_code
                        break
                    # 也尝试第一段
                    parts = pc.replace(".", " ").replace("-", " ").split()
                    if parts:
                        prefix_matches = await _query_code_prefix_parent(db, parts[0], sa_index=sa_index)
                        if prefix_matches:
                            sa = prefix_matches[0]
                            parent_crosswalk = sa.account_code
                            break

            if parent_crosswalk:
                crosswalk_matches = await _query_crosswalk_match(db, parent_crosswalk)
                for sa in crosswalk_matches:
                    is_generic = _normalize_name(client_name) in {
                        _normalize_name(n) for n in _GENERIC_LEAF_NAMES
                    }
                    candidate = _build_parent_inherited_candidate(
                        sa, client_code, client_name,
                        parent_code, parent_name, parent_crosswalk,
                        is_generic=is_generic,
                        client_account_full_path=ca.get("client_account_full_path"),
                    )
                    entry["candidates"].append(candidate)

        # ── 优先级 3d：标准科目名称相似度 ─────
        if normalized_client_name:
            name_matches = await _query_name_similarity(db, client_name, threshold=0.6, sa_index=sa_index)
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
            prefix_match = await _query_code_prefix_parent(db, client_code, sa_index=sa_index)
            for sa in prefix_match:
                _add_fallback_candidate(
                    entry, _build_code_prefix_parent_candidate(sa, client_code, client_name, ca)
                )

        # ── 优先级 4b：代码类别锚点（客户代码体系与标准不一致时） ──
        # 客户用 6604 表示研发费用，但标准科目库无 6604，只有「660201 减：研发费用」时，
        # 按 6604→研发费用 的类别锚点去标准科目表按名称匹配。兜底候选，带 warning 不自动确认。
        if normalized_client_code:
            category_matches = await _query_code_category_anchor(db, client_code, sa_index=sa_index)
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
                anchor_matches = await _query_name_anchor_match(db, anchor, sa_index=sa_index)
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
            await _resolve_exact_code_vs_exact_name_conflict(db, entry, client_name, sa_index=sa_index)

        # ── 统一候选排序（TASK-087）：所有候选构造、冲突降级、兜底补充完成后，
        # 用 _sort_candidates 重排，保证安全候选始终排在所有非安全候选前。
        entry["candidates"] = _sort_candidates(entry["candidates"])

        # 兜底候选去重后可能仍较多，限制最多 10 个（保留已加入的顺序：高优先级在前）
        if len(entry["candidates"]) > 10:
            entry["candidates"] = entry["candidates"][:10]

        # ── TASK-087：自动确认决策 ──
        auto_confirm = pick_unique_auto_confirm_candidate(entry["candidates"])
        if auto_confirm is not None:
            entry["auto_confirm_candidate"] = auto_confirm
            # 检查是否同一目标多来源
            safe_ids = set()
            for c in entry["candidates"]:
                if _is_safe_candidate(c):
                    safe_ids.add(c.get("standard_account_id"))
            if len(safe_ids) > 1:
                entry["auto_confirm_status"] = "ambiguous"
                entry["auto_confirm_reason"] = f"存在 {len(safe_ids)} 个不同安全目标，不自动确认"
                entry["auto_confirm_candidate"] = None
            else:
                entry["auto_confirm_status"] = "unique_safe"
                entry["auto_confirm_reason"] = f"唯一安全候选：{auto_confirm.get('source')} → {auto_confirm.get('standard_account_code')} {auto_confirm.get('standard_account_name')}"
        else:
            entry["auto_confirm_candidate"] = None
            # 检查是否有安全候选但多目标
            safe = [c for c in entry["candidates"] if _is_safe_candidate(c)]
            if len(safe) > 1:
                safe_ids = {c.get("standard_account_id") for c in safe}
                if len(safe_ids) > 1:
                    entry["auto_confirm_status"] = "ambiguous"
                    entry["auto_confirm_reason"] = f"存在 {len(safe_ids)} 个不同安全目标，需人工选择"
                else:
                    entry["auto_confirm_status"] = "unique_safe"
                    entry["auto_confirm_reason"] = f"唯一安全目标但无最佳候选"
            else:
                entry["auto_confirm_status"] = "none"
                entry["auto_confirm_reason"] = "无安全候选，需人工确认"

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
# TASK-087：调整候选来源优先级 — 名称语义优先于代码
_CANDIDATE_SOURCE_PRIORITY: dict[str, int] = {
    "company_history": 0,
    "name_exact": 1,          # 名称精确匹配高于全局历史
    "semantic_alias": 2,       # 语义别名高于代码匹配
    "name_prefix": 3,          # 名称首段高于全局历史
    "global_history": 4,       # 全局历史低于名称候选
    "code_match": 5,           # 代码匹配必须在名称检查之后
    "old_code_crosswalk": 6,   # 旧编码低于名称候选
    "parent_inherited_crosswalk": 7,
    "auxiliary_inherited_parent": 7,
    "name_anchor": 8,          # 名称锚点
    "name_similarity": 9,      # 模糊匹配（永不自认）
    "code_prefix_parent": 10,  # 代码前缀（默认人工）
    "code_category_anchor": 11, # 代码类别锚点（默认人工）
    "code_match_conflict": 12,  # 代码冲突
    "history_conflict": 12,     # 历史冲突
}


def _candidate_priority(c: dict) -> tuple[int, float]:
    """候选排序键：先按来源优先级，再按 score 降序（负值升序）。"""
    source = c.get("source", "")
    return (_CANDIDATE_SOURCE_PRIORITY.get(source, 9), -float(c.get("score", 0) or 0))


# 安全候选阈值：warning 为空且 score >= 该值视为「可自动确认安全候选」。
_SAFE_CANDIDATE_MIN_SCORE = 0.9


def _is_safe_candidate(c: dict) -> bool:
    """TASK-087：判定是否为安全候选。

    必须同时满足：
    - auto_confirmable is True
    - warning is None
    - score >= 0.9
    - standard_account is_active (通过 warning 间接检查)
    - compatibility_status == "compatible"

    缺少 auto_confirmable 字段的旧候选按保守方式处理（视为不安全）。
    """
    if c.get("warning"):
        return False
    # TASK-087：必须显式标记 auto_confirmable
    if c.get("auto_confirmable") is not True:
        return False
    # TASK-087：必须兼容
    if c.get("compatibility_status") != "compatible":
        return False
    try:
        return float(c.get("score", 0) or 0) >= _SAFE_CANDIDATE_MIN_SCORE
    except (TypeError, ValueError):
        return False


def _sort_candidates(candidates: list[dict]) -> list[dict]:
    """统一候选排序：安全候选必须排在所有非安全候选前。

    规则（TASK-087 增强）：
    1. 先按「是否安全候选」分区：safe 在前，non-safe 在后。
    2. 安全候选内部先按 source priority，再按 score 降序。
    3. 非安全候选内部：auto_confirmable > source_priority > compatibility > score。
    """
    safe = [c for c in candidates if _is_safe_candidate(c)]
    non_safe = [c for c in candidates if not _is_safe_candidate(c)]
    safe.sort(key=_candidate_priority)
    # 非安全候选：先按是否 auto_confirmable，再按 source priority，再按兼容性，再按 score
    def _non_safe_key(c: dict) -> tuple:
        auto_ok = 0 if c.get("auto_confirmable") is True else 1
        source = _CANDIDATE_SOURCE_PRIORITY.get(c.get("source", ""), 9)
        compat = {"compatible": 0, "unknown": 1, "conflict": 2}.get(c.get("compatibility_status"), 3)
        return (auto_ok, source, compat, -float(c.get("score", 0) or 0))
    non_safe.sort(key=_non_safe_key)
    return safe + non_safe


def pick_unique_auto_confirm_candidate(candidates: list[dict]) -> dict | None:
    """TASK-087：唯一安全候选自动确认。

    规则：
    1. 筛选所有安全候选
    2. 按 standard_account_id 去重
    3. 只有一个不同目标 → 返回最佳候选
    4. 多个不同安全目标 → 返回 None（ambiguous）
    5. 无安全候选 → 返回 None
    """
    if not candidates:
        return None
    safe = [c for c in candidates if _is_safe_candidate(c)]
    if not safe:
        return None
    # 按 standard_account_id 去重
    seen_ids: dict[str, dict] = {}
    for c in safe:
        sa_id = c.get("standard_account_id", "")
        if sa_id and sa_id not in seen_ids:
            seen_ids[sa_id] = c
    if len(seen_ids) == 0:
        return None
    if len(seen_ids) == 1:
        # 唯一目标：返回最佳候选（按优先级最高）
        best = min(seen_ids.values(), key=_candidate_priority)
        return best
    # 多个不同安全目标：不自动确认
    return None


def _pick_auto_confirm_candidate(candidates: list[dict]) -> dict | None:
    """【已废弃】请使用 pick_unique_auto_confirm_candidate。
    保留向后兼容：回退到唯一安全候选；无安全候选时回退到首项。
    """
    result = pick_unique_auto_confirm_candidate(candidates)
    if result is not None:
        return result
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
    sa_index: _StandardAccountIndex | None = None,
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
    # TASK-087：同时检查 code_match 和 code_match_conflict（已被 _build_code_match_candidate 降级）
    code_candidates = [c for c in candidates if c.get("source") in ("code_match", "code_match_conflict")]
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

    prefix_matches = await _query_name_prefix_match(db, client_name, sa_index=sa_index)
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


async def _query_code_match(
    db: AsyncSession, client_code: str,
    sa_index: _StandardAccountIndex | None = None,
) -> list[StandardAccount]:
    """查询标准科目代码精确匹配"""
    normalized_code = _normalize_code(client_code)
    if not normalized_code:
        return []

    if sa_index is not None:
        all_accounts = sa_index.all_accounts
    else:
        stmt = select(StandardAccount)
        result = await db.execute(stmt)
        all_accounts = result.scalars().all()
    matches = [
        sa for sa in all_accounts
        if _normalize_code(sa.account_code) == normalized_code
    ]
    matches.sort(key=lambda sa: (not sa.is_active, sa.account_code))
    return matches[:3]


async def _query_name_exact_match(
    db: AsyncSession, client_name: str,
    sa_index: _StandardAccountIndex | None = None,
) -> list[StandardAccount]:
    """查询标准科目名称规范化后的精确匹配。

    注意：此处用 _normalize_name（不去「减：/加：/其中：」显示前缀）。
    带显示前缀的标准科目（如「减：研发费用」）不应被客户「研发费用」自动确认匹配，
    那属于锚点兜底（_query_name_anchor_match），需带 warning 由用户确认。
    """
    normalized_name = _normalize_name(client_name)
    if not normalized_name:
        return []

    if sa_index is not None:
        all_accounts = sa_index.all_accounts
    else:
        stmt = select(StandardAccount)
        result = await db.execute(stmt)
        all_accounts = result.scalars().all()
    matches = [
        sa for sa in all_accounts
        if _normalize_name(sa.account_name) == normalized_name
    ]
    matches.sort(key=lambda sa: (not sa.is_active, sa.account_code))
    return matches[:5]


async def _query_name_anchor_match(
    db: AsyncSession, anchor: str,
    sa_index: _StandardAccountIndex | None = None,
) -> list[StandardAccount]:
    """按名称锚点匹配标准科目（剥离显示前缀后比较）。

    优先级：
    1. canonical 标准科目名 == canonical anchor（精确）
    2. canonical 标准科目名 contains canonical anchor（包含，如 anchor「研发费用」命中「研发费用-资本化」）

    active 标准科目优先；精确优于包含；同优先级按代码升序。最多返回 5 个。
    """
    canonical_anchor = _canonical_name(anchor)
    if not canonical_anchor:
        return []

    if sa_index is not None:
        all_accounts = sa_index.all_accounts
    else:
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
    db: AsyncSession, client_name: str, threshold: float = 0.6,
    sa_index: _StandardAccountIndex | None = None,
) -> list[tuple[StandardAccount, float]]:
    """查询标准科目名称相似度（数据库层粗筛后用 Python 精算）。

    用 _normalize_name（不去显示前缀），避免「研发费用」与「减：研发费用」
    因剥离前缀后完全相同而被高相似度自动确认。带前缀的标准科目由锚点兜底处理。
    """
    normalized_input = _normalize_name(client_name)
    if not normalized_input or len(normalized_input) < 2:
        return []

    if sa_index is not None:
        all_accounts = sa_index.all_accounts
    else:
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


async def _query_code_prefix_parent(
    db: AsyncSession, client_code: str,
    sa_index: _StandardAccountIndex | None = None,
) -> list[StandardAccount]:
    """按最长标准科目代码前缀匹配上级标准科目。

    客户明细科目代码（如 10020108）没有精确匹配时，找到标准科目表中
    代码是该客户代码前缀、且最长（最贴近）的标准科目（如 1002）。
    排除与客户代码完全相等的情况（那属于精确匹配，应已由 code_match 处理）。
    """
    normalized_code = _normalize_code(client_code)
    if not normalized_code or len(normalized_code) < 4:
        # 代码太短时前缀匹配噪声大，不做
        return []

    if sa_index is not None:
        all_accounts = sa_index.all_accounts
    else:
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


async def _query_code_category_anchor(
    db: AsyncSession, client_code: str,
    sa_index: _StandardAccountIndex | None = None,
) -> list[StandardAccount]:
    """按客户代码类别锚点查询标准科目。

    客户代码体系与标准不一致时（如客户 6604 研发费用，标准无 6604），
    按代码类别对应的名称锚点（6604→研发费用）去标准科目表按名称匹配
    （经 _query_name_anchor_match，命中「减：研发费用」等带前缀的标准科目）。
    """
    anchor = _detect_code_category_anchor(client_code)
    if not anchor:
        return []
    return await _query_name_anchor_match(db, anchor, sa_index=sa_index)



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
            "auto_confirmable": False,
            "compatibility_status": "conflict",
            "compatibility_reason": "标准科目已删除",
            "evidence": ["deleted_standard_account"],
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
            "auto_confirmable": False,
            "compatibility_status": "conflict",
            "compatibility_reason": "标准科目已停用",
            "evidence": [f"inactive_sa={sa.account_code}"],
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
            "auto_confirmable": False,
            "compatibility_status": "conflict",
            "compatibility_reason": conflict,
            "evidence": [f"conflict={conflict}"],
        }

    # TASK-087：历史映射必须接受当前名称一致性检查
    hist_name = _history_name_value(cam)
    curr_name = _normalize_name(cam.client_account_name)
    name_consistent = hist_name == curr_name

    # TASK-087：公司历史映射：仅名称一致时可自动确认
    is_company_history = source == "company_history"
    auto_confirm = is_company_history and name_consistent and score >= 0.9

    # TASK-087：全局历史映射：名称一致 + 兼容时才安全
    if source == "global_history":
        compat = evaluate_name_compatibility(
            sa,
            client_account_name=cam.client_account_name,
        )
        if compat.status == "conflict":
            return {
                "standard_account_id": str(sa.id),
                "standard_account_code": sa.account_code,
                "standard_account_name": sa.account_name,
                "score": min(score, 0.75),
                "source": "history_conflict",
                "reason": f"历史映射与当前名称冲突：{compat.reason}",
                "warning": f"全局历史映射「{sa.account_code} {sa.account_name}」与当前名称冲突：{compat.reason}，请人工确认",
                "auto_confirmable": False,
                "compatibility_status": "conflict",
                "compatibility_reason": compat.reason,
                "evidence": compat.evidence,
            }
        if compat.status == "unknown":
            return {
                "standard_account_id": str(sa.id),
                "standard_account_code": sa.account_code,
                "standard_account_name": sa.account_name,
                "score": min(score, 0.82),
                "source": "global_history",
                "reason": f"历史映射经验 → {sa.account_code} {sa.account_name}",
                "warning": "全局历史映射，名称语义不明确，请人工确认",
                "auto_confirmable": False,
                "compatibility_status": "unknown",
                "compatibility_reason": compat.reason,
                "evidence": compat.evidence,
            }
        auto_confirm = name_consistent

    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": score,
        "source": source,
        "reason": f"历史映射经验 → {sa.account_code} {sa.account_name}",
        "warning": None,
        "auto_confirmable": auto_confirm,
        "compatibility_status": "compatible",
        "compatibility_reason": "历史映射名称一致" if name_consistent else "历史映射（名称有变化但兼容）",
        "evidence": [
            f"hist_name={hist_name}",
            f"curr_name={curr_name}",
            f"name_consistent={name_consistent}",
            f"source={source}",
        ],
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
    parent_client_account_name: str | None = None,
    ancestor_names: list[str] | None = None,
    client_account_full_path: str | None = None,
) -> dict:
    """从代码精确匹配构造候选。

    TASK-087：代码精确匹配必须通过名称兼容性检查。
    - compatible → 安全自动确认 (score=0.92, auto_confirmable=True)
    - conflict → 降级为 code_match_conflict (score<=0.60, auto_confirmable=False)
    - unknown → 降级为 code_match_conflict (score<=0.82, auto_confirmable=False)
    """
    if client_name:
        # 先用旧的锚点冲突检查（快速路径）
        conflict_check = _check_code_match_name_conflict(sa, client_name)
        if conflict_check:
            return {
                "standard_account_id": str(sa.id),
                "standard_account_code": sa.account_code,
                "standard_account_name": sa.account_name,
                "score": conflict_check["score"],
                "source": "code_match_conflict",
                "reason": f"科目代码相同但名称锚点不一致 → {sa.account_code} {sa.account_name}",
                "warning": conflict_check["warning"],
                "auto_confirmable": False,
                "compatibility_status": "conflict",
                "compatibility_reason": conflict_check.get("warning", "名称锚点冲突"),
                "evidence": [f"client_name={client_name}", f"sa_name={sa.account_name}"],
            }

        # TASK-087：统一兼容性评估
        compat = evaluate_name_compatibility(
            sa,
            client_account_name=client_name,
            parent_client_account_name=parent_client_account_name,
            ancestor_names=ancestor_names,
            client_account_full_path=client_account_full_path,
        )
        if compat.status == "conflict":
            return {
                "standard_account_id": str(sa.id),
                "standard_account_code": sa.account_code,
                "standard_account_name": sa.account_name,
                "score": 0.60,
                "source": "code_match_conflict",
                "reason": f"代码相同但客户名称与目标标准科目性质冲突：{compat.reason}",
                "warning": f"代码相同但客户名称「{client_name}」与目标「{sa.account_code} {sa.account_name}」性质冲突：{compat.reason}，请人工确认",
                "auto_confirmable": False,
                "compatibility_status": "conflict",
                "compatibility_reason": compat.reason,
                "evidence": compat.evidence,
            }
        if compat.status == "unknown":
            return {
                "standard_account_id": str(sa.id),
                "standard_account_code": sa.account_code,
                "standard_account_name": sa.account_name,
                "score": 0.82,
                "source": "code_match",
                "reason": f"科目代码精确匹配，但缺少名称语义证据 → {sa.account_code} {sa.account_name}",
                "warning": "仅科目代码命中，缺少名称语义证据，请人工确认",
                "auto_confirmable": False,
                "compatibility_status": "unknown",
                "compatibility_reason": compat.reason,
                "evidence": compat.evidence,
            }
        # compatible: 安全（但停用科目除外）
        is_active = sa.is_active
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": 0.92 if is_active else 0.82,
            "source": "code_match",
            "reason": f"科目代码精确匹配且名称兼容 → {sa.account_code} {sa.account_name}",
            "warning": None if is_active else f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目",
            "auto_confirmable": is_active,
            "compatibility_status": "compatible" if is_active else "conflict",
            "compatibility_reason": compat.reason if is_active else "标准科目已停用",
            "evidence": compat.evidence,
        }

    # 无客户名称：仅代码命中
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": 0.82,
        "source": "code_match",
        "reason": f"科目代码精确匹配（无客户名称） → {sa.account_code} {sa.account_name}",
        "warning": "仅科目代码命中，缺少客户名称，请人工确认",
        "auto_confirmable": False,
        "compatibility_status": "unknown",
        "compatibility_reason": "客户名称为空",
        "evidence": ["client_name=(空)", f"sa_code={sa.account_code}"],
    }


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
    is_active = sa.is_active
    warning = None if is_active else f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": 0.98 if is_active else 0.82,
        "source": "name_exact",
        "reason": f"科目名称精确匹配 → {sa.account_code} {sa.account_name}",
        "warning": warning,
        "auto_confirmable": is_active,
        "compatibility_status": "compatible" if is_active else "conflict",
        "compatibility_reason": "名称规范化后完全一致" if is_active else "标准科目已停用",
        "evidence": [f"sa_name={sa.account_name}", "match=exact_normalized", f"active={is_active}"],
    }


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
    sa_index: _StandardAccountIndex | None = None,
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

    if sa_index is not None:
        all_active = sa_index.all_active
    else:
        stmt = select(StandardAccount)
        result = await db.execute(stmt)
        all_active = [sa for sa in result.scalars().all() if sa.is_active]

    matches: list[StandardAccount] = []
    for sa in all_active:
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

    安全（warning=None, score=0.94）：客户名称明显以更精确标准科目名称开头，
    语义精确度高于父级代码命中，应优先自动确认到该子级。详见 TASK-070。
    """
    is_active = sa.is_active
    warning = None if is_active else f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": 0.94 if is_active else 0.82,
        "source": "name_prefix",
        "reason": (
            f"客户科目名称首段/开头匹配更精确标准科目 → {sa.account_code} {sa.account_name}"
        ),
        "warning": warning,
        "auto_confirmable": is_active,
        "compatibility_status": "compatible" if is_active else "conflict",
        "compatibility_reason": f"客户名称以标准科目「{sa.account_name}」开头" if is_active else "标准科目已停用",
        "evidence": [f"client_name={client_name}", f"sa_name={sa.account_name}", "match=name_prefix"],
    }


def _build_name_similarity_candidate(sa: StandardAccount, similarity: float) -> dict:
    """从名称相似度构造候选。
    TASK-087：模糊匹配永远不自动确认（auto_confirmable=False），无论相似度多高。
    """
    score = round(0.7 + (similarity - 0.6) * 0.5, 2)
    score = min(score, 0.89)  # TASK-087：上限 0.89，永不超过安全阈值
    warning = f"名称相似度 {similarity:.0%}，非精确匹配，请人工确认"
    if not sa.is_active:
        warning = f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": score,
        "source": "name_similarity",
        "reason": f"科目名称相似（相似度 {similarity:.0%}）→ {sa.account_code} {sa.account_name}",
        "warning": warning,
        "auto_confirmable": False,
        "compatibility_status": "unknown",
        "compatibility_reason": "模糊匹配，非精确名称对应",
        "evidence": [f"similarity={similarity:.0%}"],
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
                    # TASK-087：类别锚点匹配时，增加名称兼容性检查
                    # 例如：客户代码 4101 锚点到「资本公积」，但客户名称「生产成本」
                    # 与目标「资本公积」冲突 → 不应安全归入
                    if client_name:
                        compat = evaluate_name_compatibility(
                            sa,
                            client_account_name=client_name,
                            client_account_full_path=context.get("client_account_full_path") if context else None,
                        )
                        if compat.status == "conflict":
                            return False
                        if compat.status == "unknown":
                            return False
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
                # TASK-087：代码前缀确认父子关系时，必须通过名称兼容性检查
                # 例如客户 4105.003「--折旧费」前缀命中标准 4105 利润分配 → 必须检查名称冲突
                # 正常情况如客户 10020108 前缀命中标准 1002 银行存款，名称含银行信息 → 兼容
                if client_name:
                    compat = evaluate_name_compatibility(
                        sa,
                        client_account_name=client_name,
                        client_account_full_path=context.get("client_account_full_path") if context else None,
                    )
                    if compat.status == "conflict":
                        return False
                    if compat.status == "unknown":
                        # 仅代码前缀 + 未知名称 → 不安全，需人工确认
                        return False
                # 名称兼容或无名称 → 允许代码前缀安全归入
                return True

    return False


def _build_code_prefix_parent_candidate(
    sa: StandardAccount,
    client_code: str,
    client_name: str | None = None,
    context: dict | None = None,
) -> dict:
    """从客户明细代码最长标准科目前缀构造候选（父级汇总）。

    若名称锚点与标准科目 canonical name 一致并经名称兼容性检查，则视为安全自动归入
    （warning=None, score=0.92）；否则为兜底候选（带 warning, score=0.85）。
    """
    is_safe = _is_safe_auto_rollup(sa, client_name, context)
    if is_safe:
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": 0.92,
            "source": "code_prefix_parent",
            "reason": f"明细代码前缀安全归入上级科目 → {sa.account_code} {sa.account_name}",
            "warning": None,
            "auto_confirmable": True,
            "compatibility_status": "compatible",
            "compatibility_reason": "代码前缀匹配且名称兼容",
            "evidence": [f"client_code={client_code}", f"sa_code={sa.account_code}"],
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
        "auto_confirmable": False,
        "compatibility_status": "unknown",
        "compatibility_reason": "仅代码前缀匹配，缺少名称证据",
        "evidence": [f"client_code={client_code}", f"sa_code={sa.account_code}"],
    }


def _build_name_anchor_candidate(
    sa: StandardAccount,
    anchor: str,
    client_name: str,
    context: dict | None = None,
) -> dict:
    """从名称锚点构造候选。

    若锚点与标准科目 canonical name 一致并经兼容性检查，视为安全自动归入（warning=None, score=0.92）；
    否则为兜底候选（带 warning, score=0.86）。
    """
    is_safe = _is_safe_auto_rollup(sa, client_name, context)
    if is_safe:
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": 0.92,
            "source": "name_anchor",
            "reason": f"名称锚点「{anchor}」安全归入 → {sa.account_code} {sa.account_name}",
            "warning": None,
            "auto_confirmable": True,
            "compatibility_status": "compatible",
            "compatibility_reason": f"名称锚点「{anchor}」与目标兼容",
            "evidence": [f"anchor={anchor}", f"sa_name={sa.account_name}"],
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
        "auto_confirmable": False,
        "compatibility_status": "unknown",
        "compatibility_reason": "仅名称锚点匹配，需人工确认",
        "evidence": [f"anchor={anchor}"],
    }


def _build_code_category_anchor_candidate(
    sa: StandardAccount,
    client_code: str,
    client_name: str | None = None,
    context: dict | None = None,
) -> dict:
    """从客户代码类别锚点构造候选。

    若名称锚点与标准科目 canonical name 一致并经兼容性检查，视为安全自动归入（warning=None, score=0.92）；
    否则为兜底候选（带 warning, score=0.86）。
    """
    is_safe = _is_safe_auto_rollup(sa, client_name, context)
    if is_safe:
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": 0.92,
            "source": "code_category_anchor",
            "reason": f"代码类别锚点安全归入 → {sa.account_code} {sa.account_name}",
            "warning": None,
            "auto_confirmable": True,
            "compatibility_status": "compatible",
            "compatibility_reason": "代码类别锚点匹配且名称兼容",
            "evidence": [f"client_code={client_code}", f"sa_code={sa.account_code}"],
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
        "auto_confirmable": False,
        "compatibility_status": "unknown",
        "compatibility_reason": "仅代码类别锚点匹配，缺少名称证据",
        "evidence": [f"client_code={client_code}"],
    }


def _build_standard_account_candidate(
    sa: StandardAccount,
    *,
    source: str,
    score: float,
    reason_prefix: str,
    auto_confirmable: bool | None = None,
    compatibility_status: str | None = None,
    compatibility_reason: str | None = None,
    evidence: list[str] | None = None,
) -> dict:
    """从标准科目直接匹配构造候选，停用科目只能作为警告候选。

    TASK-087：所有候选必须包含 auto_confirmable / compatibility_status / evidence 字段。
    缺少兼容性信息的调用方应显式传入，否则默认为 unknown。
    """
    warning = None
    if not sa.is_active:
        warning = f"标准科目「{sa.account_code} {sa.account_name}」已停用，请重新选择启用的标准科目"
        auto_confirmable = False

    # 默认值：未显式传入时，保守处理
    if auto_confirmable is None:
        auto_confirmable = warning is None
    if compatibility_status is None:
        compatibility_status = "unknown"
    if compatibility_reason is None:
        compatibility_reason = "来源未提供兼容性评估" if warning is None else warning
    if evidence is None:
        evidence = [f"source={source}", f"sa_code={sa.account_code}"]

    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": score,
        "source": source,
        "reason": f"{reason_prefix} → {sa.account_code} {sa.account_name}",
        "warning": warning,
        "auto_confirmable": auto_confirmable,
        "compatibility_status": compatibility_status,
        "compatibility_reason": compatibility_reason,
        "evidence": evidence,
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



# ── TASK-081：性能缓存 ──────────────────────────────
# 避免大文件（如 205201 98k 行）反复计算 crosswalk 和查询 DB
_crosswalk_cache: dict[str, str | None] = {}
_crosswalk_sa_cache: dict[str, list] = {}  # target_code → list[StandardAccount]


def _lookup_old_code_crosswalk(client_code: str) -> str | None:
    """在旧编码映射表中查找最匹配的标准科目代码（带缓存）。"""
    if not client_code:
        return None
    code = str(client_code).strip()
    if code in _crosswalk_cache:
        return _crosswalk_cache[code]

    result = _lookup_old_code_crosswalk_impl(code)
    _crosswalk_cache[code] = result
    return result


def _lookup_old_code_crosswalk_impl(code: str) -> str | None:
    """crosswalk 查找实现。"""
    # 精确匹配
    if code in _OLD_CODE_CROSSWALK:
        return _OLD_CODE_CROSSWALK[code]
    # 点分层级：取第一段
    parts = code.replace(".", " ").replace("-", " ").replace("/", " ").split()
    if parts:
        first = parts[0]
        if first in _OLD_CODE_CROSSWALK:
            return _OLD_CODE_CROSSWALK[first]
    # 按前缀匹配（最长的）
    best = None
    best_len = 0
    for old_code, std_code in _OLD_CODE_CROSSWALK.items():
        if code.startswith(old_code) and len(old_code) > best_len:
            best = std_code
            best_len = len(old_code)
    return best


async def _query_crosswalk_match(
    db: AsyncSession,
    target_code: str,
) -> list[StandardAccount]:
    """按标准科目代码精确查询（crosswalk 结果，带缓存）。"""
    if target_code in _crosswalk_sa_cache:
        return _crosswalk_sa_cache[target_code]
    stmt = select(StandardAccount).where(
        StandardAccount.account_code == target_code,
        StandardAccount.is_active == True,
    )
    result = await db.execute(stmt)
    accounts = list(result.scalars().all())
    if accounts:
        _crosswalk_sa_cache[target_code] = accounts
    return accounts


def _build_crosswalk_candidate(
    sa: StandardAccount,
    client_code: str,
    client_name: str | None,
    target_code: str,
    parent_client_account_name: str | None = None,
    ancestor_names: list[str] | None = None,
    client_account_full_path: str | None = None,
) -> dict:
    """从旧编码 crosswalk 构造候选。

    TASK-087：旧编码 crosswalk 必须通过名称兼容性检查。
    - compatible → 安全自动确认 (score=0.91, auto_confirmable=True)
    - conflict → 降级 (score<=0.60, auto_confirmable=False)
    - unknown → 人工确认 (score<=0.82, auto_confirmable=False)
    """
    base = {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": 0.95,
        "source": "old_code_crosswalk",
        "reason": (
            f"旧编码「{client_code}」按编码映射表归入标准科目 → "
            f"{sa.account_code} {sa.account_name}"
        ),
        "warning": None,
    }
    # TASK-087：名称兼容性检查
    if client_name:
        compat = evaluate_name_compatibility(
            sa,
            client_account_name=client_name,
            parent_client_account_name=parent_client_account_name,
            ancestor_names=ancestor_names,
            client_account_full_path=client_account_full_path,
        )
        if compat.status == "conflict":
            base["score"] = 0.60
            base["source"] = "old_code_crosswalk"
            base["warning"] = (
                f"旧编码映射到「{sa.account_code} {sa.account_name}」但客户名称"
                f"「{client_name}」与目标性质冲突：{compat.reason}，请人工确认"
            )
            base["reason"] = f"旧编码 crosswalk 冲突 → {compat.reason}"
            base["auto_confirmable"] = False
            base["compatibility_status"] = "conflict"
            base["compatibility_reason"] = compat.reason
            base["evidence"] = compat.evidence
            return base
        if compat.status == "unknown":
            base["score"] = 0.82
            base["warning"] = (
                f"旧编码映射到「{sa.account_code} {sa.account_name}」，"
                f"但名称语义不明确：{compat.reason}，请人工确认"
            )
            base["auto_confirmable"] = False
            base["compatibility_status"] = "unknown"
            base["compatibility_reason"] = compat.reason
            base["evidence"] = compat.evidence
            return base
        # compatible
        base["score"] = 0.91
        base["auto_confirmable"] = True
        base["compatibility_status"] = "compatible"
        base["compatibility_reason"] = compat.reason
        base["evidence"] = compat.evidence
        return base
    # 无名称：降级
    base["score"] = 0.82
    base["warning"] = "旧编码映射，但缺少客户名称，请人工确认"
    base["auto_confirmable"] = False
    base["compatibility_status"] = "unknown"
    base["compatibility_reason"] = "客户名称为空"
    base["evidence"] = [f"client_code={client_code}", f"target_code={target_code}"]
    return base


def _build_parent_inherited_candidate(
    sa: StandardAccount,
    client_code: str,
    client_name: str | None,
    parent_code: str | None,
    parent_name: str | None,
    target_code: str,
    is_generic: bool = False,
    client_account_full_path: str | None = None,
) -> dict:
    """从父级继承构造候选（通过 crosswalk 或前缀匹配）。

    TASK-087：父级继承必须检查名称兼容性。只有父级名称与目标兼容时才安全。
    """
    score = 0.93 if is_generic else 0.95
    if is_generic:
        reason = (
            f"泛化明细「{client_name or client_code}」继承父级"
            f"「{parent_code or ''} {parent_name or ''}」→ "
            f"{sa.account_code} {sa.account_name}"
        )
    else:
        reason = (
            f"明细「{client_code} {client_name or ''}」继承父级"
            f"「{parent_code or ''} {parent_name or ''}」→ "
            f"{sa.account_code} {sa.account_name}"
        )
    # TASK-087：名称兼容性检查（用父级名称作为主要判断依据）
    compat = evaluate_name_compatibility(
        sa,
        client_account_name=parent_name or client_name,
        client_account_full_path=client_account_full_path,
    )
    if compat.status == "conflict":
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": 0.60,
            "source": "parent_inherited_crosswalk",
            "reason": f"父级继承冲突：{compat.reason}",
            "warning": f"父级「{parent_name or parent_code}」与目标「{sa.account_code} {sa.account_name}」性质冲突：{compat.reason}，请人工确认",
            "auto_confirmable": False,
            "compatibility_status": "conflict",
            "compatibility_reason": compat.reason,
            "evidence": compat.evidence,
        }
    if compat.status == "unknown":
        return {
            "standard_account_id": str(sa.id),
            "standard_account_code": sa.account_code,
            "standard_account_name": sa.account_name,
            "score": 0.82 if not is_generic else min(score, 0.82),
            "source": "parent_inherited_crosswalk",
            "reason": f"父级继承（名称语义不明）：{reason}",
            "warning": f"继承父级但名称语义不明确，请人工确认",
            "auto_confirmable": False,
            "compatibility_status": "unknown",
            "compatibility_reason": compat.reason,
            "evidence": compat.evidence,
        }
    # compatible
    return {
        "standard_account_id": str(sa.id),
        "standard_account_code": sa.account_code,
        "standard_account_name": sa.account_name,
        "score": score,
        "source": "parent_inherited_crosswalk",
        "reason": reason,
        "warning": None,
        "auto_confirmable": True,
        "compatibility_status": "compatible",
        "compatibility_reason": compat.reason,
        "evidence": compat.evidence,
    }
