"""生成 yiliao.json v2 fixture"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path("D:/APP/Codex-项目/13、审计系统/backend/tests/fixtures/task_093_confirmations/yiliao.json")
FK = "yiliao"
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
idx = 28

entries.append(m(idx, "1471", "存货跌价准备", "147101", "减：存货-资产减值损失",
                 "源科目为'存货跌价准备',会计性质属于资产备抵类(余额方向贷方,冲减存货账面价值)。标准科目 147101 为'减:存货-资产减值损失',同属资产备抵且余额方向为贷方,性质一致,映射成立。"))
idx += 1

entries.append(m(idx, "1601", "固定资产", "160101", "固定资产-原值",
                 "源科目'固定资产'按字面应对应标准科目 160101 '固定资产-原值',反映固定资产入账原值,余额方向均为借方,无误。"))
idx += 1

entries.append(m(idx, "160102", "固定资产-机器设备", "160101", "固定资产-原值",
                 "源科目为'固定资产-机器设备',按企业会计准则下属明细属于固定资产原值范畴,统一映射至标准科目 160101 '固定资产-原值',以避免跨大类错误。"))
idx += 1

entries.append(m(idx, "160104", "固定资产-电子设备", "160101", "固定资产-原值",
                 "源科目'电子设备'为固定资产-原值的明细分类,统一映射至 160101,反映固定资产账面原值,余额方向为借方,合理。"))
idx += 1

entries.append(m(idx, "160105", "固定资产-其他设备", "160101", "固定资产-原值",
                 "源科目'其他设备'为固定资产原值下的兜底明细,统一映射至 160101 '固定资产-原值'。"))
idx += 1

entries.append(m(idx, "165101", "使用权资产-房屋及建筑物", "164101", "使用权资产-原值",
                 "源科目'使用权资产-房屋及建筑物'属于新租赁准则下的'使用权资产-原值'范畴,统一映射至 164101,反映承租人对租赁资产的初始入账价值,余额方向为借方。"))
idx += 1

entries.append(m(idx, "27050101", "租赁负债-租赁付款额-合同金额", "270201", "租赁负债-租赁合同付款额",
                 "源科目'租赁付款额-合同金额'属于租赁负债下的本金明细,映射至 270201 '租赁负债-租赁合同付款额',反映承租人尚未支付的租赁付款额本金,余额方向为贷方。"))
idx += 1

entries.append(m(idx, "27050102", "租赁负债-租赁付款额-已付款", "270201", "租赁负债-租赁合同付款额",
                 "源科目'租赁付款额-已付款'虽代表已经支付的部分,但原始科目类别仍属于租赁负债(贷方反映尚未支付余额),统一映射至 270201 '租赁负债-租赁合同付款额'。"))
idx += 1

entries.append(m(idx, "4103", "本年利润", "4103", "未分配利润",
                 "源科目'本年利润'按企业会计准则年末结转至'利润分配-未分配利润',标准科目 4103 即'未分配利润',余额方向均为贷方,反映企业累计未分配利润,合理。"))
idx += 1

entries.append(m(idx, "660113", "销售费用-租房成本", "6601", "减：销售费用",
                 "源科目'销售费用-租房成本'属于销售费用项下的租赁相关支出,统一映射至 6601 '减:销售费用',反映销售环节发生的费用支出,余额方向为借方。"))
idx += 1

entries.append(m(idx, "66011301", "销售费用-租房成本-租金", "6601", "减：销售费用",
                 "源科目'租房成本-租金'属于销售费用明细,统一映射至 6601 '减:销售费用',反映销售环节房租支出,余额方向借方。"))
idx += 1

payload = {
    "file_key": FK,
    "fixture_version": 2,
    "data_classification": "deidentified_test_fixture",
    "reviewed_at": REVIEWED_AT,
    "reviewed_by": REVIEWED_BY,
    "review_method": "manual_accounting_review",
    "fixture_source": "原 yiliao.xlsx 是某医疗企业的科目余额表,已脱敏所有供应商/客户/科目明细名后入册。",
    "confirmed_mappings": entries,
    "ignored_rows": [],
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"wrote {OUT} ({len(entries)} rows)")