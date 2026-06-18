"""文件解析器 — 支持 Excel (.xlsx/.xls) 和 CSV 文件"""

import csv
import pandas as pd
from pathlib import Path


def parse_file(file_path: str) -> tuple[list[str], list[list]]:
    """
    解析上传文件，自动识别表头行并返回数据。

    Args:
        file_path: 文件路径

    Returns:
        (headers: list[str], rows: list[list]) — 表头列表 + 数据行列表
    """
    ext = Path(file_path).suffix.lower()

    if ext == ".csv":
        return _parse_csv(file_path)
    elif ext in (".xlsx", ".xls"):
        return _parse_excel(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}（仅支持 .xlsx .xls .csv）")


def _parse_csv(file_path: str) -> tuple[list[str], list[list]]:
    """解析 CSV 文件"""
    # 先探测编码
    encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1"]
    content = None
    used_encoding = "utf-8"

    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc, newline="") as f:
                content = f.read()
            used_encoding = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if content is None:
        raise ValueError("无法识别 CSV 文件编码")

    lines = content.strip().splitlines()
    reader = csv.reader(lines)
    all_rows = list(reader)

    if len(all_rows) < 2:
        raise ValueError("CSV 文件至少需要表头行 + 一行数据")

    header_idx = _detect_header_row(all_rows)
    headers = [_clean_header(h) for h in all_rows[header_idx]]
    data_rows = all_rows[header_idx + 1 :]

    # 清理：移除全空行、移除空值填充
    data_rows = [
        [cell.strip() if isinstance(cell, str) else cell for cell in row]
        for row in data_rows
        if any(
            cell is not None and str(cell).strip() != "" for cell in row
        )
    ]

    return headers, data_rows


def _clean_header(header: str | None) -> str:
    """清洗表头：去 BOM、去空格、去引号"""
    if header is None:
        return ""
    s = str(header).strip()
    # 移除 UTF-8 BOM
    if s.startswith("\ufeff"):
        s = s[1:]
    # 移除零宽字符
    s = s.replace("\u200b", "").replace("\ufeff", "")
    # 移除首尾引号
    s = s.strip('"').strip("'").strip()
    return s


def _parse_excel(file_path: str) -> tuple[list[str], list[list]]:
    """解析 Excel 文件"""
    # 先用 openpyxl 读取（保留原始格式），pandas 做 fallback
    try:
        return _parse_excel_openpyxl(file_path)
    except Exception:
        return _parse_excel_pandas(file_path)


def _parse_excel_openpyxl(file_path: str) -> tuple[list[str], list[list]]:
    """用 openpyxl 解析（更精确控制表头识别）"""
    from openpyxl import load_workbook

    wb = load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active

    all_rows = []
    for row in ws.iter_rows(values_only=True):
        all_rows.append(list(row))

    wb.close()

    if len(all_rows) < 2:
        raise ValueError("Excel 文件至少需要表头行 + 一行数据")

    header_idx = _detect_header_row(all_rows)
    headers = [_clean_header(h) for h in all_rows[header_idx]]
    data_rows = all_rows[header_idx + 1 :]

    # 清理：移除全空行
    data_rows = [
        [cell if cell is not None else "" for cell in row]
        for row in data_rows
        if any(cell is not None and str(cell).strip() != "" for cell in row)
    ]

    return headers, data_rows


def _parse_excel_pandas(file_path: str) -> tuple[list[str], list[list]]:
    """用 pandas 解析（fallback）"""
    df = pd.read_excel(file_path, header=None, dtype=str)
    all_rows = df.fillna("").values.tolist()

    if len(all_rows) < 2:
        raise ValueError("Excel 文件至少需要表头行 + 一行数据")

    header_idx = _detect_header_row(all_rows)
    headers = [_clean_header(h) for h in all_rows[header_idx]]
    data_rows = all_rows[header_idx + 1 :]

    data_rows = [
        [str(cell).strip() for cell in row]
        for row in data_rows
        if any(str(cell).strip() != "" for cell in row)
    ]

    return headers, data_rows


def _detect_header_row(rows: list[list], max_scan: int = 5) -> int:
    """
    自动检测表头行：扫描前 N 行，找到第一个所有单元格都非空的行。

    规则：
    1. 扫描前 max_scan 行
    2. 找到非空率最高的行
    3. 如果第一行非空率 ≥ 50%，默认第一行就是表头
    """
    best_idx = 0
    best_count = 0

    scan_end = min(max_scan, len(rows))
    for i in range(scan_end):
        row = rows[i]
        non_empty = sum(1 for cell in row if cell is not None and str(cell).strip() != "")
        if non_empty > best_count:
            best_count = non_empty
            best_idx = i

    # 优先第一行（大多数财务软件第一行就是表头）
    if best_idx == 0 and best_count > 0:
        return 0

    # 如果找到的行非空数明显更多，用那一行
    first_row_non_empty = sum(
        1 for cell in rows[0] if cell is not None and str(cell).strip() != ""
    )
    if best_count > first_row_non_empty * 1.5:
        return best_idx

    return 0


def parse_file_info(file_path: str) -> dict:
    """获取文件基本信息（用于预览前确认）"""
    headers, rows = parse_file(file_path)
    return {
        "file_name": Path(file_path).name,
        "headers": headers,
        "header_count": len(headers),
        "row_count": len(rows),
        "preview_rows": rows[:5],
    }
