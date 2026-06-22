"""字段映射经验库测试 — TASK-031 后端基础"""

import uuid
import pytest
from sqlalchemy import select

from app.models.field_mapping_experience import FieldMappingExperience
from app.services.mapping_experience_service import (
    normalize_header,
    build_context_signature,
    build_lookup_key,
    is_ambiguous_header,
)


class TestNormalizeHeader:
    """normalize_header 规范化"""

    def test_normalize_basic(self):
        assert normalize_header(" 本币期间异动(借) ") == "本币期间异动借"

    def test_normalize_fullwidth_chars(self):
        assert normalize_header("（本币）期间【异动】") == "本币期间异动"

    def test_normalize_case(self):
        assert normalize_header("AccountCode") == "accountcode"
        assert normalize_header("ACCOUNT_CODE") == "accountcode"  # underscores removed

    def test_normalize_punctuation(self):
        assert normalize_header("凭证号：") == "凭证号"
        assert normalize_header("科目编码,科目名称") == "科目编码科目名称"
        assert normalize_header("摘要___说明") == "摘要说明"

    def test_normalize_newlines_and_spaces(self):
        assert normalize_header("凭证\n号") == "凭证号"
        assert normalize_header("  凭证  号  ") == "凭证号"

    def test_normalize_none(self):
        assert normalize_header(None) == ""

    def test_normalize_unicode_nfkc(self):
        # 全角数字转半角
        assert normalize_header("１２３") == "123"


class TestContextSignature:
    """build_context_signature 上下文签名"""

    def test_stable_for_same_input(self):
        headers = ["凭证号", "凭证日期", "摘要", "科目编码"]
        sig1 = build_context_signature(headers, 1)
        sig2 = build_context_signature(headers, 1)
        assert sig1 == sig2
        assert len(sig1) == 64  # sha256 hex

    def test_sensitive_to_neighbor_change(self):
        headers = ["凭证号", "凭证日期", "摘要", "科目编码"]
        sig1 = build_context_signature(headers, 1)
        headers2 = ["凭证号", "日期", "摘要", "科目编码"]  # 当前列变了
        sig2 = build_context_signature(headers2, 1)
        assert sig1 != sig2

    def test_first_and_last_column(self):
        headers = ["凭证号", "凭证日期", "摘要"]
        sig_first = build_context_signature(headers, 0)
        sig_last = build_context_signature(headers, 2)
        assert sig_first != sig_last
        assert len(sig_first) == 64
        assert len(sig_last) == 64


class TestLookupKey:
    """build_lookup_key 查找键"""

    def test_different_company_yields_different_key(self):
        k1 = build_lookup_key(uuid.uuid4(), "journal", "", "", "凭证号", "abc123")
        k2 = build_lookup_key(uuid.uuid4(), "journal", "", "", "凭证号", "abc123")
        assert k1 != k2

    def test_different_context_yields_different_key(self):
        cid = uuid.uuid4()
        k1 = build_lookup_key(cid, "journal", "", "", "凭证号", "ctx_a")
        k2 = build_lookup_key(cid, "journal", "", "", "凭证号", "ctx_b")
        assert k1 != k2

    def test_global_uses_placeholder(self):
        k = build_lookup_key(None, "journal", "", "", "凭证号", "ctx")
        assert len(k) == 40

    def test_same_input_yields_same_key(self):
        cid = uuid.uuid4()
        k1 = build_lookup_key(cid, "journal", "sw", "lf", "凭证号", "ctx")
        k2 = build_lookup_key(cid, "journal", "sw", "lf", "凭证号", "ctx")
        assert k1 == k2


class TestAmbiguousHeader:
    """is_ambiguous_header 歧义判断"""

    def test_borrow_lend_ambiguous(self):
        assert is_ambiguous_header("借") is True
        assert is_ambiguous_header("借方") is True
        assert is_ambiguous_header("贷") is True
        assert is_ambiguous_header("贷方") is True

    def test_balance_ambiguous(self):
        assert is_ambiguous_header("余额") is True
        assert is_ambiguous_header("期初") is True
        assert is_ambiguous_header("期末") is True
        assert is_ambiguous_header("本期") is True
        assert is_ambiguous_header("发生额") is True

    def test_normal_headers_not_ambiguous(self):
        assert is_ambiguous_header("凭证号") is False
        assert is_ambiguous_header("科目编码") is False
        assert is_ambiguous_header("account_name") is False
        assert is_ambiguous_header("") is False


class TestFieldMappingExperienceModel:
    """ORM 模型和数据库集成"""

    @pytest.mark.asyncio
    async def test_create_all_creates_table(self, db):
        """Base.metadata.create_all 能创建新表"""
        from sqlalchemy import inspect

        def _check(conn):
            insp = inspect(conn)
            return "field_mapping_experiences" in insp.get_table_names()

        conn = await db.connection()
        ok = await conn.run_sync(_check)
        assert ok, "field_mapping_experiences table should exist"

    @pytest.mark.asyncio
    async def test_lookup_key_not_unique(self, db):
        """同一 lookup_key 可以存在多条记录（active+inactive）"""
        from app.models.field_mapping_experience import FieldMappingExperience

        exp1 = FieldMappingExperience(
            company_id=None,
            data_type="journal",
            source_header_original="凭证号",
            source_header_normalized="凭证号",
            source_column_index=0,
            target_field="voucher_no",
            lookup_key="test_key_001",
            is_active=True,
        )
        exp2 = FieldMappingExperience(
            company_id=None,
            data_type="journal",
            source_header_original="凭证号",
            source_header_normalized="凭证号",
            source_column_index=0,
            target_field="voucher_date",  # 不同目标
            lookup_key="test_key_001",     # 相同 key
            is_active=False,
        )
        db.add(exp1)
        db.add(exp2)
        await db.flush()

        stmt = select(FieldMappingExperience).where(
            FieldMappingExperience.lookup_key == "test_key_001"
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        assert len(rows) == 2
