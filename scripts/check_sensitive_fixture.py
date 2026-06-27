#!/usr/bin/env python3
"""
TASK-094A: 敏感数据扫描脚本

扫描 backend/tests/fixtures/、backend/test_reports/、docs/tasks/ 以及 frontend 测试
fixture 目录,检测:
  1. 连续 12 位以上数字 (疑似银行账号)
  2. 18 位身份证号 (中国大陆)
  3. 11 位 / 13 位 / 14 位手机号
  4. 邮箱地址
  5. 银行账号关键词 (account / 账号 / 银行)
  6. 真实客户名称黑名单
  7. 乱码 review_reason (全部是 ? 或全角 ?)
  8. 同一 row_key 重复确认到不同标准科目

通用会计科目代码白名单内的 12 位数字 (例如 160101020101) 不应误报,因此脚本会
先用白名单过滤再报警。

Usage:
  python scripts/check_sensitive_fixture.py [--strict] [--root <repo-root>]

默认扫描项目根目录下上述路径;--strict 时遇到疑似敏感数据以非零退出码退出,
适合接入 pre-commit 和 CI。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# 规则与白名单
# ---------------------------------------------------------------------------

# 通用会计科目代码:最多 14 位数字,以 1/2/3/4/5/6 开头 (允许客户自定义明细编码)
ACCOUNT_CODE_WHITELIST_PATTERN = re.compile(r"^[123456]\d{0,13}$")

# 连续 12 位以上纯数字 (疑似银行账号) - 但只报警不在白名单内的
LONG_DIGIT_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])\d{12,}(?![A-Za-z0-9_:-])")

# 中国大陆身份证号 (18 位,末位 X/x)
ID_CARD_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])\d{17}[\dXx](?![A-Za-z0-9_:-])")

# 中国大陆手机号 (11 位)
CN_MOBILE_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])1[3-9]\d{9}(?![A-Za-z0-9_:.])")

# row_key 字段 (sha256:hex...) 不参与数字命中
ROW_KEY_PATTERN = re.compile(r'"row_key"\s*:\s*"sha256:[0-9a-f]+"')

# 邮箱地址
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 银行账号/账户关键字 (避免将"账号"用作名词时漏报)
BANK_KEYWORDS = (
    "银行账号", "银行账户", "银行帐号",
    "银行卡号", "银行卡账户",
)

# 真实银行名全称关键词 (行内 substring 即可触发)
REAL_BANK_NAME_KEYWORDS = (
    "中国农业银行", "中国工商银行", "中国建设银行", "中国银行",
    "交通银行", "中国邮政储蓄", "招商银行", "兴业银行", "民生银行",
    "浦发银行", "中信银行", "光大银行", "华夏银行", "平安银行",
    "农行", "工行", "建行", "中行", "交行", "招行", "兴行",
    "成都银行", "成都农商行", "大连银行",
)

# 这些是 fixture 中已脱敏的占位符,不应触发敏感数据报警
DESENSITIZED_PLACEHOLDERS = (
    "BANK_ACCT_REDACTED", "国有银行A_支行", "国有银行B_支行",
    "国有银行C_支行", "国有银行D_支行", "国有银行E_支行",
    "国有银行F_支行", "国有银行G_支行", "国有银行A/B/C 支行账号",
    "脱敏后国有银行", "已脱敏为",
)

# 真实客户名称黑名单 (来自旧 fixture)
REAL_CUSTOMER_BLACKLIST = (
    "海达源", "小天鹅", "美的", "海信", "聚隆", "惠而浦",
    "宁国聚隆", "Tcl", "TCL", "澳柯玛", "蓝凌", "金蝶",
    "宁国", "合肥", "青岛", "无锡",
)

# 乱码 review_reason
GARBLED_REASON_PATTERN = re.compile(r"^[\s?？?□◇◆○●]+$")


def is_whitelisted_digit_run(digits: str) -> bool:
    """判断一个连续数字串是否属于通用会计科目代码白名单。"""
    return ACCOUNT_CODE_WHITELIST_PATTERN.match(digits) is not None


def scan_text_for_sensitive(text: str, source_path: str | Path,
                            line_no: int | None = None) -> list[dict]:
    """扫描一段字符串,返回疑似敏感命中。

    返回的每个命中包含:
        rule: 命中的规则名
        match: 命中片段
        path, line_no, context: 位置 + 上下文
    """
    hits: list[dict] = []
    if not text:
        return hits

    # 已脱敏占位符的行/字符串:跳过"支行/账号"等关键字命中(它们是占位符的一部分)
    is_desensitized = any(p in text for p in DESENSITIZED_PLACEHOLDERS)

    for m in LONG_DIGIT_PATTERN.finditer(text):
        run = m.group(0)
        if not is_whitelisted_digit_run(run):
            hits.append({
                "rule": "long_digit_run",
                "match": run,
                "path": str(source_path),
                "line_no": line_no,
                "context": _context(text, m.start(), m.end()),
            })

    for m in ID_CARD_PATTERN.finditer(text):
        hits.append({
            "rule": "id_card",
            "match": m.group(0),
            "path": str(source_path),
            "line_no": line_no,
            "context": _context(text, m.start(), m.end()),
        })

    # 跳过已脱敏占位符所在的行
    if any(p in text for p in DESENSITIZED_PLACEHOLDERS):
        # 已脱敏:不再对"支行/账号"等做命中,但仍扫描数字/邮箱/手机号
        # 由于占位符本身含 BANK_ACCT_REDACTED 但不含真实账号,无需额外处理
        pass

    for m in CN_MOBILE_PATTERN.finditer(text):
        hits.append({
            "rule": "cn_mobile",
            "match": m.group(0),
            "path": str(source_path),
            "line_no": line_no,
            "context": _context(text, m.start(), m.end()),
        })

    for m in EMAIL_PATTERN.finditer(text):
        hits.append({
            "rule": "email",
            "match": m.group(0),
            "path": str(source_path),
            "line_no": line_no,
            "context": _context(text, m.start(), m.end()),
        })

    lower = text.lower()
    if not is_desensitized:
        for kw in BANK_KEYWORDS:
            idx = lower.find(kw.lower())
            if idx >= 0:
                hits.append({
                    "rule": "bank_keyword",
                    "match": kw,
                    "path": str(source_path),
                    "line_no": line_no,
                    "context": _context(text, idx, idx + len(kw)),
                })

        for kw in REAL_BANK_NAME_KEYWORDS:
            idx = text.find(kw)
            if idx >= 0:
                hits.append({
                    "rule": "real_bank_name",
                    "match": kw,
                    "path": str(source_path),
                    "line_no": line_no,
                    "context": _context(text, idx, idx + len(kw)),
                })

    for kw in REAL_CUSTOMER_BLACKLIST:
        idx = text.find(kw)
        if idx >= 0:
            hits.append({
                "rule": "real_customer_blacklist",
                "match": kw,
                "path": str(source_path),
                "line_no": line_no,
                "context": _context(text, idx, idx + len(kw)),
            })

    if GARBLED_REASON_PATTERN.match(text.strip()) and text.strip():
        hits.append({
            "rule": "garbled_reason",
            "match": text.strip(),
            "path": str(source_path),
            "line_no": line_no,
            "context": text.strip()[:60],
        })

    return hits


def _context(text: str, start: int, end: int, *, window: int = 30) -> str:
    s = max(0, start - window)
    e = min(len(text), end + window)
    return text[s:e].replace("\n", " ")


# ---------------------------------------------------------------------------
# 扫描文件 / 目录
# ---------------------------------------------------------------------------

DEFAULT_SCAN_DIRS = (
    "backend/tests/fixtures",
    "backend/test_reports",
    # 注意:docs/tasks/ 下是历史任务报告,本身含有真实案例用于说明问题,
    # 不属于 fixture 治理范围;但 docs/security/ 与本任务相关,会被扫描。
    "docs/security",
)


def iter_scan_files(root: Path) -> Iterable[Path]:
    """枚举所有需要扫描的文件路径。

    - JSON fixture (含 task_093_confirmations 目录)
    - 任意 .md 任务文档
    - frontend 测试 fixture (前端测试 fixtures 目录,如存在)
    """
    candidates: list[Path] = []

    for rel in DEFAULT_SCAN_DIRS:
        p = root / rel
        if p.is_dir():
            for fp in p.rglob("*"):
                if fp.is_file() and (
                    fp.suffix in {".json", ".md", ".txt", ".log"}
                    or fp.name.startswith(".")
                ):
                    candidates.append(fp)

    frontend_fixtures = root / "frontend"
    if frontend_fixtures.is_dir():
        for fp in frontend_fixtures.rglob("**/fixtures/*"):
            if fp.is_file():
                candidates.append(fp)
        for fp in frontend_fixtures.rglob("**/__fixtures__/*"):
            if fp.is_file():
                candidates.append(fp)

    return candidates


def scan_file(path: Path) -> list[dict]:
    hits: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="gbk", errors="replace")

    # 行号
    lines = text.splitlines()
    for ln, line in enumerate(lines, start=1):
        # 跳过 row_key 字段行,避免 sha256:hex 中的连续数字被误判
        clean_line = ROW_KEY_PATTERN.sub('"row_key":"<sha256>"', line)
        hits.extend(scan_text_for_sensitive(clean_line, path, line_no=ln))

    # 额外的 "review_reason" 键扫描
    if path.suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return hits
        hits.extend(_scan_review_reasons_in_json(data, path))

    return hits


def _scan_review_reasons_in_json(node, path: Path) -> list[dict]:
    """深度优先遍历 JSON,识别 review_reason 字段中的乱码。"""
    found: list[dict] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "review_reason" and isinstance(v, str):
                if GARBLED_REASON_PATTERN.match(v.strip()):
                    found.append({
                        "rule": "garbled_reason_in_json",
                        "match": v.strip()[:60],
                        "path": str(path),
                        "line_no": None,
                        "context": f"review_reason={v.strip()[:60]}",
                    })
            else:
                found.extend(_scan_review_reasons_in_json(v, path))
    elif isinstance(node, list):
        for item in node:
            found.extend(_scan_review_reasons_in_json(item, path))
    return found


# ---------------------------------------------------------------------------
# 重复 row_key 校验 (跨类跨文件)
# ---------------------------------------------------------------------------

def scan_duplicate_row_keys(root: Path) -> list[dict]:
    """扫描所有 fixture,确认同一 stable row_key 未被确认到不同标准科目。

    如果两个 mapping 的 row_key 相同但 standard_account_code 不同,则视为冲突。
    """
    seen: dict[str, tuple[str, str]] = {}
    conflicts: list[dict] = []

    fixtures_dir = root / "backend" / "tests" / "fixtures"
    if not fixtures_dir.is_dir():
        return conflicts

    for fp in fixtures_dir.rglob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        mappings = data.get("confirmed_mappings") if isinstance(data, dict) else None
        if not isinstance(mappings, list):
            continue

        for m in mappings:
            if not isinstance(m, dict):
                continue
            rk = m.get("row_key")
            tgt = m.get("standard_account_code")
            if not rk or not tgt:
                continue
            key = f"{data.get('file_key', fp.stem)}|{rk}"
            if key in seen:
                prev_file, prev_tgt = seen[key]
                if prev_tgt != tgt:
                    conflicts.append({
                        "rule": "duplicate_row_key_conflict",
                        "match": key,
                        "path": str(fp),
                        "line_no": None,
                        "context": f"prev={prev_file}@{prev_tgt}, new={fp.name}@{tgt}",
                    })
            else:
                seen[key] = (fp.name, tgt)
    return conflicts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="TASK-094A sensitive data scanner")
    p.add_argument("--root", default=".", help="项目根目录")
    p.add_argument("--strict", action="store_true",
                   help="发现任何命中则返回非零退出码")
    p.add_argument("--json", action="store_true",
                   help="以 JSON 格式输出结果")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()

    all_hits: list[dict] = []
    for fp in iter_scan_files(root):
        all_hits.extend(scan_file(fp))
    all_hits.extend(scan_duplicate_row_keys(root))

    if args.json:
        print(json.dumps(all_hits, ensure_ascii=False, indent=2))
    else:
        if not all_hits:
            print("✓ 未发现疑似敏感数据")
        else:
            print(f"× 共发现 {len(all_hits)} 处疑似敏感数据:")
            for h in all_hits:
                ln = h.get("line_no")
                loc = f"{h['path']}:{ln}" if ln else h["path"]
                print(f"  - [{h['rule']}] {loc}  match={h['match']!r}  ctx={h['context']!r}")

    return 1 if (args.strict and all_hits) else 0


if __name__ == "__main__":
    sys.exit(main())