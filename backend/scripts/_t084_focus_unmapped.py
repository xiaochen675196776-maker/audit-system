#!/usr/bin/env python3
"""TASK-084 聚焦诊断：检查 205201 未映射/unsafe 行的性质。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.file_parser import parse_trial_balance_import, slice_data_rows

FILE_PATH = r"D:\APP\谷歌\文件下载\205201-2023.xls"
# 验收映射的金额列索引
AMOUNT_COLS = [15, 16, 17, 18]
CODE_COL = 2
NAME_COL = 3


def _is_nonzero(v):
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    try:
        return float(s) != 0.0
    except (ValueError, TypeError):
        return False


def main():
    parsed = parse_trial_balance_import(FILE_PATH)
    all_rows = parsed["all_rows"]
    data_start = parsed["data_start_row"]
    rows = slice_data_rows(all_rows, data_start)
    print(f"数据行数: {len(rows)}")

    # 统计 9999 行
    rows_9999 = []
    rows_220206 = []
    for ri, row in enumerate(rows):
        code = str(row[CODE_COL]).strip() if CODE_COL < len(row) else ""
        if code == "9999":
            rows_9999.append(ri)
        if code == "220206":
            rows_220206.append(ri)

    print(f"\n=== code=9999 行数: {len(rows_9999)} ===")
    # 检查这些行的金额
    nonzero_9999 = 0
    zero_9999 = 0
    for ri in rows_9999:
        row = rows[ri]
        has_nonzero = any(
            _is_nonzero(row[c] if c < len(row) else None) for c in AMOUNT_COLS
        )
        if has_nonzero:
            nonzero_9999 += 1
        else:
            zero_9999 += 1
    print(f"  有非零金额: {nonzero_9999}")
    print(f"  全零金额: {zero_9999}")
    # 样本
    print(f"  前 3 行样本:")
    for ri in rows_9999[:3]:
        row = rows[ri]
        name = str(row[NAME_COL]).strip() if NAME_COL < len(row) else ""
        amounts = [row[c] if c < len(row) else None for c in AMOUNT_COLS]
        print(f"    row={ri} code=9999 name='{name}' amounts={amounts}")

    print(f"\n=== code=220206 行数: {len(rows_220206)} ===")
    nonzero_220206 = 0
    for ri in rows_220206:
        row = rows[ri]
        if any(_is_nonzero(row[c] if c < len(row) else None) for c in AMOUNT_COLS):
            nonzero_220206 += 1
    print(f"  有非零金额: {nonzero_220206}")
    print(f"  前 3 行样本:")
    for ri in rows_220206[:3]:
        row = rows[ri]
        name = str(row[NAME_COL]).strip() if NAME_COL < len(row) else ""
        amounts = [row[c] if c < len(row) else None for c in AMOUNT_COLS]
        print(f"    row={ri} code=220206 name='{name}' amounts={amounts}")

    # 统计所有 active 行（有非零金额）的 code 分布
    print(f"\n=== 有非零金额行的科目代码分布 (前 20) ===")
    from collections import Counter
    active_codes = Counter()
    for ri, row in enumerate(rows):
        if any(_is_nonzero(row[c] if c < len(row) else None) for c in AMOUNT_COLS):
            code = str(row[CODE_COL]).strip() if CODE_COL < len(row) else ""
            active_codes[code] += 1
    for code, cnt in active_codes.most_common(20):
        print(f"  code='{code}': {cnt}")

    # 空 code 的 active 行
    empty_code_active = active_codes.get("", 0)
    print(f"\n  空 code 但有非零金额的行: {empty_code_active}")

    # 检查空 code 行的 name 样本
    print(f"  空 code active 行前 5 样本:")
    cnt = 0
    for ri, row in enumerate(rows):
        code = str(row[CODE_COL]).strip() if CODE_COL < len(row) else ""
        if code == "" and any(_is_nonzero(row[c] if c < len(row) else None) for c in AMOUNT_COLS):
            name = str(row[NAME_COL]).strip() if NAME_COL < len(row) else ""
            amounts = [row[c] if c < len(row) else None for c in AMOUNT_COLS]
            print(f"    row={ri} name='{name}' amounts={amounts}")
            cnt += 1
            if cnt >= 5:
                break


if __name__ == "__main__":
    main()
