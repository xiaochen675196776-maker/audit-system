#!/usr/bin/env python3
"""TASK-084: 205201-2023.xls 诊断脚本。

诊断目标：
  1. 列出文件所有 sheet 的行列概况
  2. 对每个 sheet 输出每列的非空/非零统计
  3. 特别关注验收脚本中映射的 col_2/col_3/col_15~col_18
  4. 判断金额是否真的不存在（A/B/C/D 哪种情况）

判定标准：
  A = 金额在当前映射列中 → 无需修复，验收应通过
  B = 金额在其他列或其他 sheet → 修字段映射/解析器
  C = 文件真的没有金额列 → 保持验收失败，样本不合格
  D = 解析器无法正确读取文件 → 修解析器
"""

import sys
import os
from pathlib import Path

# 确保 backend 目录在 path 中
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

FILE_PATH = r"D:\APP\谷歌\文件下载\205201-2023.xls"

# 验收脚本中使用的字段映射
FIELD_MAPPINGS = [
    {"column_id": "col_2", "field_name": "account_code"},
    {"column_id": "col_3", "field_name": "account_name"},
    {"column_id": "col_15", "field_name": "opening_amount", "period_type": "opening",
     "split_mode": "single_as_debit"},
    {"column_id": "col_16", "field_name": "current_debit", "period_type": "current",
     "split_mode": "two_column", "debit_column_id": "col_16", "credit_column_id": "col_17"},
    {"column_id": "col_17", "field_name": "current_credit", "period_type": "current",
     "split_mode": "two_column", "debit_column_id": "col_16", "credit_column_id": "col_17"},
    {"column_id": "col_18", "field_name": "ending_amount", "period_type": "ending",
     "split_mode": "single_as_debit"},
]


def _is_numeric(v) -> bool:
    """判断值是否为非零数值。"""
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    try:
        return float(s) != 0.0
    except (ValueError, TypeError):
        return False


def _is_nonempty(v) -> bool:
    """判断值是否非空。"""
    if v is None:
        return False
    s = str(v).strip()
    return s != "" and s != "None"


def _col_stats(data_rows, ncols):
    """每列统计，返回 list of (nonempty, nonzero, samples)。"""
    stats = []
    for cx in range(ncols):
        nonempty = 0
        nonzero = 0
        samples = []
        for row in data_rows:
            v = row[cx] if cx < len(row) else None
            if _is_nonempty(v):
                nonempty += 1
                if len(samples) < 5:
                    samples.append(repr(v))
            if _is_numeric(v):
                nonzero += 1
        stats.append((nonempty, nonzero, samples))
    return stats


def _print_col_stats(stats, headers=None, label=""):
    """格式化输出每列统计。"""
    ncols = len(stats)
    hdr_label = "表头" if headers else ""
    print(f"\n  每列统计 ({ncols} 列) {label}:")
    print(f"  {'列索引':>6} | {'表头':>20} | {'非空数':>6} | {'非零数':>6}")
    print(f"  {'─' * 6} | {'─' * 20} | {'─' * 6} | {'─' * 6}")
    for cx, (nonempty, nonzero, _) in enumerate(stats):
        hdr = headers[cx] if headers and cx < len(headers) else ""
        print(f"  col_{cx:>3} | {hdr:>20} | {nonempty:>6} | {nonzero:>6}")


def _print_mapped_cols(stats, headers, label=""):
    """重点列诊断。"""
    print(f"\n  ★ 重点列诊断 {label}:")
    for fm in FIELD_MAPPINGS:
        cid = fm["column_id"]
        fname = fm["field_name"]
        idx = int(cid.replace("col_", ""))
        if idx >= len(stats):
            print(f"    {cid} ({fname}): ❌ 列越界 (共 {len(stats)} 列)")
            continue
        nonempty, nonzero, samples = stats[idx]
        hdr = headers[idx] if headers and idx < len(headers) else "(无)"
        status = "✅" if nonzero > 0 else ("⚠️ 有值但全为零" if nonempty > 0 else "❌ 全空")
        print(f"    {cid} ({fname}) → 表头'{hdr}': nonempty={nonempty}, nonzero={nonzero} {status}")
        for s in samples[:3]:
            print(f"      样本: {s}")


