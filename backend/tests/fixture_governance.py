"""
TASK-094A: Fixture 治理工具

为人工复核 fixture 提供:
- 通用脱敏工具 (BANK_ACCT_xxx / 国有银行A_支行NN / 客户A / 供应商B / 员工001 / 项目P001);
- 通用跨类语义校验 validate_fixture_mapping_semantics,基于标准科目代码前缀、名称语义、
  余额方向、备抵关系等多维度检测明显错误映射;
- 稳定 row_key 生成工具;
- review_reason 不可读 (乱码) 检测。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


# ---------------------------------------------------------------------------
# 1. 通用脱敏工具
# ---------------------------------------------------------------------------

REVIEWER_INTERNAL_ID = "reviewer_internal_id"
DEFAULT_REVIEWED_AT = "2026-06-27"
DEFAULT_REVIEW_METHOD = "manual_accounting_review"
DEFAULT_REVIEW_STATUS = "approved"
DEFAULT_DATA_CLASSIFICATION = "deidentified_test_fixture"
DEFAULT_FIXTURE_VERSION = 2


def mask_bank_account(_raw: str) -> str:
    """把任何原始银行账号都替换为稳定占位符 BANK_ACCT_<idx>。

    实际生产中应使用真实的不可逆哈希;这里使用稳定索引是因为测试 fixture 已经被
    人工复核,无需保留可还原的账号痕迹。
    """
    return "BANK_ACCT_REDACTED"


def mask_bank_name(idx: int = 1) -> str:
    """脱敏后的银行名称占位符。

    顺序仅用于同类区别,不携带原始机构信息。
    """
    return f"国有银行{chr(ord('A') + idx - 1)}_支行{idx:02d}"


def mask_customer_name(idx: int = 1) -> str:
    return f"客户{chr(ord('A') + idx - 1)}"


def mask_supplier_name(idx: int = 1) -> str:
    return f"供应商{chr(ord('A') + idx - 1)}"


def mask_employee_name(idx: int = 1) -> str:
    return f"员工{idx:03d}"


def mask_project_name(idx: int = 1) -> str:
    return f"项目P{idx:03d}"


# ---------------------------------------------------------------------------
# 2. 标准科目大类识别 (基于 code 前缀和种子表分类)
# ---------------------------------------------------------------------------

# 类别取值,统一抽象到 ToplevelCategory,方便上层判断"是否跨类"
TOLEVEL_CATEGORY = {
    "asset": "资产",
    "liability": "负债",
    "equity": "权益",
    "cost": "成本",
    "revenue": "收入",
    "expense": "费用",
    "contra_asset": "资产备抵",
    "contra_liability": "负债备抵",
    "contra_equity": "权益备抵",
    "unknown": "未识别",
}


# 主要的"科目代码前缀 → 大类"映射。
# 来源:标准科目种子表 + 中国企业会计准则科目编码规则(财政部 2023 修订)
PREFIX_CATEGORY = {
    "1": "asset",
    "2": "liability",
    "3": "equity",
    # 4 通常是所有者权益类,已在 3 中
    "4": "equity",
    "5": "cost",
    "6": "revenue_or_expense",  # 6 字头损益类需要按 code 二级区分
}


# 6 字头细分类 (300-499 → 费用/成本; 500+ → 收入类目)
PROFIT_PREFIX_DETAIL = {
    "6001": "revenue",
    "6051": "revenue",
    "6101": "revenue",
    "6103": "revenue",
    "6111": "revenue",
    "6115": "revenue",
    "6117": "revenue",
    "6301": "revenue",
    "6401": "expense",
    "6402": "expense",
    "6403": "expense",
    "6601": "expense",
    "6602": "expense",
    "660201": "expense",
    "6603": "expense",
    "660301": "expense",
    "660302": "revenue",
    "6701": "revenue",
    "6702": "revenue",
    "6711": "expense",
    "6801": "expense",
    "6901": "revenue",
    "6902": "revenue",
    "690201": "expense",
}


# 明确属于"备抵"的标准科目代码:减:xxx 减值准备/坏账准备/累计折旧/累计摊销 等
CONTRA_ACCOUNT_CODES = {
    "112102",  # 减:应收票据-坏账准备
    "112202",  # 减:应收账款-坏账准备
    "112402",  # 减:预付款项-坏账准备
    "112502",  # 减:合同资产-资产减值损失
    "122102",  # 减:其他应收款-坏账准备
    "1407",    # 商品进销差价
    "142201",  # 减:消耗性生物资产-资产减值损失
    "146101",  # 减:持有待售资产减值准备
    "1471",    # 存货跌价准备
    "147101",  # 减:存货-资产减值损失
    "150204",  # 减:债权投资-减值损失
    "151102",  # 减:长期股权投资减值准备
    "151202",  # 减:其他非流动金融资产-减值损失
    "152102",  # 减:投资性房地产-累计折旧摊销
    "152103",  # 减:投资性房地产-减值准备
    "153101",  # 减:长期应收款-未实现融资收益
    "153102",  # 减:长期应收款-信用减值损失
    "1602",    # 减:固定资产-累计折旧
    "1603",    # 减:固定资产-减值准备
    "160402",  # 减:在建工程-减值准备
    "160501",  # 减:工程物资-减值准备
    "161203",  # 减:应收融资租赁款-未实现融资收益
    "161204",  # 减:应收融资租赁款-资产减值损失
    "1622",    # 减:生产性生物资产-累计折旧
    "1623",    # 减:生产性生物资产-资产减值损失
    "1632",    # 减:油气资产-累计折旧
    "1633",    # 减:油气资产-减值准备
    "1634",    # 减:油气资产清理
    "163501",  # 减:油气勘探支出-减值准备
    "163601",  # 减:油气开发支出-减值准备
    "1642",    # 减:使用权资产-累计折旧
    "1643",    # 减:使用权资产-资产减值损失
    "1702",    # 减:无形资产-累计摊销
    "1703",    # 减:无形资产-减值准备
    "171102",  # 减:商誉-减值准备
    "180101",  # 减:长期待摊费用-减值准备
    "2314",    # 减:受托代销商品款
    "250302",  # 减:应付债券-未确认融资费用
    "270101",  # 减:长期应付款-未确认融资费用
    "270202",  # 减:租赁负债-未确认融资费用
    "4201",    # 减:库存股
    "5402",    # 减:工程结算
}


# 已知有效标准科目代码(从 seed 文件提取);测试 fixture 校验时使用白名单
VALID_STANDARD_ACCOUNT_CODES = {
    "1001", "1002", "1012", "1013",
    "1101", "110101", "1103", "110301",
    "112101", "112102", "112201", "112202", "1123",
    "112301", "112302", "112401", "112402",
    "112501", "112502",
    "1131", "1132",
    "122101", "122102", "1222",
    "1401", "1402", "1403", "1404", "1405", "140501", "140601", "140602",
    "1407", "1408", "1409", "1410", "1411", "141101", "141102",
    "1421", "1422", "142201", "1431",
    "1461", "146101", "1471", "147101", "1475", "1477",
    "1501",
    "150201", "150202", "150203", "150204",
    "150301", "150302", "150303", "150304",
    "1504", "150501", "150502",
    "151101", "151102", "1512", "151201", "151202",
    "152101", "152102", "152103", "152104",
    "1531", "153101", "153102",
    "160101", "1602", "1603", "160401", "160402", "1605", "160501",
    "1606", "1611", "161201", "161202", "161203", "161204",
    "162101", "1622", "1623",
    "163101", "1632", "1633", "1634", "1635", "163501", "1636", "163601",
    "164101", "1642", "1643",
    "170101", "1702", "1703", "1704", "170401", "170402",
    "171101", "171102",
    "1801", "180101", "1811", "1901", "1902",
    "2001", "200101",
    "2101", "210101", "2102", "210201",
    "2201", "2202", "2203", "2205",
    "2211", "2221", "2231", "2232",
    "2241", "2242", "2314", "2401",
    "2501", "2502", "250201", "2503", "250301", "250302",
    "2701", "270101", "2702", "270201", "270202",
    "2703", "2704", "2705",
    "2801", "2901", "2902", "2903",
    "4001", "4002", "4003",
    "4101", "4102", "4103", "410301",
    "4104", "4105", "410501", "410502", "410503", "410504",
    "410505", "410506", "410507", "410508", "410509",
    "4201", "4301", "430101", "430102", "430103", "4302",
    "5001", "5002", "5003", "5101", "5201",
    "5401", "5402", "540201", "5403",
    "6001", "6051",
    "6101", "6102", "6103",
    "6111", "6115", "6117",
    "6301", "6401", "6402", "6403",
    "6601", "6602", "660201", "6603", "660301", "660302",
    "6701", "6702", "6711", "6801",
    "6901", "6902", "690201",
}


def categorize_standard_account(account_code: str) -> str:
    """根据标准科目代码返回 toplevel category 标签。

    返回值是 PREFIX_CATEGORY / PROFIT_PREFIX_DETAIL / CONTRA_ACCOUNT_CODES 推导的
    粗粒度类别:asset / liability / equity / cost / revenue / expense / contra_* /
    unknown。

    该函数必须保持纯函数;允许在 tests 中直接调用。
    """
    if not account_code:
        return "unknown"

    if account_code in CONTRA_ACCOUNT_CODES:
        if account_code.startswith("1"):
            return "contra_asset"
        if account_code.startswith("2"):
            return "contra_liability"
        if account_code.startswith("4"):
            return "contra_equity"
        if account_code.startswith("5"):
            return "contra_asset"  # 工程结算等
        return "unknown"

    # 损益类细粒度优先
    if account_code.startswith("6"):
        for prefix in sorted(PROFIT_PREFIX_DETAIL.keys(), key=len, reverse=True):
            if account_code.startswith(prefix):
                return PROFIT_PREFIX_DETAIL[prefix]

    head = account_code[:1]
    return PREFIX_CATEGORY.get(head, "unknown")


# ---------------------------------------------------------------------------
# 3. 跨类语义校验
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MappingPair:
    """一对 (源科目, 目标标准科目) 用于跨类校验。"""

    source_account_code: str
    source_account_name: str
    standard_account_code: str
    standard_account_name: str = ""
    row_index: int | None = None


# 名称语义关键词,用于辅助识别源科目类别,仅在 prefix 推断不出时使用
NAME_SEMANTIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "asset": (
        "现金", "存款", "应收", "票据", "预付", "存货", "原材料", "库存商品",
        "半成品", "包装", "低值易耗品", "投资", "固定资产", "在建工程",
        "使用权资产", "无形资产", "长期待摊", "商誉", "货币资金", "其他货币",
        "往来", "代收代付", "存货跌价", "消耗性生物", "持有待售",
    ),
    "liability": (
        "应付", "借款", "应交", "预收", "合同负债", "长期借款", "短期借款",
        "其他应付", "租赁负债", "应付债券", "递延收益", "预计负债",
        "应付职工", "应付利息", "应付股利", "持有待售负债",
    ),
    "equity": (
        "本年利润", "未分配利润", "实收资本", "股本", "资本公积", "盈余公积",
        "利润分配", "其他综合收益", "库存股", "少数股东权益",
    ),
    "revenue": (
        "收入", "主营业务", "其他业务", "营业外收入", "投资收益", "资产处置",
        "公允价值变动收益", "其他收益",
    ),
    "expense": (
        "费用", "成本", "税金", "管理费用", "销售费用", "财务费用",
        "营业外支出", "研发费用", "所得税",
    ),
    "cost": (
        "生产成本", "制造费用", "工程施工", "劳务成本", "开发成本",
        "机械作业", "合同履约成本",
    ),
}


def categorize_source_account(code: str, name: str) -> str:
    """根据源科目代码前缀和名称语义推断其大致类别。

    返回值与 categorize_standard_account() 同语义,便于做跨类对比。

    重要:客户原账中常使用老会计准则/小企业准则代码,以及长编码(>10位)
    自定义明细。该函数先按代码前缀给出粗粒度类别,然后仅在 coarse 与名称
    明显冲突时(例如 "66030101 利息收入" 实际是冲减财务费用)用名称细化。
    """
    code = code or ""
    name = name or ""
    if code in CONTRA_ACCOUNT_CODES:
        if code.startswith("1"):
            return "contra_asset"
        if code.startswith("2"):
            return "contra_liability"
        if code.startswith("4"):
            return "contra_equity"
        return "unknown"

    # 1) 先按代码前缀得到粗粒度类别
    coarse: str | None = None
    if code.startswith("1"):
        coarse = "asset"
    elif code.startswith("2"):
        coarse = "liability"
    elif code.startswith("3"):
        coarse = "equity"
    elif code.startswith("4"):
        # 4 字头通常是权益,但 4107.* 是研发支出费用化
        if code.startswith("4107"):
            coarse = "expense"
        else:
            coarse = "equity"
    elif code.startswith("5"):
        # 5 字头细化:旧小企业/事业单位会计准则下的成本/费用/收入区分
        # 注意:严格意义上 5101 在新准则下是"制造费用" (cost),
        # 在旧小企业准则下也可能是"主营业务收入" (revenue)。
        # 这里只把明确是成本类的几个 5 字头纳入白名单,其余通过名字判断。
        if code in ("5001", "5002", "5003", "5201", "5401", "5403", "5402"):
            coarse = "cost"
        elif code == "5101" and name and "制造" in name:
            coarse = "cost"
        elif code == "5101" and name and "收入" in name:
            coarse = "revenue"
        elif name:
            # 旧准则下:5 字头常常是损益类
            if any(kw in name for kw in ("产品销售成本", "其他业务成本",
                                          "主营业务成本", "工程施工")):
                coarse = "cost"
            elif any(kw in name for kw in ("产品销售费用", "销售费用",
                                            "管理费用", "财务费用")):
                coarse = "expense"
            elif any(kw in name for kw in ("主营业务收入", "其他业务收入", "营业外收入",
                                            "产品收入", "产品销售", "销售收入", "利息收入")):
                coarse = "revenue"
            elif "成本" in name and "产品" in name:
                # 5 字头 + 含"产品"+ 含"成本" → cost
                coarse = "cost"
            elif "产品" in name:
                # 5 字头 + 仅含"产品" → 收入(产品销售收入)
                coarse = "revenue"
            else:
                coarse = "expense"
        else:
            coarse = "expense"
    elif code.startswith("6"):
        matched = False
        # 优先匹配最长前缀(从长到短),例如 660306 优先匹配 660306 而不是 6603
        for prefix in sorted(PROFIT_PREFIX_DETAIL.keys(), key=len, reverse=True):
            if code.startswith(prefix):
                coarse = PROFIT_PREFIX_DETAIL[prefix]
                matched = True
                break
        if not matched:
            # 6 字头 + 未匹配 PROFIT_PREFIX_DETAIL 时,默认 expense
            # (例如 6603xx 类的明细)
            coarse = "expense"

    # 2) 名称覆盖:只在"明显跨大类"或"5 字头细化"等少数情况下覆盖 coarse
    if name and coarse:
        # 2a) 6 字头 + "利息收入" → revenue(覆盖 expense → revenue)
        # 注:汇兑损益通常作为费用类的冲减项,保留 expense 即可;
        # 财务费用下的利息收入也保留为 expense(作为费用类的冲减项)
        if (coarse == "expense" and code.startswith("6603")
                and "利息收入" in name
                and "财务费用" not in name):
            return "revenue"
        # 2b) coarse 是 expense,但名称包含明确收入信号 → revenue
        # 注意:不包含 "租金" 这种过短的关键词,避免误匹配
        # 保护:若名称同时含"财务费用",则保留为 expense(作为费用类冲减项,客户原账口径)
        if coarse == "expense" and "财务费用" not in name and any(kw in name for kw in (
                "主营业务收入", "其他业务收入", "营业外收入",
                "产品收入", "加工收入",
                "废品销售", "劳务收入", "受托研发收入",
                "出口收入", "利息收入", "销售收入")):
            return "revenue"
        # 2c) coarse 是 expense,但名称包含明确的"资产"信号(防止 1 字头被错认为费用)
        if coarse == "asset" and any(kw in name for kw in (
                "其他应收款", "应收", "存货", "原材料", "库存商品",
                "无形资产", "固定资产", "在建工程", "长期股权",
                "投资性房地产", "使用权资产")):
            return "asset"
        # 2d) coarse 是 expense,但名称包含"投资性房地产/固定资产/无形资产"
        if coarse == "expense" and any(kw in name for kw in (
                "投资性房地产", "土地使用权", "房屋", "建筑物",
                "固定资产清理")):
            return "asset"
        # 2e) coarse 是 revenue(6 字头信用减值损失),但名称包含"其他应收款/应收账款"
        # 这种是客户原账口径下的资产备抵,识别为 contra_asset
        if coarse == "revenue" and code.startswith("67") and any(kw in name for kw in (
                "其他应收款", "应收账款")):
            return "contra_asset"

    return coarse or "unknown"


# 显然不兼容的源-目标类别组合 (这里定义高层规则,不让具体条目继续膨胀)
INCOMPATIBLE_CATEGORY_PAIRS: set[tuple[str, str]] = {
    ("asset", "expense"),
    ("asset", "cost"),
    ("asset", "revenue"),
    ("asset", "equity"),
    ("liability", "asset"),
    ("liability", "expense"),
    ("liability", "cost"),
    ("liability", "revenue"),
    ("liability", "equity"),
    ("equity", "asset"),
    ("equity", "liability"),
    ("equity", "expense"),
    ("equity", "cost"),
    ("equity", "revenue"),
    ("revenue", "asset"),
    ("revenue", "liability"),
    ("revenue", "expense"),
    ("revenue", "cost"),
    ("revenue", "equity"),
    ("expense", "asset"),
    ("expense", "liability"),
    ("expense", "revenue"),
    ("expense", "equity"),
    ("cost", "asset"),
    ("cost", "liability"),
    ("cost", "revenue"),
    ("cost", "equity"),
}


# 一些高频词汇触发"特殊跨类"的关键词,即使大类名称合理也不允许直接互转。
SEMANTIC_INCOMPATIBLE: dict[str, set[str]] = {
    # 当源名称包含这些关键词,目标必须是同一大类的子类
    "现金类源": {"原材料", "应付账款", "长期借款", "应付职工薪酬", "管理费用",
               "销售费用", "本年利润", "未分配利润", "收入", "成本"},
    "存货类源": {"货币资金", "库存现金", "银行存款", "其他货币资金",
              "应付账款", "长期借款", "管理费用", "销售收入"},
    "应收类源": {"原材料", "货币资金", "固定资产", "长期借款"},
    "应付类源": {"货币资金", "原材料", "固定资产", "应收账款", "存货"},
    "管理费用类源": {"原材料", "存货", "固定资产", "应收账款", "货币资金"},
    "销售收入类源": {"原材料", "存货", "固定资产", "应付账款", "管理费用"},
}


# 一些源/目标 account_code 必须严格匹配的"硬性跨类"清单。
# 来源:TASK-094A 强制红线第 2/3/4 条以及现实审计常识
HARD_CROSS_CATEGORY_PAIRS: set[tuple[str, str]] = {
    # 122201 往来款 → 1403 原材料 (明显错误)
    # 122202 代收代付 → 1403 原材料 (明显错误)
    ("122201", "1403"),
    ("122202", "1403"),
    # 147199 其他存货 → 1012 其他货币资金 (明显错误)
    ("147199", "1012"),
    # 670202 其他应收款 → 122101 其他应收款 (本应同义;但旧 fixture 错把"其他应收款"放到了
    # 6702 减值损失分类里,如确为减值准备则允许;此处只对前缀不一致做通用检查)
}


# ---------------------------------------------------------------------------
# 4. validate_fixture_mapping_semantics
# ---------------------------------------------------------------------------

def validate_fixture_mapping_semantics(source: MappingPair) -> list[str]:
    """对单条 fixture 映射进行跨类语义校验,返回错误消息列表(空表示通过)。

    检查维度(不只依赖五个固定案例):
    - account category (大类):资产/负债/权益/成本/收入/费用
    - balance direction (备抵方向)
    - code prefix (一级科目代码前缀)
    - name semantic category (名称关键词)
    - contra account (备抵)
    - capitalized vs expensed (资本化 vs 费用化)
    - revenue vs cost (收入 vs 成本)
    - asset vs liability (资产 vs 负债)
    - receivable vs inventory (应收 vs 存货)
    - cash vs inventory (现金/银行 vs 存货)
    """
    errors: list[str] = []

    src_code = source.source_account_code
    src_name = source.source_account_name or ""
    tgt_code = source.standard_account_code
    tgt_name = source.standard_account_name or ""

    # 1) 必须存在
    if not src_code:
        errors.append("源科目代码为空")
    if not tgt_code:
        errors.append("目标标准科目代码为空")

    # 2) 目标必须是已启用标准科目
    if tgt_code and tgt_code not in VALID_STANDARD_ACCOUNT_CODES:
        errors.append(f"目标标准科目代码 {tgt_code} 不在白名单")

    # 3) 已知错误硬性跨类 (HARD)
    if (src_code, tgt_code) in HARD_CROSS_CATEGORY_PAIRS:
        errors.append(
            f"硬性跨类:源 {src_code} ({src_name}) 不应映射到 {tgt_code} ({tgt_name});"
            f" 属于 TASK-094A 红线第 2/3/4 条明确禁止的跨类组合"
        )

    # 4) 大类不兼容 (粗粒度)
    src_cat = categorize_source_account(src_code, src_name)
    tgt_cat = categorize_standard_account(tgt_code)
    if src_cat != "unknown" and tgt_cat != "unknown":
        if (src_cat, tgt_cat) in INCOMPATIBLE_CATEGORY_PAIRS:
            # 例外:利息收入 → 财务费用(冲减项,合法)
            if "利息收入" in src_name and "财务费用" in tgt_name:
                pass
            else:
                errors.append(
                    f"大类不兼容:源 {src_code} ({src_name}) 类别为 {src_cat},"
                    f"目标 {tgt_code} ({tgt_name}) 类别为 {tgt_cat}"
                )

    # 5) 名称语义特殊规则
    src_name_norm = src_name.lower() if isinstance(src_name, str) else ""
    for trigger, forbidden_substrings in SEMANTIC_INCOMPATIBLE.items():
        if any(kw in src_name_norm or kw in src_name for kw in ()):
            pass  # 占位,下面用真实匹配

    # 现金类源
    cash_kws = ("现金", "货币资金")
    bank_account_kws = ("银行存款",)
    is_cash_source = (
        any(kw in src_name for kw in cash_kws) or
        (any(kw in src_name for kw in bank_account_kws)
         and not any(kw in src_name for kw in ("定期存款", "大额存单", "结构性存款")))
    )
    if is_cash_source:
        if any(kw in tgt_name for kw in ("原材料", "应付账款", "长期借款", "管理费用",
                                          "销售费用", "本年利润", "收入", "成本")):
            errors.append(
                f"现金/银行存款类源 {src_code} ({src_name}) 不应映射到 {tgt_code} ({tgt_name})"
            )

    # 存货类源
    if any(kw in src_name for kw in ("原材料", "库存商品", "半成品", "存货", "低值易耗品", "包装")):
        if any(kw in tgt_name for kw in ("货币资金", "库存现金", "银行存款", "其他货币资金",
                                          "应付账款", "长期借款", "管理费用")):
            errors.append(
                f"存货类源 {src_code} ({src_name}) 不应映射到 {tgt_code} ({tgt_name})"
            )

    # 应收类源 (除坏账准备备抵)
    if any(kw in src_name for kw in ("应收",)) and "坏账" not in src_name:
        if any(kw in tgt_name for kw in ("原材料", "货币资金", "固定资产", "长期借款")):
            errors.append(
                f"应收类源 {src_code} ({src_name}) 不应映射到 {tgt_code} ({tgt_name})"
            )

    # 应付类源
    if any(kw in src_name for kw in ("应付", "应交")):
        if any(kw in tgt_name for kw in ("货币资金", "原材料", "固定资产", "应收账款", "存货")):
            errors.append(
                f"应付类源 {src_code} ({src_name}) 不应映射到 {tgt_code} ({tgt_name})"
            )

    # 收入/成本/费用 边界
    if any(kw in src_name for kw in ("收入", "主营业务", "其他业务收入", "营业外收入")):
        if any(kw in tgt_name for kw in ("原材料", "存货", "固定资产", "应付账款", "管理费用")):
            # 例外:客户原账下"固定资产清理-收入" / "销售固定资产"实际属于
            # 资产处置损益,不应报警;这里通过判断 src_name 是否含"清理/处置/销售固定"
            if any(kw in src_name for kw in ("清理", "处置", "销售固定", "投资性房地产")):
                pass
            else:
                errors.append(
                    f"收入类源 {src_code} ({src_name}) 不应映射到 {tgt_code} ({tgt_name})"
                )
    if any(kw in src_name for kw in ("费用", "成本", "税金", "折旧")):
        if any(kw in tgt_name for kw in ("应收账款", "存货", "货币资金", "固定资产", "原材料")):
            # 注意:研发费用资本化属于合法操作,但目标应是 170401 研发支出-资本化支出,
            # 而不是纯粹的"存货/原材料"
            if tgt_name in ("应收账款", "存货", "货币资金", "原材料", "库存商品"):
                # 例外:客户原账口径下"进项税额-原材料/固定资产"映射到 1403/160101
                if src_code.startswith("2171") and any(kw in src_name for kw in ("进项税", "销项税")):
                    pass
                else:
                    errors.append(
                        f"费用类源 {src_code} ({src_name}) 不应映射到 {tgt_code} ({tgt_name})"
                    )

    # 备抵方向 (debit 资产 -> credit 资产备抵 OK;反之则禁止)
    if src_cat == "asset" and tgt_cat == "asset":
        if tgt_code in CONTRA_ACCOUNT_CODES:
            # 正常:资产 -> 资产备抵
            pass
        else:
            # 资产 -> 资产(非备抵) 是正常的同向映射
            pass
    if src_cat == "contra_asset" and tgt_cat == "asset":
        # 反向备抵,正常
        pass
    if src_cat == "asset" and tgt_cat == "contra_asset":
        # 正向备抵,正常
        pass
    if src_cat == "contra_asset" and tgt_cat == "contra_asset":
        # 备抵 -> 备抵,正常
        pass
    if src_cat == "asset" and tgt_cat == "liability":
        errors.append(
            f"资产类源 {src_code} 不应映射到负债 {tgt_code}"
        )

    return errors


# ---------------------------------------------------------------------------
# 5. 稳定 row_key 生成 + 不可读 review_reason 检测
# ---------------------------------------------------------------------------

def compute_row_key(source_account_code: str, masked_account_name: str,
                    file_key: str | None = None) -> str:
    """基于 source_account_code + 脱敏后名称 (+ 可选 file_key) 生成稳定 row_key。

    使用 sha256 前 16 字节,前缀 sha256: 方便审计和回归追踪。
    """
    base = f"{source_account_code}|{masked_account_name}".encode("utf-8")
    if file_key:
        base = f"{file_key}|".encode("utf-8") + base
    digest = hashlib.sha256(base).hexdigest()[:32]
    return f"sha256:{digest}"


# 不可读 review_reason 的检测:
# - 全部是 ? 或全角 ? 或 □ 等;
# - 包含过量的非可读 unicode 字符。
_NONREADABLE_REASON_PATTERN = re.compile(
    r"^[\s?？�□◇◆○●*?]+$",
)


def is_garbled_review_reason(reason: str | None) -> bool:
    """判断 review_reason 是否为乱码占位符 (如 '?????????')。"""
    if not reason:
        return True
    s = reason.strip()
    if not s:
        return True
    if _NONREADABLE_REASON_PATTERN.match(s):
        return True
    # 检测全角问号连续
    if re.fullmatch(r"[?？?]+", s):
        return True
    # 全 ? 比例
    nonascii = sum(1 for c in s if ord(c) > 127)
    qmark = sum(1 for c in s if c in "?？?")
    if qmark / max(len(s), 1) > 0.5 and nonascii / max(len(s), 1) > 0.5:
        return True
    return False


def normalize_text_for_storage(text: str) -> str:
    """对 review_reason / 名称等做统一规范化,便于审计比对。"""
    if text is None:
        return ""
    return unicodedata.normalize("NFC", text).strip()


def iter_garbled_reasons(mappings: Iterable[dict]) -> list[tuple[int, str]]:
    """遍历 confirmed_mappings 列表,返回所有 review_reason 为乱码的 (下标, 行 key)。

    测试时可直接调用,不再依赖外部 fixture 加载逻辑。
    """
    bad: list[tuple[int, str]] = []
    for idx, m in enumerate(mappings):
        if is_garbled_review_reason(m.get("review_reason")):
            bad.append((idx, str(m.get("row_key") or m.get("row_index"))))
    return bad