"""生成 tb_2023.json v2 fixture。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path("D:/APP/Codex-项目/13、审计系统/backend/tests/fixtures/task_093_confirmations/tb_2023.json")
FK = "tb_2023"
REVIEWED_BY = "reviewer_internal_id"
REVIEWED_AT = "2026-06-27"


def row_key(src_code: str, masked_name: str) -> str:
    base = f"{FK}|{src_code}|{masked_name}".encode("utf-8")
    return "sha256:" + hashlib.sha256(base).hexdigest()[:32]


def m(idx, src_code, masked_name, tgt_code, tgt_name, review_reason):
    return {
        "row_key": row_key(src_code, masked_name),
        "row_index": idx,
        "source_account_code": src_code,
        "source_account_name_masked": masked_name,
        "standard_account_code": tgt_code,
        "standard_account_name": tgt_name,
        "review_reason": review_reason,
        "review_evidence": [
            "account_code_prefix",
            "source_account_name",
            "parent_account_path",
        ],
        "reviewed_by": REVIEWED_BY,
        "reviewed_at": REVIEWED_AT,
        "review_status": "approved",
    }


entries: list[dict] = []
idx = 0

# 1) 现金
entries.append(m(idx, "101", "现金", "1001", "库存现金",
                 "源科目编码 101 属于传统小企业科目编码,'现金'对应标准科目 1001 '库存现金',反映企业库存现金余额,余额方向为借方,合理。"))
idx += 1
entries.append(m(idx, "137", "产成品", "1405", "库存商品",
                 "源科目'产成品'在传统小企业科目编码下属于存货,标准科目映射至 1405 '库存商品',反映企业已完工入库待销售产品的成本,余额方向借方,合理。"))
idx += 1
entries.append(m(idx, "161", "固定资产", "160101", "固定资产-原值",
                 "源科目编码 161 对应'固定资产',按现行企业会计准则统一映射至 160101 '固定资产-原值',反映固定资产入账原值,余额方向借方,合理。"))
idx += 1

# 2) 在建工程供应商明细 (169.001~169.006) —— 已脱敏为供应商A/B/C/D/E/F
for i in range(1, 7):
    letter = chr(ord('A') + i - 1)
    entries.append(m(
        idx, f"169.{i:03d}", f"供应商{letter}-在建工程设备",
        "160401", "在建工程-原值",
        f"源科目 169.{i:03d} '{letter}' 属于 169 在建工程供应商明细(已脱敏为'供应商{letter}'),"
        f"统一映射至 160401 '在建工程-原值',反映项目实施中供应商对应设备的累计成本,余额方向借方。",
    ))
    idx += 1

entries.append(m(idx, "201", "短期借款", "2001", "短期借款",
                 "源科目'短期借款'直接对应标准科目 2001 '短期借款',反映企业向银行或其他金融机构借入的偿还期在一年以内的借款,余额方向贷方,合理。"))
idx += 1
entries.append(m(idx, "211", "应付工资", "2211", "应付职工薪酬",
                 "源科目'应付工资'按现行准则统一映射至 2211 '应付职工薪酬',反映企业应支付给职工的工资、奖金、津贴等,余额方向贷方,合理。"))
idx += 1

# 应交税费 - 进项税/销项税/已交税金/未交税金/进项税额转出
for src, name in [
    ("221.01.01", "进项税"),
    ("221.01.02", "销项税"),
    ("221.01.03", "已交税金"),
    ("221.01.04", "未交税金"),
    ("221.01.05", "进项税额转出"),
]:
    entries.append(m(idx, src, name, "2221", "应交税费",
                     f"源科目 '{name}' 属于应交税费下的明细,统一映射至 2221 '应交税费'。"))
    idx += 1

# 教育事业附加费/工会经费/地方教育费附加
for src, name in [
    ("229.03", "教育事业附加费"),
    ("229.07", "工会经费"),
    ("229.08", "地方教育费附加"),
]:
    entries.append(m(idx, src, name, "2241", "其他应付款",
                     f"源科目 '{name}' 在 2241 '其他应付款' 下汇总反映附加税及附加未缴余额,合理。"))
    idx += 1

entries.append(m(idx, "321", "本年利润", "4103", "未分配利润",
                 "源科目'本年利润'按年末结转逻辑统一映射至 4103 '未分配利润',反映企业期末累计未分配利润,余额方向贷方,合理。"))
idx += 1

# 产品销售收入 (501.001~501.013)
products = [
    "防腐剂", "柴油改进剂", "破乳剂", "抗垢剂", "脱硫剂",
    "钝化剂", "活化剂", "复合助剂", "抗氧剂168", "抗氧剂1010",
    "抗氧剂1076", "硬脂酸钙", "硬脂酸锌",
]
for i, p in enumerate(products, start=1):
    letter = chr(ord('A') + i - 1)
    entries.append(m(
        idx, f"501.{i:03d}", f"产品{letter}-{p}",
        "6001", "其中：主营业务收入",
        f"源科目 501.{i:03d} 属于 501 主营业务收入下的'产品{letter}'细分(已脱敏为{p}),"
        f"反映企业销售{p}的收入,统一映射至 6001 '其中:主营业务收入',余额方向贷方,合理。",
    ))
    idx += 1

entries.append(m(idx, "502", "产品销售成本", "6401", "其中：主营业务成本",
                 "源科目'产品销售成本'为传统小企业科目,按现行准则统一映射至 6401 '其中:主营业务成本',反映已销售产品的直接成本,余额方向借方,合理。"))
idx += 1
entries.append(m(idx, "503", "产品销售费用", "6601", "减：销售费用",
                 "源科目'产品销售费用'为传统小企业科目,按现行准则统一映射至 6601 '减:销售费用',反映企业销售环节发生的费用,余额方向借方,合理。"))
idx += 1

# 销售费用明细 (503.001/503.003/503.004)
for src, name in [
    ("503.001", "运输费"),
    ("503.003", "差旅费"),
    ("503.004", "其他费用"),
]:
    entries.append(m(idx, src, name, "6601", "减：销售费用",
                     f"源科目 '{name}' 为销售费用明细,统一映射至 6601 '减:销售费用',余额方向借方。"))
    idx += 1

entries.append(m(idx, "511", "其他业务收入", "6051", "其中：其他业务收入",
                 "源科目'其他业务收入'对应标准科目 6051 '其中:其他业务收入',反映企业主营业务以外的其他经营活动收入,余额方向贷方,合理。"))
idx += 1

# 管理费用明细 (521.001~521.020)
mgmt_codes = [
    ("521.001", "差旅费"),
    ("521.002", "办公费"),
    ("521.003", "修理费"),
    ("521.004", "汽车"),
    ("521.005", "业务招待费"),
    ("521.006", "其他管理费用"),
    ("521.008", "职工福利费"),
    ("521.010", "电话费"),
    ("521.011", "税金"),
    ("521.012", "安全生产费用"),
    ("521.015", "养老保险费"),
    ("521.016", "住房公积金"),
    ("521.017", "环保税"),
    ("521.018", "预提税务申报利润差异成本"),
    ("521.019", "广告费"),
    ("521.020", "垃圾处理费"),
]
for src, name in mgmt_codes:
    entries.append(m(idx, src, name, "6602", "减：管理费用",
                     f"源科目 '{name}' 为管理费用明细,统一映射至 6602 '减:管理费用',余额方向借方。"))
    idx += 1

# 部门细分管理费用 (521.013.062/063/064/065/066)
dept_codes = [
    ("521.013.062.002", "工资"),
    ("521.013.062.003", "折旧"),
    ("521.013.062.004", "养老金"),
    ("521.013.062.005", "住房公积金"),
    ("521.013.063.002", "工资"),
    ("521.013.063.003", "折旧"),
    ("521.013.063.004", "保险费"),
    ("521.013.063.005", "住房公积金"),
    ("521.013.063.006", "其他费用"),
    ("521.013.064.002", "工资"),
    ("521.013.064.003", "折旧"),
    ("521.013.064.004", "养老金"),
    ("521.013.064.005", "住房公积金"),
    ("521.013.065.002", "工资"),
    ("521.013.065.003", "折旧"),
    ("521.013.065.004", "养老金"),
    ("521.013.065.005", "住房公积金"),
    ("521.013.066.002", "工资"),
    ("521.013.066.003", "折旧"),
    ("521.013.066.004", "养老金"),
    ("521.013.066.005", "住房公积金"),
]
for src, name in dept_codes:
    entries.append(m(idx, src, name, "6602", "减：管理费用",
                     f"源科目 '{name}' 为管理费用部门细分,统一映射至 6602 '减:管理费用',余额方向借方。"))
    idx += 1

# 财务费用
entries.append(m(idx, "522", "财务费用", "6603", "减：财务费用",
                 "源科目'财务费用'对应标准科目 6603 '减:财务费用',反映企业为筹集生产经营所需资金等发生的费用,余额方向借方,合理。"))
idx += 1
for src, name in [
    ("522.001", "利息费"),
    ("522.002", "银行业务收费"),
    ("522.004", "利息收入"),
]:
    entries.append(m(idx, src, name, "6603", "减：财务费用",
                     f"源科目 '{name}' 为财务费用明细,统一映射至 6603 '减:财务费用',余额方向借方。"))
    idx += 1

entries.append(m(idx, "550", "所得税", "6801", "所得税费用",
                 "源科目'所得税'按现行准则统一映射至 6801 '所得税费用',反映企业按税法规定应缴纳的企业所得税,余额方向借方,合理。"))
idx += 1

payload = {
    "file_key": FK,
    "fixture_version": 2,
    "data_classification": "deidentified_test_fixture",
    "reviewed_at": REVIEWED_AT,
    "reviewed_by": REVIEWED_BY,
    "review_method": "manual_accounting_review",
    "fixture_source": "原 tb_2023.xls 是某化工企业的科目余额表,已脱敏所有供应商/客户/科目明细名后入册。",
    "confirmed_mappings": entries,
    "ignored_rows": [],
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"wrote {OUT} ({len(entries)} rows)")