def diagnose_xlrd(encoding_override=None):
    """使用 xlrd 逐 sheet 诊断。"""
    import xlrd

    label = f"(encoding_override={encoding_override!r})" if encoding_override else ""
    print("=" * 80)
    print(f"诊断方式 1: xlrd 逐 sheet 解析 {label}")
    print("=" * 80)

    wb = xlrd.open_workbook(FILE_PATH, formatting_info=False,
                            encoding_override=encoding_override)
    print(f"\n文件: {FILE_PATH}")
    print(f"Sheet 数量: {wb.nsheets}")
    print(f"Sheet 名称: {wb.sheet_names()}")

    for si in range(wb.nsheets):
        ws = wb.sheet_by_index(si)
        print(f"\n{'─' * 60}")
        print(f"Sheet[{si}]: '{ws.name}'  行数={ws.nrows}  列数={ws.ncols}")
        print(f"{'─' * 60}")

        if ws.nrows == 0:
            print("  (空 sheet)")
            continue

        # 打印前 5 行原始内容
        print("\n  前 5 行原始内容:")
        for rx in range(min(5, ws.nrows)):
            cells = []
            for cx in range(min(ws.ncols, 30)):
                cell = ws.cell(rx, cx)
                cells.append(repr(cell.value))
            suffix = " ..." if ws.ncols > 30 else ""
            print(f"    行{rx}: [{', '.join(cells)}{suffix}]")

        # 统计每列
        data_rows_all = []
        for rx in range(ws.nrows):
            row = [ws.cell(rx, cx).value for cx in range(ws.ncols)]
            data_rows_all.append(row)

        # 跳过前 header_row 行做数据统计（假设第0行是表头）
        data_rows = data_rows_all[1:] if ws.nrows > 1 else []
        ncols = ws.ncols

        stats = _col_stats(data_rows, ncols)
        _print_col_stats(stats, label=f"Sheet '{ws.name}'")

        # 重点列
        headers_row = data_rows_all[0] if data_rows_all else []
        _print_mapped_cols(stats, headers_row, label=f"Sheet '{ws.name}'")


def diagnose_parse_trial_balance_import():
    """使用项目自带 parse_trial_balance_import 诊断。"""
    from app.services.file_parser import parse_trial_balance_import, build_columns

    print("\n" + "=" * 80)
    print("诊断方式 2: parse_trial_balance_import (项目解析器)")
    print("=" * 80)

    result = parse_trial_balance_import(FILE_PATH)
    all_rows = result["all_rows"]
    merged_headers = result["merged_headers"]
    header_rows = result["header_rows"]
    data_start = result["data_start_row"]

    print(f"\nall_rows 总行数: {len(all_rows)}")
    print(f"header_rows: {header_rows}")
    print(f"data_start_row: {data_start}")
    print(f"merged_headers ({len(merged_headers)} 列):")
    for i, h in enumerate(merged_headers):
        print(f"  col_{i}: '{h}'")

    # 数据行
    data_rows = all_rows[data_start:]
    print(f"\n数据行数: {len(data_rows)}")
    if not data_rows:
        print("  ❌ 没有数据行!")
        return

    ncols = max(len(r) for r in data_rows) if data_rows else 0
    print(f"数据列数: {ncols}")

    stats = _col_stats(data_rows, ncols)
    _print_col_stats(stats, merged_headers)

    # 重点列 — 直接用整数索引，不用 build_columns
    _print_mapped_cols(stats, merged_headers, label="(项目解析器)")

    # 检查前 5 行数据的映射列原始值
    print(f"\n  ★ 前 5 行数据的映射列原始值:")
    for ri in range(min(5, len(data_rows))):
        row = data_rows[ri]
        vals = {}
        for fm in FIELD_MAPPINGS:
            idx = int(fm["column_id"].replace("col_", ""))
            vals[fm["column_id"]] = repr(row[idx]) if idx < len(row) else "<越界>"
        print(f"    行{ri}: {vals}")


def diagnose_xlrd_all_sheets():
    """使用 xlrd + gbk encoding 读取所有 sheet。"""
    print("\n" + "=" * 80)
    print("诊断方式 3: xlrd + encoding_override='gbk' 全 sheet 诊断")
    print("=" * 80)

    try:
        diagnose_xlrd(encoding_override="gbk")
    except Exception as e:
        print(f"\n❌ xlrd+gbk 失败: {type(e).__name__}: {e}")

    # 也试试 latin-1
    print("\n" + "-" * 40)
    try:
        diagnose_xlrd(encoding_override="latin-1")
    except Exception as e:
        print(f"\n❌ xlrd+latin-1 失败: {type(e).__name__}: {e}")


