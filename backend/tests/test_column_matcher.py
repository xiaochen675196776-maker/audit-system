"""测试列名智能匹配器 — 科目余额表字段、序时账字段、自动匹配"""

import pytest
from app.services.column_matcher import (
    match_column,
    auto_match,
    apply_mapping,
    map_row,
    similarity,
    KEYWORD_MAP,
    REQUIRED_FIELDS,
    TYPE_FIELDS,
)


class TestSimilarity:
    """字符串相似度"""

    def test_exact_match(self):
        assert similarity("科目编码", "科目编码") == 1.0

    def test_similar_chinese(self):
        s = similarity("期初借方余额", "期初借方")
        assert s > 0.6

    def test_case_insensitive(self):
        s = similarity("Account Code", "account code")
        assert s == 1.0


class TestMatchColumn:
    """单列匹配"""

    def test_match_account_code_chinese(self):
        targets = TYPE_FIELDS["trial_balance"]
        field, score = match_column("科目编码", targets)
        assert field == "account_code"
        assert score >= 0.85

    def test_match_account_name_chinese(self):
        targets = TYPE_FIELDS["trial_balance"]
        field, score = match_column("科目名称", targets)
        assert field == "account_name"

    def test_match_opening_debit(self):
        """期初借方余额 → opening_debit"""
        targets = TYPE_FIELDS["trial_balance"]
        field, score = match_column("期初借方余额", targets)
        assert field == "opening_debit"

    def test_match_current_debit(self):
        """本期借方发生额 → current_debit"""
        targets = TYPE_FIELDS["trial_balance"]
        field, score = match_column("本期借方发生额", targets)
        assert field == "current_debit"

    def test_match_ending_debit(self):
        """期末借方余额 → ending_debit"""
        targets = TYPE_FIELDS["trial_balance"]
        field, score = match_column("期末借方余额", targets)
        assert field == "ending_debit"

    def test_match_debit_amount_journal(self):
        """借方金额（序时账）→ debit_amount"""
        targets = TYPE_FIELDS["journal"]
        field, score = match_column("借方金额", targets)
        assert field == "debit_amount"

    def test_match_credit_amount_journal(self):
        """贷方金额（序时账）→ credit_amount"""
        targets = TYPE_FIELDS["journal"]
        field, score = match_column("贷方金额", targets)
        assert field == "credit_amount"

    def test_match_voucher_no(self):
        targets = TYPE_FIELDS["journal"]
        field, score = match_column("凭证号", targets)
        assert field == "voucher_no"

    def test_match_summary(self):
        targets = TYPE_FIELDS["journal"]
        field, score = match_column("摘要", targets)
        assert field == "summary"

    def test_match_fiscal_year(self):
        targets = TYPE_FIELDS["trial_balance"]
        field, score = match_column("会计年度", targets)
        assert field == "fiscal_year"

    def test_match_period(self):
        targets = TYPE_FIELDS["trial_balance"]
        field, score = match_column("会计期间", targets)
        assert field == "period"

    def test_unmatched_column(self):
        targets = TYPE_FIELDS["trial_balance"]
        field, score = match_column("无关字段XYZ", targets)
        assert field is None

    def test_low_confidence_threshold(self):
        """低于 0.6 置信度不匹配"""
        targets = TYPE_FIELDS["trial_balance"]
        field, score = match_column("abc", targets)
        assert field is None or score < 0.6


class TestAutoMatch:
    """整组表头自动匹配"""

    def test_trial_balance_headers_match(self):
        headers = ["科目编码", "科目名称", "会计年度", "会计期间",
                    "期初借方余额", "期初贷方余额",
                    "本期借方发生额", "本期贷方发生额",
                    "期末借方余额", "期末贷方余额"]
        result = auto_match(headers, "trial_balance")
        assert result["data_type"] == "trial_balance"
        assert "account_code" in result["matched"]
        assert "account_name" in result["matched"]
        assert "opening_debit" in result["matched"]
        assert "current_debit" in result["matched"]
        assert "ending_debit" in result["matched"]
        assert "opening_credit" in result["matched"]
        assert "current_credit" in result["matched"]
        assert "ending_credit" in result["matched"]
        # 必填字段不应缺失
        assert len(result["missing"]) == 0

    def test_journal_headers_match(self):
        headers = ["凭证号", "凭证日期", "摘要", "科目编码", "科目名称",
                    "借方金额", "贷方金额", "会计年度", "会计期间"]
        result = auto_match(headers, "journal")
        assert result["data_type"] == "journal"
        assert "voucher_no" in result["matched"]
        assert "debit_amount" in result["matched"]
        assert "credit_amount" in result["matched"]
        assert len(result["missing"]) == 0

    def test_missing_required_fields_detected(self):
        """缺少必填字段应被检测"""
        headers = ["凭证号", "摘要"]  # 缺少很多必填字段
        result = auto_match(headers, "journal")
        # REQUIRED_FIELDS for journal: fiscal_year, period, voucher_no, voucher_date, summary, account_code, account_name
        missing = result["missing"]
        assert "fiscal_year" in missing or "account_code" in missing

    def test_unknown_data_type_raises(self):
        with pytest.raises(ValueError, match="未知的数据类型"):
            auto_match(["科目编码"], "unknown_type")


class TestApplyMapping:
    """手动映射应用"""

    def test_apply_valid_mapping(self):
        headers = ["科目编码", "科目名称", "期初借方"]
        mapping = {"account_code": "科目编码", "account_name": "科目名称"}
        result = apply_mapping(headers, mapping)
        assert result == mapping

    def test_apply_partial_mapping(self):
        headers = ["科目编码"]
        mapping = {"account_code": "科目编码", "account_name": "不存在的列"}
        result = apply_mapping(headers, mapping)
        assert "account_code" in result
        assert "account_name" not in result


class TestMapRow:
    """行数据映射"""

    def test_map_row_basic(self):
        headers = ["科目编码", "科目名称", "期初借方余额"]
        mapping = {"account_code": "科目编码", "account_name": "科目名称", "opening_debit": "期初借方余额"}
        row = ["1001", "现金", "10000.00"]
        result = map_row(row, headers, mapping)
        assert result == {"account_code": "1001", "account_name": "现金", "opening_debit": "10000.00"}

    def test_map_row_partial(self):
        """部分映射：row 比 headers 短时不应越界"""
        headers = ["科目编码", "科目名称", "期初借方余额"]
        mapping = {"account_code": "科目编码", "account_name": "科目名称", "opening_debit": "期初借方余额"}
        row = ["1001"]  # 只有一列
        result = map_row(row, headers, mapping)
        assert result == {"account_code": "1001"}
