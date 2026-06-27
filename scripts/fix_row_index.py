"""从 git 提取原始 fixture 的 row_index,修正 v2 fixture 的 row_index。"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path("D:/APP/Codex-项目/13、审计系统")
FIXTURE_DIR = ROOT / "backend" / "tests" / "fixtures" / "task_093_confirmations"
GIT_REF = "9fb2063"  # TASK-093 anchor inheritance 修复前的 commit


def extract_original(file_key: str) -> list[dict]:
    """从 git ref 读取原始 fixture 的 row_index -> (src_code, name) 映射。"""
    path = f"backend/tests/fixtures/task_093_confirmations/{file_key}.json"
    cmd = ["git", "show", f"{GIT_REF}:{path}"]
    result = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return data.get("confirmed_mappings") or []


def fix_fixture(file_key: str) -> int:
    """修正 v2 fixture 的 row_index 与原始一致。

    对于合并过的 fixture(如 205201 把大量重复 row_index 合并),row_index
    取该 code 在原始 fixture 中最早的 row_index,这样回归测试能够匹配到
    analyze_result 的对应行。
    """
    fp = FIXTURE_DIR / f"{file_key}.json"
    if not fp.exists():
        print(f"  {file_key}: missing v2 fixture")
        return 0

    original = extract_original(file_key)
    if not original:
        print(f"  {file_key}: no original found")
        return 0

    # 构建 source_account_code -> [list of row_index] (按 row_index 升序)
    original_by_code: dict[str, list[int]] = {}
    for m in original:
        src = m.get("client_account_code") or ""
        ri = m.get("row_index")
        if src and ri is not None:
            original_by_code.setdefault(src, []).append(ri)
    for k, v in original_by_code.items():
        original_by_code[k] = sorted(set(v))

    # 读 v2 fixture,按 source_account_code 取原始 row_index 中的第一个
    v2 = json.loads(fp.read_text(encoding="utf-8"))
    code_counters: dict[str, int] = {}
    updated = 0
    unmatched = 0
    for m in v2.get("confirmed_mappings") or []:
        src = m.get("source_account_code") or ""
        if src not in original_by_code:
            unmatched += 1
            continue
        idx = code_counters.get(src, 0)
        if idx >= len(original_by_code[src]):
            # v2 比原始多了相同 code 的 entry(也合法),保持原 row_index
            unmatched += 1
            continue
        new_ri = original_by_code[src][idx]
        code_counters[src] = idx + 1
        if m.get("row_index") != new_ri:
            m["row_index"] = new_ri
            updated += 1

    if updated:
        fp.write_text(
            json.dumps(v2, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"  {file_key}: {updated} row_index updated (out of {len(v2.get('confirmed_mappings', []))}, unmatched={unmatched})")
    return updated


if __name__ == "__main__":
    for fk in ["huizhan", "112", "205201", "chengdu_dikang", "tb_2023", "yiliao"]:
        print(f"fixing {fk}:")
        fix_fixture(fk)