#!/usr/bin/env python3
"""
TASK-095A: repository sensitive data scanner.

The scanner covers repository text files by default. It intentionally includes
docs/tasks, docs/security, backend/test_reports, tests, frontend source, scripts,
and GitHub workflow files. Only technical/generated directories and binary file
types are excluded.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


TASK_ID = "TASK-095A"

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
}

TEXT_EXTENSIONS = {
    ".py",
    ".ts",
    ".vue",
    ".js",
    ".json",
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".txt",
    ".csv",
}

BINARY_EXTENSIONS = {
    ".xlsx",
    ".xls",
    ".xlsm",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".zip",
    ".7z",
    ".rar",
    ".gz",
    ".tar",
    ".db",
    ".sqlite",
    ".sqlite3",
}

LOCAL_SENSITIVE_TERMS = Path("scripts") / "sensitive_terms.local.json"


# ---------------------------------------------------------------------------
# Rules and safe placeholders
# ---------------------------------------------------------------------------

ACCOUNT_CODE_WHITELIST_PATTERN = re.compile(r"^[123456]\d{0,13}$")
ACCOUNT_CODE_CONTEXT_PATTERN = re.compile(
    r'(?i)(?:"?(?:account_code|source_account_code)"?|\b科目代码\b)\s*[:：=]\s*["“”\'`]*$'
)
ACCOUNT_CODE_TABLE_CONTEXT_PATTERN = re.compile(
    r"(?i)(?:^|[|,])\s*(?:account_code|source_account_code|科目代码)\s*(?:[|,]|$)"
)

LONG_DIGIT_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])\d{12,}(?![A-Za-z0-9_:-])")
ID_CARD_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])\d{17}[\dXx](?![A-Za-z0-9_:-])")
CN_MOBILE_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])1[3-9]\d{9}(?![A-Za-z0-9_:.])")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TAX_ID_CONTEXT_PATTERN = re.compile(r"(统一社会信用代码|纳税人识别号|税号)")
TAX_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Z0-9]{15,20}(?![A-Za-z0-9])")
PROPERTY_CERT_PATTERN = re.compile(
    r"(不动产权|房产证|土地证)[^，。；;\n]{0,20}[A-Za-z0-9第\-]{6,}号?"
)
REAL_BANK_BRANCH_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{2,12}(?:银行|农商行|信用社|商业银行)"
    r"[\u4e00-\u9fffA-Za-z0-9_]{0,20}(?:支行|分行|营业部)"
)

ROW_KEY_PATTERN = re.compile(r'"row_key"\s*:\s*"sha256:[0-9a-f]+"')
GARBLED_REASON_PATTERN = re.compile(r"^[\s?？□◇◆○●]+$")

DESENSITIZED_PLACEHOLDERS = (
    "<账户号样例",
    "<银行账号样例",
    "<客户名样例",
    "<真实客户名样例",
    "<真实供应商名样例",
    "<真实员工名样例",
    "<不动产权证样例>",
    "BANK_ACCT_REDACTED",
    "银行A_支行",
    "银行B_支行",
    "国有银行A_支行",
    "国有银行B_支行",
    "国有银行C_支行",
    "客户A",
    "供应商B",
    "员工001",
    "项目P001",
    "已脱敏为",
    "脱敏后",
)
PUBLIC_DEPENDENCY_EMAILS = {
    "i" + "@izs.me",
}


def is_whitelisted_digit_run(
    digits: str,
    *,
    text: str | None = None,
    start: int | None = None,
    end: int | None = None,
) -> bool:
    """Allow long account-code-like digits only in explicit field context."""
    if not ACCOUNT_CODE_WHITELIST_PATTERN.match(digits):
        return False
    if text is None or start is None or end is None:
        return False

    left = text[max(0, start - 80):start]
    if ACCOUNT_CODE_CONTEXT_PATTERN.search(left):
        return True

    # Markdown/CSV table rows may be represented as "account_code | 100201...".
    row_left = text[:start]
    if ACCOUNT_CODE_TABLE_CONTEXT_PATTERN.search(row_left):
        return True

    return False


def load_sensitive_terms(root: str | Path) -> list[str]:
    """Load local sensitive terms without requiring them to be committed."""
    path = Path(root) / LOCAL_SENSITIVE_TERMS
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    terms: list[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, str):
            value = node.strip()
            if len(value) >= 2:
                terms.append(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)
        elif isinstance(node, dict):
            for value in node.values():
                collect(value)

    collect(data)
    return sorted(set(terms), key=len, reverse=True)


def scan_text_for_sensitive(
    text: str,
    source_path: str | Path,
    line_no: int | None = None,
    *,
    sensitive_terms: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not text:
        return hits

    is_desensitized = any(p in text for p in DESENSITIZED_PLACEHOLDERS)

    for m in ID_CARD_PATTERN.finditer(text):
        hits.append(_hit("id_card", m.group(0), source_path, line_no, text, m.start(), m.end()))

    for m in CN_MOBILE_PATTERN.finditer(text):
        hits.append(_hit("cn_mobile", m.group(0), source_path, line_no, text, m.start(), m.end()))

    for m in LONG_DIGIT_PATTERN.finditer(text):
        run = m.group(0)
        if ID_CARD_PATTERN.fullmatch(run):
            continue
        if is_whitelisted_digit_run(run, text=text, start=m.start(), end=m.end()):
            continue
        hits.append(_hit("long_digit_run", run, source_path, line_no, text, m.start(), m.end()))

    for m in EMAIL_PATTERN.finditer(text):
        if _is_allowed_public_dependency_email(m.group(0), source_path):
            continue
        hits.append(_hit("email", m.group(0), source_path, line_no, text, m.start(), m.end()))

    if not is_desensitized:
        for m in REAL_BANK_BRANCH_PATTERN.finditer(text):
            if _is_generic_bank_branch_category(m.group(0)):
                continue
            hits.append(_hit("real_bank_name", m.group(0), source_path, line_no, text, m.start(), m.end()))

        if TAX_ID_CONTEXT_PATTERN.search(text):
            for m in TAX_ID_PATTERN.finditer(text):
                hits.append(_hit("tax_id", m.group(0), source_path, line_no, text, m.start(), m.end()))

        for m in PROPERTY_CERT_PATTERN.finditer(text):
            hits.append(_hit("property_certificate", m.group(0), source_path, line_no, text, m.start(), m.end()))

        for term in sensitive_terms or ():
            idx = text.find(term)
            if idx >= 0:
                hits.append(_hit("local_sensitive_term", term, source_path, line_no, text, idx, idx + len(term)))

    if GARBLED_REASON_PATTERN.match(text.strip()) and text.strip():
        hits.append({
            "rule": "garbled_reason",
            "match": text.strip(),
            "path": _path_string(source_path),
            "line_no": line_no,
            "context": text.strip()[:60],
        })

    return hits


def _hit(
    rule: str,
    match: str,
    source_path: str | Path,
    line_no: int | None,
    text: str,
    start: int,
    end: int,
) -> dict[str, Any]:
    return {
        "rule": rule,
        "match": match,
        "path": _path_string(source_path),
        "line_no": line_no,
        "context": _context(text, start, end),
    }


def _context(text: str, start: int, end: int, *, window: int = 30) -> str:
    s = max(0, start - window)
    e = min(len(text), end + window)
    return text[s:e].replace("\n", " ")


def _path_string(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _is_allowed_public_dependency_email(email: str, source_path: str | Path) -> bool:
    path = _path_string(source_path)
    return path.endswith("package-lock.json") and email in PUBLIC_DEPENDENCY_EMAILS


def _is_generic_bank_branch_category(value: str) -> bool:
    return "真实银行支行" in value or "银行支行占位" in value


# ---------------------------------------------------------------------------
# File and repository scanning
# ---------------------------------------------------------------------------

def iter_scan_files(root: Path) -> Iterable[Path]:
    root = Path(root).resolve()
    files: list[Path] = []

    git_candidates = _iter_git_candidate_files(root)
    if git_candidates is not None:
        for path in git_candidates:
            if _is_local_sensitive_terms_file(root, path):
                continue
            if _has_excluded_dir(root, path):
                continue
            if path.is_file() and is_scan_text_file(path):
                files.append(path)
        return sorted(files, key=lambda p: _path_string(p.relative_to(root)))

    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in DEFAULT_EXCLUDE_DIRS]
        current_path = Path(current)
        for filename in filenames:
            path = current_path / filename
            if _is_local_sensitive_terms_file(root, path):
                continue
            if is_scan_text_file(path):
                files.append(path)

    return sorted(files, key=lambda p: _path_string(p.relative_to(root)))


def _iter_git_candidate_files(root: Path) -> list[Path] | None:
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "core.quotePath=false",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, UnicodeDecodeError):
        return None

    if proc.returncode != 0:
        return None

    return [root / line for line in proc.stdout.splitlines() if line.strip()]


def _has_excluded_dir(root: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root)
    except ValueError:
        return False
    return any(part in DEFAULT_EXCLUDE_DIRS for part in rel.parts[:-1])


def is_scan_text_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return False
    return suffix in TEXT_EXTENSIONS


def scan_file(
    path: Path,
    *,
    display_path: str | Path | None = None,
    sensitive_terms: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    source_path = display_path if display_path is not None else path

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="gbk", errors="replace")
    except OSError as exc:
        return [{
            "rule": "file_read_error",
            "match": type(exc).__name__,
            "path": _path_string(source_path),
            "line_no": None,
            "context": str(exc),
        }]

    for ln, line in enumerate(text.splitlines(), start=1):
        clean_line = ROW_KEY_PATTERN.sub('"row_key":"<sha256>"', line)
        hits.extend(
            scan_text_for_sensitive(
                clean_line,
                source_path,
                line_no=ln,
                sensitive_terms=sensitive_terms,
            )
        )

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return hits
        hits.extend(_scan_review_reasons_in_json(data, source_path))

    return hits


def scan_repository(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    sensitive_terms = load_sensitive_terms(root_path)
    scan_files = list(iter_scan_files(root_path))

    all_hits: list[dict[str, Any]] = []
    for path in scan_files:
        rel_path = path.relative_to(root_path)
        all_hits.extend(scan_file(path, display_path=rel_path, sensitive_terms=sensitive_terms))

    all_hits.extend(scan_duplicate_row_keys(root_path))

    return {
        "task": TASK_ID,
        "root": _path_string(root_path),
        "files_scanned": len(scan_files),
        "scanned_directories": _summarize_scanned_directories(root_path, scan_files),
        "directories_excluded": sorted(DEFAULT_EXCLUDE_DIRS),
        "scan_extensions": sorted(TEXT_EXTENSIONS),
        "local_sensitive_terms_loaded": len(sensitive_terms),
        "hits": all_hits,
        "hit_count": len(all_hits),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def _is_local_sensitive_terms_file(root: Path, path: Path) -> bool:
    try:
        return path.resolve().relative_to(root) == LOCAL_SENSITIVE_TERMS
    except ValueError:
        return False


def _summarize_scanned_directories(root: Path, files: list[Path]) -> list[str]:
    directories: set[str] = set()
    for path in files:
        rel = path.relative_to(root)
        parts = rel.parts
        if not parts:
            continue
        if parts[0] == "docs" and len(parts) > 1:
            directories.add(_path_string(Path(*parts[:2])))
        elif parts[0] == "backend" and len(parts) > 1:
            directories.add(_path_string(Path(*parts[:2])))
        elif parts[0] == "frontend" and len(parts) > 1:
            directories.add(_path_string(Path(*parts[:2])))
        elif parts[0] == ".github" and len(parts) > 1:
            directories.add(_path_string(Path(*parts[:2])))
        else:
            directories.add(parts[0])
    return sorted(directories)


def _scan_review_reasons_in_json(node: Any, path: str | Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "review_reason" and isinstance(value, str):
                stripped = value.strip()
                if stripped and GARBLED_REASON_PATTERN.match(stripped):
                    found.append({
                        "rule": "garbled_reason_in_json",
                        "match": stripped[:60],
                        "path": _path_string(path),
                        "line_no": None,
                        "context": f"review_reason={stripped[:60]}",
                    })
            else:
                found.extend(_scan_review_reasons_in_json(value, path))
    elif isinstance(node, list):
        for item in node:
            found.extend(_scan_review_reasons_in_json(item, path))
    return found


# ---------------------------------------------------------------------------
# Duplicate row_key governance scan
# ---------------------------------------------------------------------------

def scan_duplicate_row_keys(root: Path) -> list[dict[str, Any]]:
    seen: dict[str, tuple[str, str]] = {}
    conflicts: list[dict[str, Any]] = []

    fixtures_dir = root / "backend" / "tests" / "fixtures"
    if not fixtures_dir.is_dir():
        return conflicts

    for fp in fixtures_dir.rglob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue

        mappings = data.get("confirmed_mappings") if isinstance(data, dict) else None
        if not isinstance(mappings, list):
            continue

        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            row_key = mapping.get("row_key")
            target = mapping.get("standard_account_code")
            if not row_key or not target:
                continue
            key = f"{data.get('file_key', fp.stem)}|{row_key}"
            if key in seen:
                prev_file, prev_target = seen[key]
                if prev_target != target:
                    conflicts.append({
                        "rule": "duplicate_row_key_conflict",
                        "match": key,
                        "path": _path_string(fp.relative_to(root)),
                        "line_no": None,
                        "context": f"prev={prev_file}@{prev_target}, new={fp.name}@{target}",
                    })
            else:
                seen[key] = (fp.name, target)
    return conflicts


# ---------------------------------------------------------------------------
# Reporting and CLI
# ---------------------------------------------------------------------------

def write_json_report(result: dict[str, Any], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_markdown_report(result: dict[str, Any], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# {result['task']} 敏感数据扫描报告",
        "",
        f"- 生成时间: {result['generated_at']}",
        f"- 扫描根目录: `{result['root']}`",
        f"- files_scanned: {result['files_scanned']}",
        f"- hit_count: {result['hit_count']}",
        f"- excluded_dirs: {', '.join(result['directories_excluded'])}",
        f"- local_sensitive_terms_loaded: {result['local_sensitive_terms_loaded']}",
        "",
        "## 扫描目录",
        "",
    ]
    lines.extend(f"- `{directory}`" for directory in result["scanned_directories"])
    lines.extend(["", "## 命中结果", ""])
    if result["hit_count"] == 0:
        lines.append("未发现疑似敏感数据。")
    else:
        lines.append("发现疑似敏感数据。为避免报告写入敏感值,以下仅列出规则和位置。")
        lines.append("")
        for hit in result["hits"]:
            loc = f"{hit['path']}:{hit['line_no']}" if hit.get("line_no") else hit["path"]
            lines.append(f"- `{hit['rule']}` at `{loc}`")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_human_report(result: dict[str, Any]) -> None:
    print(f"files_scanned: {result['files_scanned']}")
    print(f"hit_count: {result['hit_count']}")
    print(f"excluded_dirs: {', '.join(result['directories_excluded'])}")

    if not result["hits"]:
        print("PASS 未发现疑似敏感数据")
        return

    print(f"FAIL 共发现 {result['hit_count']} 处疑似敏感数据:")
    for hit in result["hits"]:
        loc = f"{hit['path']}:{hit['line_no']}" if hit.get("line_no") else hit["path"]
        print(f"  - [{hit['rule']}] {loc} match=<redacted> ctx=<redacted>")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TASK-095A repository sensitive data scanner")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--strict", action="store_true", help="发现任何命中则返回非零退出码")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出扫描摘要")
    parser.add_argument("--report-json", help="写入 JSON 扫描报告")
    parser.add_argument("--report-md", help="写入 Markdown 扫描报告")
    args = parser.parse_args(argv)

    result = scan_repository(args.root)

    if args.report_json:
        write_json_report(result, args.report_json)
    if args.report_md:
        write_markdown_report(result, args.report_md)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human_report(result)

    return 1 if (args.strict and result["hit_count"]) else 0


if __name__ == "__main__":
    sys.exit(main())