def diagnose_raw_binary_amount_check():
    """直接扫描二进制数据，检查是否有数值型单元格数据。"""
    print("\n" + "=" * 80)
    print("诊断方式 4: 原始 BIFF 二进制扫描 (检查 NUMBER 记录)")
    print("=" * 80)

    with open(FILE_PATH, "rb") as f:
        data = f.read()

    # BIFF8 NUMBER record (type 0x0203): 2-byte type + 2-byte length + 6-byte header + 8-byte float
    # BIFF8 record header: 2-byte type + 2-byte length
    # Row record: 0x0008
    # Number record: 0x0203
    # Label record: 0x00FD or 0x0204 (BIFF8)
    # RK record: 0x027E

    record_types = {}
    number_count = 0
    rk_count = 0
    label_count = 0
    pos = 0

    while pos + 4 <= len(data):
        rec_type = int.from_bytes(data[pos:pos+2], 'little')
        rec_len = int.from_bytes(data[pos+2:pos+4], 'little')
        record_types[rec_type] = record_types.get(rec_type, 0) + 1

        if rec_type == 0x0203:  # NUMBER
            number_count += 1
            if number_count <= 10:
                # NUMBER record: row(2) + col(2) + xf(2) + value(8) = 14 bytes
                if rec_len >= 14 and pos + 4 + 14 <= len(data):
                    row_idx = int.from_bytes(data[pos+4:pos+6], 'little')
                    col_idx = int.from_bytes(data[pos+6:pos+8], 'little')
                    import struct
                    val = struct.unpack('<d', data[pos+10:pos+18])[0]
                    print(f"  NUMBER #{number_count}: row={row_idx} col={col_idx} value={val}")

        elif rec_type == 0x027E:  # RK
            rk_count += 1

        elif rec_type in (0x00FD, 0x0204):  # LABEL/LABELSST
            label_count += 1

        pos += 4 + rec_len

    print(f"\n  总记录数: {sum(record_types.values())}")
    print(f"  NUMBER 记录 (0x0203): {number_count}")
    print(f"  RK 记录 (0x027E): {rk_count}")
    print(f"  LABEL 记录: {label_count}")

    # 打印出现最多的记录类型
    sorted_types = sorted(record_types.items(), key=lambda x: -x[1])[:15]
    print(f"\n  前 15 种记录类型:")
    for rt, cnt in sorted_types:
        name = {
            0x0009: "BOF", 0x000A: "EOF", 0x0008: "ROW",
            0x00FC: "SST", 0x00FD: "LABEL", 0x0204: "LABELSST",
            0x0203: "NUMBER", 0x027E: "RK", 0x00BD: "MULRK",
            0x00BE: "MULBLANK", 0x00E5: "MERGEDCELLS",
            0x005C: "WRITEACCESS", 0x0042: "CODEPAGE",
            0x003D: "WINDOW1", 0x023E: "WINDOW2",
        }.get(rt, "?")
        print(f"    0x{rt:04X} ({name}): {cnt}")

    if number_count == 0 and rk_count == 0:
        print("\n  ⚠️ 文件中没有 NUMBER/RK 数值记录！")
        print("  → 金额数据可能不存在于 BIFF 记录中。")
    else:
        print(f"\n  ✅ 发现 {number_count + rk_count} 条数值记录。")


def _scan_biff_number_records(data: bytes) -> dict:
    """扫描 BIFF8 NUMBER 记录，返回 {(row_idx, col_idx): float_value}。

    NUMBER record (0x0203): type(2) + length(2) + row(2) + col(2) + xf(2) + value(8)
    """
    import struct
    numbers: dict[tuple[int, int], float] = {}
    pos = 0
    while pos + 4 <= len(data):
        rec_type = int.from_bytes(data[pos:pos+2], 'little')
        rec_len = int.from_bytes(data[pos+2:pos+4], 'little')
        if rec_type == 0x0203 and rec_len >= 14 and pos + 4 + 14 <= len(data):
            row_idx = int.from_bytes(data[pos+4:pos+6], 'little')
            col_idx = int.from_bytes(data[pos+6:pos+8], 'little')
            val = struct.unpack('<d', data[pos+10:pos+18])[0]
            numbers[(row_idx, col_idx)] = val
        # 推进到下一条记录；对未知记录类型也按长度推进
        if rec_len < 0 or pos + 4 + rec_len > len(data):
            break
        pos += 4 + rec_len
    return numbers


