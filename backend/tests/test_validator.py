"""测试数据校验器 — 必填检查、负数金额、借贷平衡"""

import uuid
import pytest
from decimal import Decimal
from app.services.validator import (
    _to_decimal,
    _to_int,
    _to_date,
    _validate_row,
    validate_rows,
    _validate_balance,
    _validate_trial_balance,
    _validate_journal_balance,
)
from app.services.column_matcher import REQUIRED_FIELDS


class TestToDecimal:
    """安全 Decimal 转换"""

    def test_normal_number(self):
        assert _to_decimal("100.50") == Decimal("100.50")

    def test_with_comma(self):
        assert _to_decimal("1,000.00") == Decimal("1000.00")

    def test_chinese_comma(self):
        assert _to_decimal("1，000.00") == Decimal("1000.00")

    def test_empty_string(self):
        assert _to_decimal("") is None

    def test_none(self):
        assert _to_decimal(None) is None

    def test_invalid(self):
        assert _to_decimal("abc") is None


class TestToInt:
    """安全 int 转换"""

    def test_normal_int(self):
        assert _to_int("2024") == 2024

    def test_float_string(self):
        assert _to_int("2024.0") == 2024

    def test_with_comma(self):
        assert _to_int("2,024") == 2024

    def test_none(self):
        assert _to_int(None) is None

    def test_empty(self):
        assert _to_int("") is None


class TestToDate:
    """安全 date 转换"""

    def test_iso_format(self):
        from datetime import date
        assert _to_date("2024-01-15") == date(2024, 1, 15)

    def test_slash_format(self):
        from datetime import date
        assert _to_date("2024/01/15") == date(2024, 1, 15)

    def test_none(self):
        assert _to_date(None) is None


class TestValidateRow:
    """单行校验"""

    def test_required_field_missing(self):
        """必填字段缺失 → 错误"""
        row = {"account_code": "1001"}  # 缺少很多必填字段
        required = ["fiscal_year", "period", "account_code", "account_name"]
        errors = _validate_row(row, "trial_balance", required, set())
        assert len(errors) > 0
        assert any("fiscal_year" in e for e in errors)
        assert any("account_name" in e for e in errors)

    def test_required_field_empty_string(self):
        """必填字段为空字符串 → 错误"""
        row = {"fiscal_year": "2024", "period": "1", "account_code": "", "account_name": "现金"}
        required = ["fiscal_year", "period", "account_code", "account_name"]
        errors = _validate_row(row, "trial_balance", required, set())
        assert any("account_code" in e for e in errors)

    def test_negative_amount_error(self):
        """金额为负数 → 错误"""
        row = {
            "fiscal_year": "2024", "period": "1",
            "account_code": "1001", "account_name": "现金",
            "opening_debit": "-100.00",
            "opening_credit": "0",
            "current_debit": "0", "current_credit": "0",
            "ending_debit": "0", "ending_credit": "0",
        }
        required = REQUIRED_FIELDS["trial_balance"]
        errors = _validate_row(row, "trial_balance", required, set())
        assert any("不能为负数" in e for e in errors)

    def test_valid_row_no_errors(self):
        """完整有效行无错误"""
        row = {
            "fiscal_year": "2024", "period": "1",
            "account_code": "1001", "account_name": "现金",
            "opening_debit": "100.00", "opening_credit": "0",
            "current_debit": "50.00", "current_credit": "0",
            "ending_debit": "150.00", "ending_credit": "0",
        }
        required = REQUIRED_FIELDS["trial_balance"]
        errors = _validate_row(row, "trial_balance", required, set())
        assert errors == []

    def test_invalid_fiscal_year_range(self):
        """会计年度超出合理范围"""
        row = {
            "fiscal_year": "1800", "period": "1",
            "account_code": "1001", "account_name": "现金",
        }
        required = REQUIRED_FIELDS["trial_balance"]
        errors = _validate_row(row, "trial_balance", required, set())
        assert any("1800" in e for e in errors)

    def test_invalid_period_range(self):
        """会计期间超出 1-12"""
        row = {
            "fiscal_year": "2024", "period": "13",
            "account_code": "1001", "account_name": "现金",
        }
        required = REQUIRED_FIELDS["trial_balance"]
        errors = _validate_row(row, "trial_balance", required, set())
        assert any("13" in e for e in errors)

    def test_invalid_voucher_date(self):
        """无效凭证日期"""
        row = {
            "fiscal_year": "2024", "period": "1",
            "voucher_no": "001", "voucher_date": "not-a-date",
            "summary": "测试", "account_code": "1001", "account_name": "现金",
        }
        required = REQUIRED_FIELDS["journal"]
        errors = _validate_row(row, "journal", required, set())
        assert any("日期" in e for e in errors)

    def test_non_numeric_amount(self):
        """非数字金额"""
        row = {
            "fiscal_year": "2024", "period": "1",
            "account_code": "1001", "account_name": "现金",
            "opening_debit": "abc",
        }
        required = REQUIRED_FIELDS["trial_balance"]
        errors = _validate_row(row, "trial_balance", required, set())
        assert any("不是有效数字" in e for e in errors)


