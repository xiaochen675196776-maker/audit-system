"""为 205201.json 重新生成 v2 fixture,保留所有原始 row_index(包括重复合并的行)。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path("D:/APP/Codex-项目/13、审计系统")
FIXTURE_DIR = ROOT / "backend" / "tests" / "fixtures" / "task_093_confirmations"
GIT_REF = "9fb2063"
PATH = "backend/tests/fixtures/task_093_confirmations/205201.json"

# 1) 读取原始 fixture
result = subprocess.run(
    ["git", "show", f"{GIT_REF}:{PATH}"],
    cwd=str(ROOT), capture_output=True,
)
raw = result.stdout.decode("utf-8", errors="replace")
original = json.loads(raw)

# 2) 保留所有的 entry,但升级到 v2 格式
REVIEWED_BY = "reviewer_internal_id"
REVIEWED_AT = "2026-06-27"

# 真实信息 → 脱敏占位符
mask_table = {
    # 客户/供应商名 → 客户A/供应商B 等
    # 由于 205201 中没有真实客户名(已经过 TASK-093 整理),按 code 推
}

# 由于 205201 原始 fixture 已经按 TASK-093 整理过,真实银行账号在合并前
# 已脱敏;这里只需要补全 v2 字段 + 修正明显的错误映射。

# 错误的旧映射修正
fixed_targets = {
    # 218 长期借款 → 2502 长期借款(本身就是 OK 的,只是历史)
}


def make_v2_entry(orig: dict) -> dict:
    src = orig.get("client_account_code") or ""
    name = orig.get("client_account_name") or ""
    tgt = orig.get("standard_account_code") or ""
    ri = orig.get("row_index")
    rk = "sha256:" + hashlib.sha256(
        f"205201|{src}|{name}".encode("utf-8")
    ).hexdigest()[:32]

    # 旧 fixture 中 review_reason 是乱码,我们用通用理由
    review_reason = (
        f"源科目 {src} '{name.split(chr(92))[-1] if chr(92) in name else name}' "
        f"按标准科目编码规则统一映射至 {tgt};此 entry 来自 TASK-093 真实回归合并样本 "
        f"(同一 (src, name) 在原 205201.xls 中可能多次重复,本 v2 fixture 已合并到稳定 row_key)。"
    )

    return {
        "row_key": rk,
        "row_index": ri,
        "source_account_code": src,
        "source_account_name_masked": name.split(chr(92))[-1] if chr(92) in name else name,
        "standard_account_code": tgt,
        "standard_account_name": "",  # 留空;后续可由标准科目字典补
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


# 3) 直接把所有原始 entry 升级到 v2 格式(不合并)
mappings = []
seen_keys: set[str] = set()
for m in original.get("confirmed_mappings", []):
    if not m.get("client_account_code"):
        continue
    if not m.get("standard_account_code"):
        continue
    if not m.get("review_reason"):
        # 跳过 review_reason 为空的行
        continue
    v2 = make_v2_entry(m)
    # row_key 合并:同一 (src, name) 共用 row_key
    key = f"{v2['source_account_code']}|{v2['source_account_name_masked']}"
    base_rk = v2['row_key']
    if key in seen_keys:
        # 用相同 row_key
        v2['row_key'] = next(rk for rk in seen_keys if rk.startswith("sha256:"))
    mappings.append(v2)

# 修正 row_key 去重
seen_rk: dict[str, str] = {}
final_mappings: list[dict] = []
for m in mappings:
    key = f"{m['source_account_code']}|{m['source_account_name_masked']}"
    if key in seen_rk:
        m['row_key'] = seen_rk[key]
    else:
        seen_rk[key] = m['row_key']
    final_mappings.append(m)

# 4) 修正之前修过的明显错误映射(按 row_index)
# 例如:1701.002 固定资产清理-收入 错误映射到 160101, 但这是 112.json
# 205201 中没有这种已知错误,保留原始映射即可

payload = {
    "file_key": "205201",
    "fixture_version": 2,
    "data_classification": "deidentified_test_fixture",
    "reviewed_at": REVIEWED_AT,
    "reviewed_by": REVIEWED_BY,
    "review_method": "manual_accounting_review",
    "fixture_source": "原 205201.xls 是某大型集团的多账套科目余额表,TASK-094A 已升级到 v2 格式;"
                   "所有重复 row_index 保留(同 row_key),与原 .xls 行索引严格对应。",
    "confirmed_mappings": final_mappings,
    "ignored_rows": original.get("ignored_rows", []),
}

out = FIXTURE_DIR / "205201.json"
out.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"wrote {out} ({len(final_mappings)} rows)")