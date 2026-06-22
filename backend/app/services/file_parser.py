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


def parse_file_with_config(
    file_path: str,
    parse_config: dict | None = None,
) -> tuple[list[str], list[list]]:
    """
    按模板 parse_config 解析文件。

    parse_config 支持的字段：
    - header_row: int (0 基) — 表头行，默认 0
    - data_start_row: int (0 基) — 数据起始行，默认 header_row + 1
    - encoding: str | "auto" — CSV 编码，默认 "auto"

    当 parse_config 为 None 或空时，等价于 parse_file()。
    """
    if not parse_config or not isinstance(parse_config, dict):
        return parse_file(file_path)

    # 先用标准解析获取原始数据
    ext = Path(file_path).suffix.lower()

    if ext == ".csv":
        headers, all_rows = _parse_csv_all_rows(file_path, parse_config.get("encoding", "auto"))
    elif ext in (".xlsx", ".xls"):
        headers, all_rows = _parse_excel_all_rows(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")

    # 应用 header_row / data_start_row 裁剪
    header_row = int(parse_config.get("header_row", 0))
    data_start = int(parse_config.get("data_start_row", header_row + 1))

    if header_row > 0 and header_row < len(all_rows):
        headers = [_clean_header(h) for h in all_rows[header_row]]
    elif header_row == 0:
        pass  # headers already from first row
    else:
        raise ValueError(f"header_row={header_row} 超出文件行数 {len(all_rows)}")

    # 截取数据行
    data_rows = all_rows[max(data_start, header_row + 1):]

    # 清理空行
    data_rows = [
        [cell if cell is not None else "" for cell in row]
        for row in data_rows
        if any(cell is not None and str(cell).strip() != "" for cell in row)
    ]

    return headers, data_rows


def _parse_csv_all_rows(file_path: str, encoding: str = "auto") -> tuple[list[str], list[list]]:
    """解析 CSV 返回全部行（不自动检测表头）"""
    encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1"]
    content = None

    if encoding != "auto":
        encodings = [encoding] + [e for e in encodings if e != encoding]

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

    # 默认第一行是表头
    headers = [_clean_header(h) for h in all_rows[0]]
    return headers, all_rows


def _parse_excel_all_rows(file_path: str) -> tuple[list[str], list[list]]:
    """解析 Excel 返回全部行"""
    from openpyxl import load_workbook
    wb = load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    all_rows = []
    for row in ws.iter_rows(values_only=True):
        all_rows.append(list(row))
    wb.close()

    if len(all_rows) < 2:
        raise ValueError("Excel 文件至少需要表头行 + 一行数据")

    headers = [_clean_header(h) for h in all_rows[0]]
    return headers, all_rows


def build_columns(headers: list[str], sample_rows: list[list] | None = None) -> list[dict]:
    """
    构建列描述符列表，每个列有稳定的 column_id。

    解决重复表头问题：column_id 基于列位置（col_001, col_002...），
    不受表头文本重复影响。duplicate_group 标记同名列的分组信息。

    Args:
        headers: 表头列表
        sample_rows: 前几行数据（用于生成 sample_values）

    Returns:
        [{"column_id": "col_001", "index": 0, "header": "...", ...}, ...]
    """
    # 第一遍：统计每个表头出现次数
    header_counts: dict[str, int] = {}
    for h in headers:
        key = (h or "").strip()
        header_counts[key] = header_counts.get(key, 0) + 1

    # 第二遍：构建列描述符
    occurrence_tracker: dict[str, int] = {}
    columns = []

    for i, header in enumerate(headers):
        normalized = header.strip() if header else ""
        col_id = f"col_{i + 1:03d}"

        col = {
            "column_id": col_id,
            "index": i,
            "header": header,
            "normalized_header": normalized,
            "sample_values": _extract_sample_values(sample_rows, i) if sample_rows else [],
        }

        # duplicate_group
        key = normalized
        total = header_counts.get(key, 1)
        if total > 1:
            occurrence_tracker[key] = occurrence_tracker.get(key, 0) + 1
            col["duplicate_group"] = {
                "header": normalized,
                "occurrence": occurrence_tracker[key],
                "total": total,
            }
        else:
            col["duplicate_group"] = None

        columns.append(col)

    return columns


def _extract_sample_values(sample_rows: list[list], col_index: int, max_samples: int = 3) -> list[str]:
    """从样例行中提取指定列的前几个值"""
    values = []
    for j in range(min(max_samples, len(sample_rows))):
        row = sample_rows[j]
        if col_index < len(row) and row[col_index] is not None:
            values.append(str(row[col_index]).strip())
        else:
            values.append("")
    return values
