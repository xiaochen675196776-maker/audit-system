from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_sensitive_fixture.py"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("check_sensitive_fixture", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scanner = _load_scanner()


ACCOUNT_NO = "622202" + "123456" + "7890123"
ACCOUNT_CODE = "100201" + "010101"
MOBILE_NO = "138" + "0013" + "8000"
ID_CARD_NO = "110101" + "199003" + "074512"
EMAIL = "audit" + "@" + "example.com"
BANK_BRANCH = "中国农业" + "银行" + "测试支行"
LOCAL_CUSTOMER_TERM = "敏感客户" + "测试词"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_docs_tasks_are_scanned(tmp_path: Path) -> None:
    marker = _write(tmp_path / "docs" / "tasks" / "TASK-095A.md", "ok")

    files = set(scanner.iter_scan_files(tmp_path))

    assert marker in files


def test_docs_security_are_scanned(tmp_path: Path) -> None:
    marker = _write(tmp_path / "docs" / "security" / "TASK-095A.md", "ok")

    files = set(scanner.iter_scan_files(tmp_path))

    assert marker in files


def test_markdown_full_account_number_is_hit() -> None:
    hits = scanner.scan_text_for_sensitive(
        f"报告文本包含完整账号 {ACCOUNT_NO}。",
        "docs/tasks/TASK-095A.md",
    )

    assert any(hit["rule"] == "long_digit_run" for hit in hits)


def test_account_code_field_allows_legal_account_code() -> None:
    hits = scanner.scan_text_for_sensitive(
        f'"account_code": "{ACCOUNT_CODE}"',
        "backend/tests/fixtures/sample.json",
    )

    assert not [hit for hit in hits if hit["rule"] == "long_digit_run"]


def test_plain_text_same_digits_are_not_account_code_whitelisted() -> None:
    hits = scanner.scan_text_for_sensitive(
        f"自然语言中的长数字 {ACCOUNT_CODE} 不能按科目代码放行。",
        "docs/tasks/TASK-095A.md",
    )

    assert any(hit["rule"] == "long_digit_run" for hit in hits)


def test_mobile_number_is_hit() -> None:
    hits = scanner.scan_text_for_sensitive(f"联系电话 {MOBILE_NO}", "sample.md")

    assert any(hit["rule"] == "cn_mobile" for hit in hits)


def test_id_card_number_is_hit() -> None:
    hits = scanner.scan_text_for_sensitive(f"证件号 {ID_CARD_NO}", "sample.md")

    assert any(hit["rule"] == "id_card" for hit in hits)


def test_email_is_hit() -> None:
    hits = scanner.scan_text_for_sensitive(f"联系人 {EMAIL}", "sample.md")

    assert any(hit["rule"] == "email" for hit in hits)


def test_real_bank_branch_is_hit() -> None:
    hits = scanner.scan_text_for_sensitive(f"开户行为{BANK_BRANCH}", "sample.md")

    assert any(hit["rule"] == "real_bank_name" for hit in hits)


def test_local_customer_term_is_hit(tmp_path: Path) -> None:
    local_terms = tmp_path / "scripts" / "sensitive_terms.local.json"
    _write(
        local_terms,
        json.dumps({"customers": [LOCAL_CUSTOMER_TERM]}, ensure_ascii=False),
    )

    terms = scanner.load_sensitive_terms(tmp_path)
    hits = scanner.scan_text_for_sensitive(
        f"本行包含{LOCAL_CUSTOMER_TERM}。",
        "sample.md",
        sensitive_terms=terms,
    )

    assert any(hit["rule"] == "local_sensitive_term" for hit in hits)


def test_placeholders_are_not_hit() -> None:
    hits = scanner.scan_text_for_sensitive(
        "<账户号样例001> 银行A_支行01 客户A 供应商B 员工001 项目P001",
        "sample.md",
    )

    assert hits == []


def test_current_repository_scan_has_zero_hits() -> None:
    result = scanner.scan_repository(REPO_ROOT)

    assert result["hit_count"] == 0


def test_strict_mode_returns_nonzero_when_hits_exist(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "tasks" / "TASK-095A.md", f"账号 {ACCOUNT_NO}")

    assert scanner.main(["--strict", "--root", str(tmp_path)]) == 1


def test_strict_mode_returns_zero_when_no_hits_exist(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "tasks" / "TASK-095A.md", "客户A 银行A_支行01")

    assert scanner.main(["--strict", "--root", str(tmp_path)]) == 0