class TestValidateBalance:
    """借贷平衡校验"""

    def test_trial_balance_balanced(self):
        """科目余额表借贷平衡"""
        valid_rows = [
            {"row_number": 1, "data": {
                "fiscal_year": 2024, "period": 1,
                "ending_debit": Decimal("100.00"), "ending_credit": Decimal("0.00"),
            }},
            {"row_number": 2, "data": {
                "fiscal_year": 2024, "period": 1,
                "ending_debit": Decimal("0.00"), "ending_credit": Decimal("100.00"),
            }},
        ]
        error_rows = []
        _validate_trial_balance(valid_rows, error_rows)
        assert len(error_rows) == 0

    def test_trial_balance_unbalanced_triggers_error(self):
        """科目余额表借贷不平衡 → 错误"""
        valid_rows = [
            {"row_number": 1, "data": {
                "fiscal_year": 2024, "period": 1,
                "ending_debit": Decimal("100.00"), "ending_credit": Decimal("0.00"),
            }},
            {"row_number": 2, "data": {
                "fiscal_year": 2024, "period": 1,
                "ending_debit": Decimal("0.00"), "ending_credit": Decimal("50.00"),
            }},
        ]
        error_rows = []
        _validate_trial_balance(valid_rows, error_rows)
        assert len(error_rows) == 1
        assert "借贷不平衡" in str(error_rows[0]["errors"])

    def test_journal_balanced(self):
        """序时账凭证借贷平衡"""
        valid_rows = [
            {"row_number": 1, "data": {
                "voucher_no": "001",
                "debit_amount": Decimal("100.00"), "credit_amount": Decimal("0.00"),
            }},
            {"row_number": 2, "data": {
                "voucher_no": "001",
                "debit_amount": Decimal("0.00"), "credit_amount": Decimal("100.00"),
            }},
        ]
        error_rows = []
        _validate_journal_balance(valid_rows, error_rows)
        assert len(error_rows) == 0

    def test_journal_unbalanced_triggers_error(self):
        """序时账凭证借贷不平衡 → 错误"""
        valid_rows = [
            {"row_number": 1, "data": {
                "voucher_no": "001",
                "debit_amount": Decimal("100.00"), "credit_amount": Decimal("0.00"),
            }},
            {"row_number": 2, "data": {
                "voucher_no": "001",
                "debit_amount": Decimal("0.00"), "credit_amount": Decimal("80.00"),
            }},
        ]
        error_rows = []
        _validate_journal_balance(valid_rows, error_rows)
        assert len(error_rows) == 1
        assert "借贷不平衡" in str(error_rows[0]["errors"])

    def test_journal_multiple_vouchers(self):
        """多凭证各自分开校验"""
        valid_rows = [
            {"row_number": 1, "data": {
                "voucher_no": "001",
                "debit_amount": Decimal("100.00"), "credit_amount": Decimal("0.00"),
            }},
            {"row_number": 2, "data": {
                "voucher_no": "001",
                "debit_amount": Decimal("0.00"), "credit_amount": Decimal("100.00"),
            }},
            {"row_number": 3, "data": {
                "voucher_no": "002",
                "debit_amount": Decimal("200.00"), "credit_amount": Decimal("0.00"),
            }},
            {"row_number": 4, "data": {
                "voucher_no": "002",
                "debit_amount": Decimal("0.00"), "credit_amount": Decimal("200.00"),
            }},
        ]
        error_rows = []
        _validate_journal_balance(valid_rows, error_rows)
        assert len(error_rows) == 0
