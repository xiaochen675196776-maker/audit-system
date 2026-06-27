"""
TASK-094A: Fixture 治理自动化测试

验证:
1. 所有 fixture 为有效 JSON;
2. 不存在疑似银行账号(连续 12+ 位数字,排除白名单);
3. 不存在手机号、身份证号、邮箱;
4. review_reason 非空且非乱码;
5. review_evidence 非空;
6. reviewed_by 存在;
7. reviewed_at 存在;
8. 标准科目代码存在且启用;
9. 客户科目大类与标准科目大类兼容(走通用跨类校验);
10. 资产负债/收入成本/费用资产不得明显跨类;
11. 原值与备抵方向兼容;
12. 同一稳定 row_key 不得重复确认到不同标准科目。

参考 fixtures/task_093_confirmations/ 下六个文件:
- chengdu_dikang.json
- 112.json
- 205201.json
- huizhan.json
- tb_2023.json
- yiliao.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fixture_governance import (
    CONTRA_ACCOUNT_CODES,
    HARD_CROSS_CATEGORY_PAIRS,
    MappingPair,
    VALID_STANDARD_ACCOUNT_CODES,
    compute_row_key,
    is_garbled_review_reason,
    validate_fixture_mapping_semantics,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "task_093_confirmations"

EXPECTED_FIXTURE_FILES = (
    "chengdu_dikang.json",
    "112.json",
    "205201.json",
    "huizhan.json",
    "tb_2023.json",
    "yiliao.json",
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / name
    assert path.exists(), f"fixture {name} not found at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(params=list(EXPECTED_FIXTURE_FILES))
def fixture_data(request) -> dict:
    return _load_fixture(request.param)


@pytest.fixture(scope="module")
def all_fixtures() -> list[dict]:
    return [_load_fixture(name) for name in EXPECTED_FIXTURE_FILES]


# ---------------------------------------------------------------------------
# 1. 所有 fixture 为有效 JSON
# ---------------------------------------------------------------------------

def test_fixtures_are_valid_json() -> None:
    for name in EXPECTED_FIXTURE_FILES:
        path = FIXTURE_DIR / name
        assert path.exists(), f"fixture {name} missing"
        # 必须能解析
        json.loads(path.read_text(encoding="utf-8"))


def test_fixtures_have_v2_marker(all_fixtures) -> None:
    for data in all_fixtures:
        assert data.get("fixture_version") == 2, (
            f"{data.get('file_key')} 未升级到 fixture_version=2"
        )
        assert data.get("data_classification") == "deidentified_test_fixture", (
            f"{data.get('file_key')} 缺少 data_classification"
        )
        assert data.get("reviewed_by"), (
            f"{data.get('file_key')} 缺少 reviewed_by"
        )
        assert data.get("reviewed_at"), (
            f"{data.get('file_key')} 缺少 reviewed_at"
        )


# ---------------------------------------------------------------------------
# 2. 不存在疑似银行账号(连续 12+ 位数字)
# ---------------------------------------------------------------------------

LONG_DIGIT_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])\d{12,}(?![A-Za-z0-9_:-])")
WHITELIST_CODE_PATTERN = re.compile(r"^[123456]\d{0,13}$")
ROW_KEY_PATTERN = re.compile(r'"row_key"\s*:\s*"sha256:[0-9a-f]+"')


def _scan_text_for_long_digit(text: str) -> list[str]:
    if not text:
        return []
    # 跳过 row_key 字段,避免 sha256:hex 中的连续数字被误判
    text = ROW_KEY_PATTERN.sub('"row_key":"<sha256>"', text)
    hits: list[str] = []
    for m in LONG_DIGIT_PATTERN.finditer(text):
        run = m.group(0)
        if not WHITELIST_CODE_PATTERN.match(run):
            hits.append(run)
    return hits


def test_no_suspected_bank_account_in_fixture(all_fixtures) -> None:
    """每个 fixture 不能包含连续 12 位以上纯数字(已剔除白名单科目代码)。"""
    for data in all_fixtures:
        fk = data.get("file_key")
        raw = json.dumps(data, ensure_ascii=False)
        hits = _scan_text_for_long_digit(raw)
        assert not hits, (
            f"{fk} 检测到疑似银行账号: {hits[:3]} ... "
            f"(共 {len(hits)} 处)"
        )


# ---------------------------------------------------------------------------
# 3. 不存在手机号、身份证号、邮箱
# ---------------------------------------------------------------------------

ID_CARD_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])\d{17}[\dXx](?![A-Za-z0-9_:-])")
CN_MOBILE_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])1[3-9]\d{9}(?![A-Za-z0-9_:-])")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def test_no_id_card_mobile_email_in_fixture(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        raw = json.dumps(data, ensure_ascii=False)
        # 跳过 row_key 字段
        raw = ROW_KEY_PATTERN.sub('"row_key":"<sha256>"', raw)
        assert not ID_CARD_PATTERN.search(raw), f"{fk} 检测到身份证号"
        assert not CN_MOBILE_PATTERN.search(raw), f"{fk} 检测到手机号"
        assert not EMAIL_PATTERN.search(raw), f"{fk} 检测到邮箱"


# ---------------------------------------------------------------------------
# 4. review_reason 非空且非乱码
# ---------------------------------------------------------------------------

def test_review_reason_not_garbled(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            reason = m.get("review_reason") or ""
            assert reason.strip(), f"{fk}#{idx} review_reason 为空"
            assert not is_garbled_review_reason(reason), (
                f"{fk}#{idx} review_reason 为乱码: {reason!r}"
            )


def test_review_reason_forbids_placeholder_text(all_fixtures) -> None:
    forbidden = ("人工确认", "映射正确", "自动生成", "only auto")
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            reason = (m.get("review_reason") or "").strip()
            for kw in forbidden:
                assert kw not in reason, (
                    f"{fk}#{idx} review_reason 仅含占位词 '{kw}': {reason!r}"
                )


# ---------------------------------------------------------------------------
# 5. review_evidence 非空
# ---------------------------------------------------------------------------

def test_review_evidence_non_empty(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            ev = m.get("review_evidence")
            assert isinstance(ev, list) and ev, (
                f"{fk}#{idx} review_evidence 为空"
            )


# ---------------------------------------------------------------------------
# 6. reviewed_by 存在
# ---------------------------------------------------------------------------

def test_reviewed_by_present(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            assert m.get("reviewed_by"), (
                f"{fk}#{idx} 缺少 reviewed_by"
            )


# ---------------------------------------------------------------------------
# 7. reviewed_at 存在
# ---------------------------------------------------------------------------

def test_reviewed_at_present(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            assert m.get("reviewed_at"), (
                f"{fk}#{idx} 缺少 reviewed_at"
            )


# ---------------------------------------------------------------------------
# 8. 标准科目代码存在且启用
# ---------------------------------------------------------------------------

def test_standard_account_code_in_whitelist(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            tgt = m.get("standard_account_code")
            assert tgt in VALID_STANDARD_ACCOUNT_CODES, (
                f"{fk}#{idx} standard_account_code {tgt} 不在白名单"
            )


# ---------------------------------------------------------------------------
# 9 + 10 + 11. 跨类语义校验(走 validate_fixture_mapping_semantics)
# ---------------------------------------------------------------------------

def test_no_cross_category_mapping(all_fixtures) -> None:
    """对每条 fixture 映射调用通用跨类语义校验。"""
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            pair = MappingPair(
                source_account_code=m.get("source_account_code") or "",
                source_account_name=m.get("source_account_name_masked") or "",
                standard_account_code=m.get("standard_account_code") or "",
                standard_account_name=m.get("standard_account_name") or "",
                row_index=m.get("row_index"),
            )
            errs = validate_fixture_mapping_semantics(pair)
            assert not errs, (
                f"{fk}#{idx} (row={m.get('row_key')}) 跨类语义错误: "
                f"{errs}"
            )


def test_no_hard_cross_category_pairs(all_fixtures) -> None:
    """TASK-094A 强制红线:不允许 5 类硬性跨类组合。"""
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            src = m.get("source_account_code") or ""
            tgt = m.get("standard_account_code") or ""
            assert (src, tgt) not in HARD_CROSS_CATEGORY_PAIRS, (
                f"{fk}#{idx} 出现硬性跨类 ({src} -> {tgt})"
            )


# ---------------------------------------------------------------------------
# 12. 同一稳定 row_key 不得重复确认到不同标准科目
# ---------------------------------------------------------------------------

def test_no_duplicate_row_key_with_different_target(all_fixtures) -> None:
    seen: dict[str, dict[str, str]] = {}
    for data in all_fixtures:
        fk = data.get("file_key")
        for m in data.get("confirmed_mappings") or []:
            rk = m.get("row_key")
            tgt = m.get("standard_account_code")
            if not rk or not tgt:
                continue
            bucket = seen.setdefault(fk, {})
            if rk in bucket and bucket[rk] != tgt:
                pytest.fail(
                    f"{fk} 中 row_key={rk} 已被映射到 {bucket[rk]},"
                    f"现在又被映射到 {tgt},存在冲突"
                )
            bucket[rk] = tgt


# ---------------------------------------------------------------------------
# 13. 真实银行名称/客户黑名单扫描
# ---------------------------------------------------------------------------

REAL_BANK_NAME_KEYWORDS = (
    "农行", "工行", "建行", "中行", "交行", "招行", "兴行",
    "兴业银行", "民生银行", "浦发银行", "中信银行", "光大银行",
    "中国农业银行", "中国工商银行", "中国建设银行", "中国银行",
    "成都银行", "成都农商行", "大连银行", "宁国", "合肥", "青岛",
    "巴基斯坦",
)

REAL_CUSTOMER_BLACKLIST = (
    "海达源", "小天鹅", "美的", "海信", "聚隆", "惠而浦",
    "TCL", "Tcl", "澳柯玛", "蓝凌", "金蝶",
)


def test_no_real_bank_name_in_fixture(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        raw = json.dumps(data, ensure_ascii=False)
        # 跳过 row_key 字段
        raw = ROW_KEY_PATTERN.sub('"row_key":"<sha256>"', raw)
        for kw in REAL_BANK_NAME_KEYWORDS:
            assert kw not in raw, f"{fk} 仍包含真实银行/地名关键字: {kw!r}"


def test_no_real_customer_in_fixture(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        raw = json.dumps(data, ensure_ascii=False)
        # 跳过 row_key 字段
        raw = ROW_KEY_PATTERN.sub('"row_key":"<sha256>"', raw)
        for kw in REAL_CUSTOMER_BLACKLIST:
            assert kw not in raw, f"{fk} 仍包含真实客户关键字: {kw!r}"


# ---------------------------------------------------------------------------
# 14. 专项:确认错误映射已删除
# ---------------------------------------------------------------------------

KNOWN_BAD_PAIRS = (
    ("122201", "1403"),  # 往来款 → 原材料
    ("122202", "1403"),  # 代收代付 → 原材料
    ("147199", "1012"),  # 其他存货 → 其他货币资金
)


def test_known_bad_pairs_not_present(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            src = m.get("source_account_code") or ""
            tgt = m.get("standard_account_code") or ""
            assert (src, tgt) not in KNOWN_BAD_PAIRS, (
                f"{fk}#{idx} 含已知错误映射 {src} → {tgt}"
            )


# ---------------------------------------------------------------------------
# 15. row_key 一致性:相同 (file_key, source_account_code, masked_name) 必须
#     生成同样的 row_key,这是稳定性的核心。
# ---------------------------------------------------------------------------

def test_row_key_is_stable(all_fixtures) -> None:
    for data in all_fixtures:
        fk = data.get("file_key")
        for idx, m in enumerate(data.get("confirmed_mappings") or []):
            rk = m.get("row_key")
            expected = compute_row_key(
                m.get("source_account_code") or "",
                m.get("source_account_name_masked") or "",
                fk,
            )
            assert rk == expected, (
                f"{fk}#{idx} row_key 不稳定: fixture={rk} expected={expected}"
            )


# ---------------------------------------------------------------------------
# 16. fixture_governance 内部健壮性:对随机错误案例应报警
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "src_code,src_name,tgt_code,tgt_name",
    [
        ("122201", "往来款", "1403", "原材料"),       # 错
        ("122202", "代收代付", "1403", "原材料"),     # 错
        ("147199", "其他存货", "1012", "其他货币资金"),  # 错
        ("6601", "销售费用", "112201", "应收账款"),   # 费用→资产
        ("6001", "主营业务收入", "1403", "原材料"),  # 收入→资产
        # 122201 往来款 → 1012 其他货币资金由 HARD_CROSS_CATEGORY_PAIRS
        # 检测,见 test_no_hard_cross_category_pairs;validate_fixture_mapping_semantics
        # 本身在大类层面不报警(同属 asset)。
    ],
)
def test_validate_fixture_mapping_semantics_flags_known_bad(
    src_code: str, src_name: str, tgt_code: str, tgt_name: str,
) -> None:
    pair = MappingPair(
        source_account_code=src_code,
        source_account_name=src_name,
        standard_account_code=tgt_code,
        standard_account_name=tgt_name,
    )
    errs = validate_fixture_mapping_semantics(pair)
    assert errs, f"({src_code} → {tgt_code}) 应被识别为错误,但未报警"


@pytest.mark.parametrize(
    "src_code,src_name,tgt_code,tgt_name",
    [
        ("1002", "银行存款", "1002", "银行存款"),  # 资产 → 资产 OK
        ("160101", "固定资产-原值", "1602", "减:固定资产-累计折旧"),  # 资产 → 资产备抵 OK
        ("1602", "减:固定资产-累计折旧", "1602", "减:固定资产-累计折旧"),  # 备抵 → 备抵 OK
        ("112101", "应收票据", "112102", "减:应收票据-坏账准备"),  # 资产 → 资产备抵 OK
        ("1002", "银行存款", "1602", "减:固定资产-累计折旧"),  # 资产 → 资产备抵 OK (反向)
        ("66030101", "利息收入", "660302", "其中:利息收入"),  # 客户口径下费用类的冲减项映射到收入明细
    ],
)
def test_validate_fixture_mapping_semantics_passes_legitimate(
    src_code: str, src_name: str, tgt_code: str, tgt_name: str,
) -> None:
    pair = MappingPair(
        source_account_code=src_code,
        source_account_name=src_name,
        standard_account_code=tgt_code,
        standard_account_name=tgt_name,
    )
    errs = validate_fixture_mapping_semantics(pair)
    assert not errs, f"({src_code} → {tgt_code}) 不应报警: {errs}"


# ---------------------------------------------------------------------------
# 17. CONTRA_ACCOUNT_CODES 自洽性:每个备抵 code 都应该在白名单里
# ---------------------------------------------------------------------------

def test_contra_codes_are_in_whitelist() -> None:
    for code in CONTRA_ACCOUNT_CODES:
        assert code in VALID_STANDARD_ACCOUNT_CODES, (
            f"备抵 code {code} 不在标准科目白名单内"
        )