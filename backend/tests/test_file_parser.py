"""测试文件解析器 — CSV/Excel 解析、中文表头、UTF-8 BOM、空行跳过"""

import os
import tempfile
import pytest
from pathlib import Path
from app.services.file_parser import (
    parse_file,
    parse_file_info,
    _clean_header,
    _detect_header_row,
)


class TestCleanHeader:
    """表头清洗"""

    def test_strip_whitespace(self):
        assert _clean_header("  科目编码  ") == "科目编码"

    def test_remove_utf8_bom(self):
        assert _clean_header("\ufeff科目编码") == "科目编码"

    def test_remove_quotes(self):
        assert _clean_header('"科目名称"') == "科目名称"
        assert _clean_header("'科目名称'") == "科目名称"

    def test_none_header(self):
        assert _clean_header(None) == ""

    def test_remove_zero_width_chars(self):
        assert _clean_header("\u200b科目\u200b") == "科目"


class TestDetectHeaderRow:
    """表头行检测"""

    def test_first_row_is_header(self):
        rows = [["科目编码", "科目名称", "期初借方"], ["1001", "现金", "10000"]]
        assert _detect_header_row(rows) == 0

    def test_second_row_more_complete(self):
        rows = [
            ["报表", "", ""],
            ["科目编码", "科目名称", "期初借方", "期初贷方"],
            ["1001", "现金", "10000", "0"],
        ]
        assert _detect_header_row(rows) == 1

    def test_all_empty_returns_zero(self):
        rows = [["", ""], ["", ""]]
        assert _detect_header_row(rows) == 0


class TestCSVParsing:
    """CSV 解析测试"""

    def _write_temp_csv(self, content: str, encoding: str = "utf-8") -> str:
        """写入临时 CSV 并返回路径"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding=encoding, newline=""
        )
        tmp.write(content)
        tmp.close()
        return tmp.name

    def test_chinese_headers(self):
        """中文表头 CSV 解析"""
        csv_content = "科目编码,科目名称,期初借方余额,期初贷方余额\r\n1001,现金,10000.00,0.00\r\n1002,银行存款,50000.00,0.00"
        path = self._write_temp_csv(csv_content)
        try:
            headers, rows = parse_file(path)
            assert headers == ["科目编码", "科目名称", "期初借方余额", "期初贷方余额"]
            assert len(rows) == 2
            assert rows[0] == ["1001", "现金", "10000.00", "0.00"]
        finally:
            os.unlink(path)

    def test_utf8_bom(self):
        """UTF-8 BOM CSV 解析"""
        csv_content = "\ufeff科目编码,科目名称\r\n1001,现金"
        path = self._write_temp_csv(csv_content, encoding="utf-8-sig")
        try:
            headers, rows = parse_file(path)
            assert headers[0] == "科目编码"  # BOM 已被清除
            assert headers == ["科目编码", "科目名称"]
            assert len(rows) == 1
        finally:
            os.unlink(path)

    def test_skip_empty_lines(self):
        """跳过空行"""
        csv_content = "科目编码,科目名称\r\n1001,现金\r\n\r\n1002,银行存款\r\n\r\n"
        path = self._write_temp_csv(csv_content)
        try:
            headers, rows = parse_file(path)
            assert len(rows) == 2  # 空行被跳过
            assert rows[0] == ["1001", "现金"]
            assert rows[1] == ["1002", "银行存款"]
        finally:
            os.unlink(path)

    def test_skip_whitespace_only_lines(self):
        """跳过仅含空白的行"""
        csv_content = "科目编码,科目名称\r\n1001,现金\r\n  \r\n1002,银行存款"
        path = self._write_temp_csv(csv_content)
        try:
            headers, rows = parse_file(path)
            assert len(rows) == 2
        finally:
            os.unlink(path)

    def test_gbk_encoding(self):
        """GBK 编码 CSV"""
        csv_content = "科目编码,科目名称\r\n1001,现金\r\n1002,银行存款"
        path = self._write_temp_csv(csv_content, encoding="gbk")
        try:
            headers, rows = parse_file(path)
            assert headers == ["科目编码", "科目名称"]
            assert len(rows) == 2
        finally:
            os.unlink(path)

    def test_too_few_rows_raises(self):
        """少于2行应抛出错误"""
        csv_content = "科目编码"
        path = self._write_temp_csv(csv_content)
        try:
            with pytest.raises(ValueError, match="至少需要表头行"):
                parse_file(path)
        finally:
            os.unlink(path)

    def test_unsupported_extension(self):
        """不支持的文件扩展名"""
        with pytest.raises(ValueError, match="不支持的文件格式"):
            parse_file("test.txt")


class TestParseFileInfo:
    """文件信息预览"""

    def test_parse_file_info_structure(self):
        csv_content = "科目编码,科目名称\r\n1001,现金\r\n1002,银行存款"
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            info = parse_file_info(tmp.name)
            assert "file_name" in info
            assert "headers" in info
            assert "header_count" in info
            assert "row_count" in info
            assert "preview_rows" in info
            assert info["header_count"] == 2
            assert info["row_count"] == 2
            assert len(info["preview_rows"]) <= 5
        finally:
            os.unlink(tmp.name)