def diagnose_merged_parse():
    """验证修复方案：文本层（自定义二进制）+ BIFF8 NUMBER 记录合并。

    模拟修复后的 _parse_xls_custom_binary：
    1. 先用现有自定义二进制解析器拿到表头和数据行（文本层）
    2. 再扫描 BIFF8 NUMBER 记录，按 (row, col) 把数值填入对应单元格
    3. 统计每列非空/非零，确认金额列被填满
    """
    from app.services.file_parser import _parse_xls_custom_binary, build_columns, _clean_header

    print("\n" + "=" * 80)
    print("诊断方式 5: 合并解析验证（文本层 + BIFF8 NUMBER 记录）")
    print("=" * 80)

    # 1. 文本层
    headers, all_rows = _parse_xls_custom_binary(FILE_PATH)
    print(f"\n文本层: headers={len(headers)} 列, all_rows={len(all_rows)} 行")

    # 2. BIFF NUMBER 记录
    with open(FILE_PATH, "rb") as f:
        data = f.read()
    numbers = _scan_biff_number_records(data)
    print(f"BIFF NUMBER 记录: {len(numbers)} 条")

    # 3. BIFF row/col 索引与 all_rows 的对应关系
    # all_rows[0] 是表头，all_rows[1:] 是数据行
    # BIFF 的 row=0 通常是表头行，row=1 开始是数据
    # 需要确认偏移：BIFF row 0 对应 all_rows[0]
    print(f"\nBIFF 行号范围: {min(r for r, c in numbers)}~{max(r for r, c in numbers)}")
    print(f"BIFF 列号范围: {min(c for r, c in numbers)}~{max(c for r, c in numbers)}")

    # 4. 把 NUMBER 值填入 all_rows（按 BIFF row 直接对应 all_rows 索引）
    filled_count = 0
    for (row_idx, col_idx), val in numbers.items():
        if row_idx < len(all_rows):
            row = all_rows[row_idx]
            # 扩展行长度到足够容纳 col_idx
            while len(row) <= col_idx:
                row.append("")
            # 只在原值为空时填入（不覆盖文本层的文本值）
            if str(row[col_idx]).strip() == "":
                row[col_idx] = val
                filled_count += 1
            elif _is_numeric(row[col_idx]):
                # 原值已是数值，用 BIFF 值覆盖（更精确）
                row[col_idx] = val
                filled_count += 1
    print(f"\n填入 NUMBER 值: {filled_count} 个单元格")

    # 5. 统计数据行（all_rows[1:]）
    data_rows = all_rows[1:]
    ncols = max(len(r) for r in data_rows) if data_rows else 0
    print(f"数据行数: {len(data_rows)}, 列数: {ncols}")

    stats = _col_stats(data_rows, ncols)
    _print_col_stats(stats, headers, label="(合并解析后)")

    # 重点列
    _print_mapped_cols(stats, headers, label="(合并解析后)")

    # 前 5 行金额列
    print(f"\n  ★ 前 5 行数据的映射列原始值（合并后）:")
    for ri in range(min(5, len(data_rows))):
        row = data_rows[ri]
        vals = {}
        for fm in FIELD_MAPPINGS:
            idx = int(fm["column_id"].replace("col_", ""))
            vals[fm["column_id"]] = repr(row[idx]) if idx < len(row) else "<越界>"
        print(f"    行{ri}: {vals}")

    # 6. 最终判定
    amount_cols = [15, 16, 17, 18]
    all_filled = all(stats[c][1] > 0 for c in amount_cols if c < len(stats))
    print(f"\n  ★ 最终判定:")
    if all_filled:
        print(f"    ✅ 金额列 (col_15~col_18) 全部有非零值 → 合并解析方案可行")
        print(f"    → 应修改 _parse_xls_custom_binary 补充 BIFF NUMBER 读取")
    else:
        empty_cols = [c for c in amount_cols if c >= len(stats) or stats[c][1] == 0]
        print(f"    ❌ 金额列 {empty_cols} 仍为空 → 合并解析方案不足")
        print(f"    → 可能需要其他解析路径")


def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  TASK-084: 205201-2023.xls 诊断                            ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    if not os.path.exists(FILE_PATH):
        print(f"\n❌ 文件不存在: {FILE_PATH}")
        sys.exit(1)

    # 文件基本信息
    size = os.path.getsize(FILE_PATH)
    print(f"\n文件大小: {size:,} bytes ({size/1024/1024:.1f} MB)")

    with open(FILE_PATH, "rb") as f:
        header_bytes = f.read(8)
    print(f"文件头字节: {header_bytes.hex(' ')}")

    is_ole2 = header_bytes[:4] == b'\xd0\xcf\x11\xe0'
    is_biff = header_bytes[:2] in (b'\x09\x08', b'\x09\x00', b'\x09\x04')
    print(f"OLE2 格式: {is_ole2}")
    print(f"BIFF 格式: {is_biff}")

    # 方式 1: 项目解析器（最重要）
    try:
        diagnose_parse_trial_balance_import()
    except Exception as e:
        print(f"\n❌ parse_trial_balance_import 失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    # 方式 2: xlrd + gbk
    try:
        diagnose_xlrd_all_sheets()
    except Exception as e:
        print(f"\n❌ xlrd 全 sheet 诊断失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    # 方式 3: 原始二进制扫描
    try:
        diagnose_raw_binary_amount_check()
    except Exception as e:
        print(f"\n❌ 原始二进制扫描失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    # 方式 4: 合并解析验证（修复方案验证）
    try:
        diagnose_merged_parse()
    except Exception as e:
        print(f"\n❌ 合并解析验证失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    # 最终汇总
    print("\n" + "=" * 80)
    print("诊断完成。")
    print("=" * 80)


if __name__ == "__main__":
    main()
