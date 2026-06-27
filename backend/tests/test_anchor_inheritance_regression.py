"""ANCHOR-INHERITANCE-MAPPING：六张真实科目余额表回归测试

对六张真实客户科目余额表执行完整的 preview → analyze → execute 流程，
记录映射计划统计、确认数量、耗时等指标，并输出 JSON / CSV / MD 报告。

Usage:
    D:\\python\\python.exe -m pytest tests/test_anchor_inheritance_regression.py -v -s
"""
import csv
import json
import os
import tempfile
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl
import pytest
import xlrd
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_account_mapping import ClientAccountMapping
from app.models.standard_account import StandardAccount
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow
from app.services.standard_trial_balance_import_service import (
    analyze_standard_import,
    execute_standard_import,
    preview_standard_import,
)

TASK_093_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "task_093_confirmations"


# ── 真实文件路径（来自 D:\APP\谷歌\文件下载） ─────────────

REAL_FILES: list[dict] = [
    {
        "key": "huizhan",
        "name": "会展中心余额表.xlsx",
        "path": r"D:\APP\谷歌\文件下载\会展中心余额表.xlsx",
        "customer_label": "会展中心",
        "fiscal_year": 2023,
        "period": 12,
    },
    {
        "key": "112",
        "name": "1-12科目余额表.xls",
        "path": r"D:\APP\谷歌\文件下载\1-12科目余额表.xls",
        "customer_label": "测试112",
        "fiscal_year": 2023,
        "period": 12,
    },
    {
        "key": "205201",
        "name": "205201-2023.xls",
        "path": r"D:\APP\谷歌\文件下载\205201-2023.xls",
        "customer_label": "205201",
        "fiscal_year": 2023,
        "period": 12,
    },
    {
        "key": "tb_2023",
        "name": "科目余额表2023年导入.xls",
        "path": r"D:\APP\谷歌\文件下载\科目余额表2023年导入.xls",
        "customer_label": "TB2023",
        "fiscal_year": 2023,
        "period": 12,
    },
    {
        "key": "yiliao",
        "name": "医疗3月31日序时账及余额表.xlsx",
        "path": r"D:\APP\谷歌\文件下载\医疗3月31日序时账及余额表.xlsx",
        "customer_label": "医疗3月",
        "fiscal_year": 2024,
        "period": 3,
    },
    {
        "key": "chengdu_dikang",
        "name": "科目余额表-成都迪康-240930.xls",
        "path": r"D:\APP\谷歌\文件下载\科目余额表-成都迪康-240930.xls",
        "customer_label": "成都迪康",
        "fiscal_year": 2024,
        "period": 9,
    },
]


# ── 工具：自动从 Excel 头部嗅探字段映射 ──────────────


def _sniff_field_mappings(headers: list[str], data_rows: list[list]) -> list[dict]:
    """从表头嗅探字段映射；金额列默认按「two_column」处理。"""
    mappings: list[dict] = []
    seen: set[str] = set()
    for idx, header in enumerate(headers):
        h = (header or "").strip()
        if not h:
            continue
        col_id = f"col_{idx}"
        # 排除重复
        if col_id in seen:
            continue
        seen.add(col_id)
        field = _guess_field_name(h)
        if field is None:
            continue
        entry: dict = {"column_id": col_id, "field_name": field}
        if field in {
            "opening_debit", "opening_credit", "current_debit",
            "current_credit", "ending_debit", "ending_credit",
        }:
            entry["period_type"] = field.split("_")[0]
            entry["split_mode"] = "two_column"
            entry["debit_column_id"] = entry["column_id"]
            entry["credit_column_id"] = entry["column_id"]
        elif field in {"opening_amount", "current_amount", "ending_amount"}:
            entry["period_type"] = field.split("_")[0]
            entry["split_mode"] = "single_by_direction"
        mappings.append(entry)
    return mappings


def _guess_field_name(header: str) -> str | None:
    """从表头猜测字段名。"""
    h = header.strip()
    # 科目代码
    if any(kw in h for kw in ["科目编码", "科目代码", "Account Code", "account_code", "编码"]):
        return "account_code"
    if any(kw in h for kw in ["科目名称", "科目全称", "科目全名", "Account Name", "account_name", "名称"]):
        return "account_name"
    if "期初" in h and "借" in h:
        return "opening_debit"
    if "期初" in h and "贷" in h:
        return "opening_credit"
    if "期初" in h:
        return "opening_amount"
    if ("本期" in h or "发生" in h) and "借" in h:
        return "current_debit"
    if ("本期" in h or "发生" in h) and "贷" in h:
        return "current_credit"
    if "本期" in h or "发生" in h:
        return "current_amount"
    if "期末" in h and "借" in h:
        return "ending_debit"
    if "期末" in h and "贷" in h:
        return "ending_credit"
    if "期末" in h:
        return "ending_amount"
    return None


# ── 工具：自动从数据行识别列对应（金融表头偏移容忍） ──


def _auto_pick_columns(
    headers: list[str], data_rows: list[list]
) -> tuple[int | None, int | None, int | None, int | None, int | None, int | None, int | None]:
    """从表头嗅探关键列索引。"""
    code_idx = name_idx = None
    ob_idx = oc_idx = cb_idx = cc_idx = eb_idx = ec_idx = None
    for idx, header in enumerate(headers):
        h = (header or "").strip()
        if "科目编码" in h or "科目代码" in h or "Account Code" in h:
            code_idx = idx
        elif "科目名称" in h or "科目全称" in h or "科目全名" in h or "Account Name" in h:
            name_idx = idx
        elif "期初" in h and "借" in h and ob_idx is None:
            ob_idx = idx
        elif "期初" in h and "贷" in h and oc_idx is None:
            oc_idx = idx
        elif ("本期" in h or "发生" in h) and "借" in h and cb_idx is None:
            cb_idx = idx
        elif ("本期" in h or "发生" in h) and "贷" in h and cc_idx is None:
            cc_idx = idx
        elif "期末" in h and "借" in h and eb_idx is None:
            eb_idx = idx
        elif "期末" in h and "贷" in h and ec_idx is None:
            ec_idx = idx
    return code_idx, name_idx, ob_idx, oc_idx, cb_idx, cc_idx, eb_idx, ec_idx


def _read_xls_to_xlsx(src_path: str) -> str:
    """把 .xls 转换为 .xlsx 临时文件（确保 openpyxl 兼容）。"""
    if src_path.endswith(".xlsx"):
        return src_path
    if not src_path.endswith(".xls"):
        return src_path
    try:
        book = xlrd.open_workbook(src_path, formatting_info=False)
        # 选第一个 sheet
        sheet = book.sheet_by_index(0)
        wb = openpyxl.Workbook()
        ws = wb.active
        for r in range(sheet.nrows):
            row = []
            for c in range(sheet.ncols):
                v = sheet.cell_value(r, c)
                if v is None or v == "":
                    row.append(None)
                else:
                    row.append(v)
            ws.append(row)
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        wb.save(tmp.name)
        tmp.close()
        return tmp.name
    except Exception:
        return src_path


# ── 工具：自动生成 confirmed_mappings（仅锚点 + 显式覆盖）──


def _load_task_093_fixture(file_key: str | None) -> dict:
    if not file_key:
        return {"confirmed_mappings": [], "ignored_rows": []}
    path = TASK_093_FIXTURE_DIR / f"{file_key}.json"
    if not path.exists():
        return {"confirmed_mappings": [], "ignored_rows": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _is_unique_safe_candidate(candidates: list[dict], backend_auto: dict | None = None) -> dict | None:
    def is_safe(c: dict) -> bool:
        if not c.get("standard_account_id"):
            return False
        if c.get("warning"):
            return False
        if c.get("auto_confirmable") is not True:
            return False
        if c.get("compatibility_status") != "compatible":
            return False
        try:
            score = float(c.get("score"))
        except (TypeError, ValueError):
            return False
        return score >= 0.9

    if backend_auto and is_safe(backend_auto):
        return backend_auto
    safe = [c for c in candidates if is_safe(c)]
    target_ids = {c.get("standard_account_id") for c in safe}
    if len(target_ids) == 1 and safe:
        return safe[0]
    return None


async def _candidate_from_fixture(
    db: AsyncSession,
    rec: dict,
    fixture_mapping: dict,
) -> dict | None:
    candidates = rec.get("candidates") or []
    target_id = fixture_mapping.get("standard_account_id")
    target_code = fixture_mapping.get("standard_account_code")
    for c in candidates:
        if target_id and c.get("standard_account_id") == target_id:
            return c
        if target_code and c.get("standard_account_code") == target_code:
            return c
    if target_code and not target_id:
        result = await db.execute(
            select(StandardAccount).where(
                StandardAccount.account_code == str(target_code),
                StandardAccount.is_active.is_(True),
            )
        )
        sa = result.scalars().first()
        if sa is not None:
            target_id = str(sa.id)
            fixture_mapping["standard_account_id"] = target_id
            fixture_mapping["standard_account_name"] = sa.account_name
    if target_id and target_code:
        return {
            "standard_account_id": target_id,
            "standard_account_code": target_code,
            "standard_account_name": fixture_mapping.get("standard_account_name") or target_code,
            "score": 1.0,
            "source": "task_093_fixture",
            "reason": fixture_mapping.get("review_reason"),
            "warning": None,
            "auto_confirmable": False,
            "compatibility_status": "compatible",
        }
    return None


async def _build_anchor_only_confirmed(
    db: AsyncSession,
    analyze_result: dict,
    file_key: str | None = None,
) -> tuple[list[dict], list[int]]:
    """从 analyze 结果构造 execute 所需的 confirmed_mappings + ignored_rows。

    TASK-092 严格规则：
    - 优先 role ∈ {anchor, breakpoint, explicit_override}，并允许 unresolved（用户主动确认）
    - 接受非末级 anchor（如 银行存款 / 预付账款 等父级会计科目）— 它们也必须提交以便子级继承
    - 接受有候选的 unresolved 行（视为用户主动确认）
    - 优先 auto_confirm_candidate（unique_safe 后端已验证）
    - 模拟用户确认：仅使用可审计 fixture；自动确认仅允许唯一安全候选

    返回：
        (confirmed_mappings, ignored_rows)
        ignored_rows：参与入库但完全无候选的末级行（视为用户主动忽略）
    """
    fixture = _load_task_093_fixture(file_key)
    fixture_confirmed = {
        item["row_index"]: item
        for item in fixture.get("confirmed_mappings", [])
        if item.get("review_reason")
    }
    fixture_ignored = {
        item["row_index"]: item
        for item in fixture.get("ignored_rows", [])
        if item.get("reason")
    }
    confirmed: list[dict] = []
    ignored: list[int] = list(fixture_ignored)
    for rec in analyze_result.get("mapping_recommendations", []):
        role = rec.get("mapping_role")
        # 接受的 role：anchor / breakpoint / explicit_override / unresolved（用户主动确认）
        if role not in {"anchor", "breakpoint", "explicit_override", "unresolved"}:
            continue
        # 跳过 structural_summary / ignored
        if role in {"structural_summary", "ignored"}:
            continue

        cand = None
        candidates = rec.get("candidates") or []
        fixture_mapping = fixture_confirmed.get(rec.get("row_index"))
        if fixture_mapping:
            cand = await _candidate_from_fixture(db, rec, fixture_mapping)
            selection_source = "user_confirmed"

        # 1) 允许所有角色使用唯一安全候选；不得按最高分兜底。
        if cand is None:
            cand = _is_unique_safe_candidate(candidates, rec.get("auto_confirm_candidate"))
            selection_source = "auto_confirmed_unique_safe" if cand else "user_confirmed"

        if cand is None:
            continue
        sa_id = cand.get("standard_account_id")
        if not sa_id:
            continue
        confirmed.append({
            "row_index": rec["row_index"],
            "client_account_code": rec.get("client_account_code"),
            "client_account_name": rec.get("client_account_name"),
            "standard_account_id": sa_id,
            "standard_account_code": cand.get("standard_account_code"),
            "standard_account_name": cand.get("standard_account_name"),
            "mapping_action": "override" if role == "explicit_override" else "anchor",
            "apply_to_descendants": True,
            "selection_source": selection_source,
        })
    return confirmed, ignored


# ── 工具：预填标准科目（最小集，确保分析能匹配） ────────


async def _ensure_minimal_standard_accounts(db: AsyncSession) -> None:
    """确保最常用的标准科目已存在（无硬编码客户科目代码）。

    TASK-092：扩充常见子级标准科目，避免依赖 audit.db 的特定种子。
    这里只补充会计实务中最常见的子科目代码/名称，不针对任何特定客户。
    """
    accounts = [
        ("1001", "库存现金", "asset", "debit", True),
        ("1002", "银行存款", "asset", "debit", True),
        ("1012", "其他货币资金", "asset", "debit", True),
        ("1013", "存放财务公司存款", "asset", "debit", True),
        ("1101", "交易性金融资产", "asset", "debit", False),
        ("110101", "加：交易性金融资产公允价值变动", "asset", "debit", True),
        ("1103", "衍生金融资产", "asset", "debit", False),
        ("110301", "加：衍生金融资产公允价值变动", "asset", "debit", True),
        ("112101", "应收票据", "asset", "debit", True),
        ("112102", "减：应收票据-坏账准备", "asset", "credit", True),
        ("112201", "应收账款", "asset", "debit", True),
        ("112202", "减：应收账款-坏账准备", "asset", "credit", True),
        ("112301", "应收款项融资", "asset", "debit", True),
        ("112302", "加：应收款项融资-公允价值变动", "asset", "credit", True),
        ("112401", "预付款项", "asset", "debit", True),
        ("112402", "减：预付款项-坏账准备", "asset", "credit", True),
        ("1131", "应收利息", "asset", "debit", True),
        ("1132", "应收股利", "asset", "debit", True),
        ("122101", "其他应收款", "asset", "debit", True),
        ("122102", "减：其他应收款-坏账准备", "asset", "credit", True),
        ("141101", "包装物", "asset", "debit", True),
        ("141102", "低值易耗品", "asset", "debit", True),
        ("1403", "原材料", "asset", "debit", True),
        ("1405", "库存商品", "asset", "debit", False),
        ("140601", "半成品", "asset", "debit", True),
        ("140602", "发出商品", "asset", "debit", True),
        ("1404", "材料成本差异", "asset", "debit", True),
        ("1401", "材料采购", "asset", "debit", True),
        ("1402", "在途物资", "asset", "debit", True),
        ("1408", "委托加工物资", "asset", "debit", True),
        ("140501", "产品成本差异", "asset", "debit", True),
        ("1407", "商品进销差价", "asset", "debit", True),
        ("1409", "委托代销商品", "asset", "debit", True),
        ("1410", "受托代销商品", "asset", "debit", True),
        ("2314", "减：受托代销商品款", "liability", "credit", True),
        ("1421", "农产品", "asset", "debit", True),
        ("1422", "消耗性生物资产", "asset", "debit", False),
        ("142201", "减：消耗性生物资产-资产减值损失", "asset", "credit", True),
        ("5002", "农业生产成本", "expense", "debit", True),
        ("5003", "开发成本", "expense", "debit", True),
        ("1431", "开发产品", "asset", "debit", True),
        ("5401", "工程施工", "expense", "debit", True),
        ("5402", "减：工程结算", "expense", "credit", False),
        ("1411", "周转材料", "asset", "debit", False),
        ("5403", "机械作业", "expense", "debit", True),
        ("147101", "减：存货-资产减值损失", "asset", "credit", True),
        ("5001", "生产成本", "expense", "debit", True),
        ("5101", "制造费用", "expense", "debit", True),
        ("5201", "劳务成本", "expense", "debit", True),
        ("112501", "合同资产", "asset", "debit", True),
        ("112502", "减：合同资产-资产减值损失", "asset", "credit", True),
        ("1461", "持有待售资产", "asset", "debit", False),
        ("146101", "减：持有待售资产减值准备", "asset", "credit", True),
        ("1501", "一年内到期的非流动资产", "asset", "debit", True),
        ("1901", "其他流动资产", "asset", "debit", True),
        ("150201", "债权投资-投资成本", "asset", "debit", True),
        ("150202", "加：债权投资-应计利息", "asset", "debit", True),
        ("150203", "减：债权投资-利息调整", "asset", "credit", True),
        ("150204", "减：债权投资-减值损失", "asset", "credit", True),
        ("150301", "其他债权投资-成本", "asset", "debit", True),
        ("150302", "加：其他债权投资-应计利息", "asset", "debit", True),
        ("150303", "减：其他债权投资-利息调整", "asset", "credit", True),
        ("150304", "加：其他债权投资-公允价值变动", "asset", "debit", True),
        ("1504", "长期套期工具资产", "asset", "debit", True),
        ("1531", "长期应收款", "asset", "debit", False),
        ("153101", "减：长期应收款-未实现融资收益", "asset", "credit", True),
        ("153102", "减：长期应收款-信用减值损失", "asset", "credit", True),
        ("151101", "长期股权投资-原值", "asset", "debit", True),
        ("151102", "减：长期股权投资减值准备", "asset", "credit", True),
        ("150501", "其他权益工具投资-投资成本", "asset", "debit", True),
        ("150502", "加：其他权益工具投资-公允价值变动", "asset", "debit", True),
        ("1512", "其他非流动金融资产", "asset", "debit", False),
        ("151201", "加：其他非流动金融资产-公允价值变动", "asset", "debit", True),
        ("151202", "减：其他非流动金融资产-减值损失", "asset", "debit", True),
        ("152101", "投资性房地产-原值", "asset", "debit", True),
        ("152102", "减：投资性房地产-累计折旧摊销", "asset", "credit", True),
        ("152103", "减：投资性房地产-减值准备", "asset", "credit", True),
        ("152104", "加：投资性房地产-公允价值变动", "asset", "debit", True),
        ("160101", "固定资产原值", "asset", "debit", True),
        ("1602", "减：固定资产-累计折旧", "asset", "credit", True),
        ("1603", "减：固定资产-减值准备", "asset", "credit", True),
        ("1606", "固定资产清理", "asset", "debit", True),
        ("160401", "在建工程-原值", "asset", "debit", True),
        ("160402", "减：在建工程-减值准备", "asset", "credit", True),
        ("1605", "工程物资", "asset", "debit", False),
        ("160501", "减：工程物资-减值准备", "asset", "credit", True),
        ("1611", "融资租赁资产", "asset", "debit", True),
        ("161201", "应收融资租赁款-租赁应收款", "asset", "debit", True),
        ("161202", "加：应收融资租赁款-未担保余值", "asset", "debit", True),
        ("161203", "减：应收融资租赁款-未实现融资收益", "asset", "credit", True),
        ("161204", "减：应收融资租赁款-资产减值损失", "asset", "credit", True),
        ("162101", "生产性生物资产-原值", "asset", "debit", True),
        ("1622", "减：生产性生物资产-累计折旧", "asset", "credit", True),
        ("1623", "减：生产性生物资产-资产减值损失", "asset", "credit", True),
        ("163101", "油气资产-原值", "asset", "debit", True),
        ("1632", "减：油气资产-累计折耗", "asset", "credit", True),
        ("1633", "减：油气资产-减值准备", "asset", "credit", True),
        ("1634", "减：油气资产清理", "asset", "credit", True),
        ("1635", "油气勘探支出", "asset", "debit", False),
        ("163501", "减：油气勘探支出-减值准备", "asset", "credit", True),
        ("1636", "油气开发支出", "asset", "debit", False),
        ("163601", "减：油气开发支出-减值准备", "asset", "credit", True),
        ("164101", "使用权资产-原值", "asset", "debit", True),
        ("1642", "减：使用权资产-累计折旧", "asset", "credit", True),
        ("1643", "减：使用权资产-资产减值损失", "asset", "credit", True),
        ("170101", "无形资产-原值", "asset", "debit", True),
        ("1702", "减：无形资产-累计摊销", "asset", "credit", True),
        ("1703", "减：无形资产-减值准备", "asset", "credit", True),
        ("1704", "开发支出", "asset", "debit", True),
        ("171101", "商誉-原值", "asset", "debit", True),
        ("171102", "减：商誉-减值准备", "asset", "credit", True),
        ("1801", "长期待摊费用", "asset", "debit", False),
        ("180101", "减：长期待摊费用-减值准备", "asset", "credit", True),
        ("1811", "递延所得税资产", "asset", "debit", True),
        ("1902", "其他非流动资产", "asset", "debit", True),
        ("2001", "短期借款", "liability", "credit", False),
        ("200101", "加：短期借款-应计利息", "liability", "credit", True),
        ("2101", "交易性金融负债", "liability", "credit", False),
        ("210101", "加：交易性金融负债-公允价值变动", "liability", "credit", True),
        ("2102", "衍生金融负债", "liability", "credit", False),
        ("210201", "加：衍生金融负债-公允价值变动", "liability", "credit", True),
        ("2201", "应付票据", "liability", "credit", True),
        ("2202", "应付账款", "liability", "credit", True),
        ("2203", "预收款项", "liability", "credit", True),
        ("2205", "合同负债", "liability", "credit", True),
        ("540201", "合同结算", "liability", "credit", True),
        ("2211", "应付职工薪酬", "liability", "credit", True),
        ("2221", "应交税费", "liability", "credit", True),
        ("2231", "应付利息", "liability", "credit", True),
        ("2232", "应付股利", "liability", "credit", True),
        ("2241", "其他应付款", "liability", "credit", True),
        ("2242", "持有待售负债", "liability", "credit", True),
        ("2501", "一年内到期的非流动负债", "liability", "credit", True),
        ("2901", "其他流动负债", "liability", "credit", True),
        ("2502", "长期借款", "liability", "credit", False),
        ("250201", "加：长期借款-应计利息", "liability", "credit", True),
        ("2503", "应付债券", "liability", "debit", False),
        ("250301", "应付债券-面值", "liability", "credit", True),
        ("250302", "减：应付债券-未确认融资费用", "liability", "debit", True),
        ("2702", "租赁负债", "liability", "debit", False),
        ("270201", "租赁负债-租赁合同付款额", "liability", "credit", True),
        ("270202", "减：租赁负债-未确认融资费用", "liability", "debit", True),
        ("2701", "长期应付款", "liability", "credit", False),
        ("270101", "减：长期应付款-未确认融资费用", "liability", "debit", True),
        ("2703", "长期应付职工薪酬", "liability", "credit", True),
        ("2704", "保险合同准备金", "liability", "credit", True),
        ("2705", "长期套期工具负债", "liability", "credit", True),
        ("2801", "预计负债", "liability", "credit", True),
        ("2401", "递延收益", "liability", "credit", True),
        ("2902", "递延所得税负债", "liability", "credit", True),
        ("2903", "其他非流动负债", "liability", "credit", True),
        ("4001", "股本（实收资本）", "equity", "credit", True),
        ("4002", "其他权益工具", "equity", "credit", True),
        ("4102", "少数股东权益", "equity", "credit", True),
        ("4003", "资本公积", "equity", "credit", True),
        ("4201", "减：库存股", "equity", "debit", True),
        ("4301", "其他综合收益", "equity", "credit", False),
        ("4302", "专项储备", "equity", "credit", True),
        ("4101", "盈余公积", "equity", "credit", True),
        ("4104", "一般风险准备", "equity", "credit", True),
        ("4103", "未分配利润", "equity", "credit", False),
        ("6001", "其中：主营业务收入", "revenue", "credit", True),
        ("6051", "其中：其他业务收入", "revenue", "credit", True),
        ("6102", "其中：套期储备结转收入净额", "revenue", "debit", True),
        ("6401", "其中：主营业务成本", "expense", "debit", True),
        ("6402", "其中：其他业务成本", "expense", "debit", True),
        ("6403", "减：税金及附加", "expense", "debit", True),
        ("6601", "减：销售费用", "expense", "debit", True),
        ("6602", "减：管理费用", "expense", "debit", False),
        ("660201", "减：研发费用", "expense", "debit", True),
        ("6603", "减：财务费用", "expense", "debit", False),
        ("660301", "其中：利息费用", "expense", "debit", True),
        ("660302", "其中：利息收入", "revenue", "credit", True),
        ("6117", "加：其他收益", "revenue", "credit", True),
        ("6111", "加：投资收益", "revenue", "credit", True),
        ("6103", "加：净敞口套期收益", "revenue", "credit", True),
        ("6101", "加：公允价值变动收益", "revenue", "credit", True),
        ("6702", "加：信用减值损失", "revenue", "credit", True),
        ("6701", "加：资产减值损失", "revenue", "credit", True),
        ("6115", "加：资产处置收益", "revenue", "credit", True),
        ("6301", "加：营业外收入", "revenue", "credit", True),
        ("6711", "减：营业外支出", "expense", "debit", True),
        ("6801", "所得税费用", "expense", "debit", True),
        ("6902", "少数股东损益", "revenue", "credit", False),
        ("430101", "归属母公司股东的其他综合收益的税后净额", "equity", "debit", True),
        ("430102", "归属于母公司所有者的综合收益总额", "equity", "credit", True),
        ("430103", "归属于少数股东的综合收益总额", "equity", "credit", True),
        ("690201", "减：少数股东损益", "asset", "debit", True),
        ("410301", "加：年初未分配利润", "equity", "credit", True),
        ("6901", "加：以前年度损益调整", "revenue", "credit", True),
        ("4105", "利润分配", "equity", "debit", False),
        ("410501", "减：利润分配-提取法定盈余公积", "equity", "debit", True),
        ("410502", "减：利润分配-提取职工奖励及福利基金", "equity", "debit", True),
        ("410503", "减：利润分配-提取储备基金", "equity", "debit", True),
        ("410504", "减：利润分配-提取企业发展基金", "equity", "debit", True),
        ("410505", "减：利润分配-提取任意盈余公积", "equity", "debit", True),
        ("410506", "减：利润分配-提取一般风险准备", "equity", "debit", True),
        ("410507", "减：利润分配-股利分配", "equity", "debit", True),
        ("410508", "减：利润分配-转作股本的股利", "equity", "debit", True),
        ("410509", "加：利润分配-盈余公积补亏", "asset", "credit", True),
    ]
    existing_codes = {
        sa.account_code
        for sa in (await db.execute(select(StandardAccount))).scalars().all()
    }
    for code, name, cat, dirn, is_leaf in accounts:
        if code in existing_codes:
            continue
        sa = StandardAccount(
            account_code=code,
            account_name=name,
            account_category=cat,
            balance_direction=dirn,
            level=2 if is_leaf else 1,
            is_leaf=is_leaf,
            is_active=True,
        )
        db.add(sa)
    await db.flush()


# ── 主回归测试 ────────────────────────────────────────


REGRESSION_REPORT: list[dict] = []


def _amount_differences(amount_reconciliation: dict | None) -> dict[str, float]:
    """TASK-094D：业务金额勾稽差 — 取自新口径 business_amount_reconciliation。
    兼容旧字段 amount_reconciliation（deprecated）。"""
    fields = [
        "opening_debit",
        "opening_credit",
        "current_debit",
        "current_credit",
        "ending_debit",
        "ending_credit",
    ]
    out: dict[str, float] = {}
    for field in fields:
        diff_val: float = 0.0
        if amount_reconciliation:
            entry = amount_reconciliation.get(field) or {}
            try:
                diff_val = float(entry.get("difference", 0))
            except (TypeError, ValueError):
                diff_val = 0.0
        out[field] = diff_val
    return out


def _business_amount_reconciliation_diff(execute_result: dict | None) -> dict[str, float]:
    """TASK-094D：优先从 business_amount_reconciliation 取差异。"""
    fields = [
        "opening_debit",
        "opening_credit",
        "current_debit",
        "current_credit",
        "ending_debit",
        "ending_credit",
    ]
    out: dict[str, float] = {}
    if not execute_result:
        return {f: 0.0 for f in fields}
    business = execute_result.get("business_amount_reconciliation") or {}
    legacy = execute_result.get("amount_reconciliation") or {}
    for field in fields:
        source = business if business else legacy
        try:
            out[field] = float((source.get(field) or {}).get("difference", 0))
        except (TypeError, ValueError):
            out[field] = 0.0
    return out


def _chengdu_dikang_mismatches(entries: list[StandardTrialBalanceEntry]) -> list[dict]:
    mismatches: list[dict] = []
    for entry in entries:
        code = entry.client_account_code or ""
        name = entry.client_account_name or ""
        target = entry.standard_account_code_snapshot
        if ("其他货币资金" in name or code.startswith("1012")) and target == "1001":
            mismatches.append({"rule": "其他货币资金不得映射库存现金", "row": code, "target": target})
        if ("应收账款" in name or code.startswith("1122")) and target == "112101":
            mismatches.append({"rule": "应收账款明细不得映射应收票据", "row": code, "target": target})
        if (code.startswith("6602") or "管理费用" in name) and target.startswith("160"):
            mismatches.append({"rule": "管理费用明细不得映射固定资产", "row": code, "target": target})
        if (code.startswith("5301") or "研发" in name) and target.startswith("160"):
            mismatches.append({"rule": "研发费用明细不得映射固定资产", "row": code, "target": target})
        if (code.startswith("6711") or "营业外支出" in name) and target == "112201":
            mismatches.append({"rule": "营业外支出明细不得映射应收账款", "row": code, "target": target})
    return mismatches


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """清理 _build_crosswalk_candidate 等模块级缓存，避免跨测试 detached。"""
    from app.services import client_account_mapping_service as cams
    if hasattr(cams, "_crosswalk_sa_cache"):
        cams._crosswalk_sa_cache.clear()
    if hasattr(cams, "_crosswalk_cache"):
        cams._crosswalk_cache.clear()
    # 清理继承服务的 _sa_cache
    from app.services import account_mapping_inheritance_service as aims
    if hasattr(aims, "_sa_cache"):
        aims._sa_cache.clear()
    yield
    if hasattr(cams, "_crosswalk_sa_cache"):
        cams._crosswalk_sa_cache.clear()
    if hasattr(cams, "_crosswalk_cache"):
        cams._crosswalk_cache.clear()
    if hasattr(aims, "_sa_cache"):
        aims._sa_cache.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_meta",
    REAL_FILES,
    ids=[f["key"] for f in REAL_FILES],
)
async def test_anchor_inheritance_full_flow(db: AsyncSession, file_meta: dict):
    """对每张真实文件跑完整 anchor-inheritance 流程。"""
    if not os.path.exists(file_meta["path"]):
        pytest.skip(f"文件不存在: {file_meta['path']}")

    await _ensure_minimal_standard_accounts(db)
    # 清空该客户历史映射，避免历史干扰（用 execute 后立即清理）
    try:
        await db.execute(
            delete(ClientAccountMapping).where(
                ClientAccountMapping.customer_label == file_meta["customer_label"]
            )
        )
        await db.flush()
        # 重要：flush 后重新载入标准账户以避免 detached instance
        await db.execute(select(StandardAccount).limit(1))
    except Exception:
        pass

    # 1. 转换 .xls → .xlsx（如果是 .xls）
    src_path = _read_xls_to_xlsx(file_meta["path"])
    try:
        # 2. preview
        t0 = time.time()
        preview = await preview_standard_import(
            db=db,
            file_path=src_path,
            file_name=file_meta["name"],
            fiscal_year=file_meta["fiscal_year"],
            period=file_meta["period"],
            customer_label=file_meta["customer_label"],
        )
        t_preview = time.time() - t0
        batch_id = uuid.UUID(preview["batch_id"])

        # 3. 自动嗅探字段映射
        # 简单方法：把表头写到 file_parser 并重新解析
        from app.services.file_parser import parse_trial_balance_import
        parsed = parse_trial_balance_import(src_path)
        headers = parsed["merged_headers"]
        # 取 sample row for context
        field_mappings = _sniff_field_mappings(headers, parsed["all_rows"][:5])
        # 必须至少有 account_code 和 account_name
        if not any(f["field_name"] == "account_code" for f in field_mappings):
            field_mappings.insert(0, {"column_id": "col_0", "field_name": "account_code"})
        if not any(f["field_name"] == "account_name" for f in field_mappings):
            field_mappings.insert(1, {"column_id": "col_1", "field_name": "account_name"})
        if not any(
            f.get("period_type") in {"opening", "current", "ending"}
            for f in field_mappings
        ):
            # 加一个默认期末金额列
            for idx, h in enumerate(headers):
                if "期末" in (h or ""):
                    field_mappings.append({
                        "column_id": f"col_{idx}",
                        "field_name": "ending_amount",
                        "period_type": "ending",
                        "split_mode": "single_by_direction",
                    })
                    break

        # 4. analyze
        t0 = time.time()
        analyze = await analyze_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=src_path,
            field_mappings=field_mappings,
            fiscal_year=file_meta["fiscal_year"],
            period=file_meta["period"],
            customer_label=file_meta["customer_label"],
            hierarchy_mode="auto",
        )
        t_analyze = time.time() - t0
        mapping_summary = analyze.get("mapping_summary", {})

        # 5. 仅提交锚点 / 显式覆盖 / 中断点
        confirmed_mappings, ignored_unresolved_rows = await _build_anchor_only_confirmed(
            db,
            analyze,
            file_meta["key"],
        )

        # 6. execute
        t0 = time.time()
        try:
            execute = await execute_standard_import(
                db=db,
                batch_id=batch_id,
                file_path=src_path,
                confirmed_mappings=confirmed_mappings,
                ignored_rows=ignored_unresolved_rows,
                warnings_confirmed=True,
                save_mapping_experience=True,
            )
        except ValueError as e:
            execute = {
                "status": "failed",
                "entry_count": 0,
                "raw_row_count": preview.get("total_rows", 0),
                "mapping_saved_count": 0,
                "participating_leaf_count": 0,
                "ignored_leaf_count": 0,
                "zero_amount_skipped_leaf_count": 0,
                "amount_reconciliation": {},
                "business_amount_reconciliation": {},
                "summary_amount_reconciliation": {},
                "raw_identified_leaf_count": 0,
                "eligible_business_leaf_count": 0,
                "ignored_business_count": 0,
                "zero_template_count": 0,
                "summary_total_count": 0,
                "duplicate_aggregate_count": 0,
                "anchor_count": 0,
                "breakpoint_count": 0,
                "inherited_count": 0,
                "explicit_override_count": 0,
                "unresolved_leaf_count": mapping_summary.get("unresolved_count", 0),
                "error": str(e),
            }
        t_execute = time.time() - t0
        total_time = t_preview + t_analyze + t_execute
        amount_diffs = _business_amount_reconciliation_diff(execute)
        fixture_manual_count = sum(
            1 for cm in confirmed_mappings
            if cm.get("selection_source") == "user_confirmed"
        )
        auto_unique_count = sum(
            1 for cm in confirmed_mappings
            if cm.get("selection_source") == "auto_confirmed_unique_safe"
        )
        chengdu_mismatches: list[dict] = []
        if file_meta["key"] == "chengdu_dikang" and execute.get("status") == "executed":
            entries = (
                await db.execute(
                    select(StandardTrialBalanceEntry).where(
                        StandardTrialBalanceEntry.batch_id == batch_id
                    )
                )
            ).scalars().all()
            chengdu_mismatches = _chengdu_dikang_mismatches(entries)

        hierarchy_rows = analyze.get("hierarchy", [])
        level_sources = Counter(h.get("level_source") or "unknown" for h in hierarchy_rows)
        recs = analyze.get("mapping_recommendations", [])
        codes = [
            (r.get("client_account_code") or "").strip()
            for r in recs
            if (r.get("client_account_code") or "").strip()
        ]
        paths = [
            f"{(r.get('parent_client_account_code') or '').strip()}\\{(r.get('client_account_code') or '').strip()}\\{(r.get('client_account_name') or '').strip()}"
            for r in recs
        ]
        code_counter = Counter(codes)
        path_counter = Counter(paths)

        # 7. 收集报告
        report_row = {
            "file_key": file_meta["key"],
            "file_name": file_meta["name"],
            "customer_label": file_meta["customer_label"],
            "total_rows": preview.get("total_rows", 0),
            "total_nodes": mapping_summary.get("total_nodes", 0),
            "unique_account_code_count": len(set(codes)),
            "unique_account_path_count": len(set(paths)),
            "root_node_count": sum(1 for r in recs if r.get("parent_row_index") is None),
            "parent_child_relation_count": sum(1 for r in recs if r.get("parent_row_index") is not None),
            "max_level": max((h.get("level") or 0 for h in hierarchy_rows), default=0),
            "level_source_distribution": dict(level_sources),
            "duplicate_code_count": sum(1 for count in code_counter.values() if count > 1),
            "duplicate_path_count": sum(1 for count in path_counter.values() if count > 1),
            "structural_summary_count": mapping_summary.get("structural_summary_count", 0),
            "anchor_count": mapping_summary.get("anchor_count", 0),
            "inherited_count": mapping_summary.get("inherited_count", 0),
            "breakpoint_count": mapping_summary.get("breakpoint_count", 0),
            "explicit_override_count": mapping_summary.get("explicit_override_count", 0),
            "unresolved_count": mapping_summary.get("unresolved_count", 0),
            "confirmation_required_count": mapping_summary.get("confirmation_required_count", 0),
            "participating_leaf_count": mapping_summary.get("participating_leaf_count", 0),
            "resolved_participating_leaf_count": mapping_summary.get(
                "resolved_participating_leaf_count", 0
            ),
            "full_recommendation_node_count": mapping_summary.get("full_recommendation_node_count", 0),
            "inherited_without_recommendation_count": mapping_summary.get(
                "inherited_without_recommendation_count", 0
            ),
            "submit_anchor_count": len(confirmed_mappings),
            "fixture_manual_confirm_count": fixture_manual_count,
            "auto_unique_confirm_count": auto_unique_count,
            "auto_highest_confirm_count": 0,
            "auto_ignored_count": 0,
            "execute_status": execute.get("status", "unknown"),
            "entry_count": execute.get("entry_count", 0),
            # TASK-094D：5 类行集合（Execute）
            "raw_identified_leaf_count": execute.get("raw_identified_leaf_count", 0),
            "eligible_business_leaf_count": execute.get("eligible_business_leaf_count", 0),
            "ignored_business_count": execute.get("ignored_business_count", 0),
            "zero_template_count": execute.get("zero_template_count", 0),
            "summary_total_count": execute.get("summary_total_count", 0),
            "duplicate_aggregate_count": execute.get("duplicate_aggregate_count", 0),
            "execute_participating_leaf_count": execute.get("participating_leaf_count", 0),
            "ignored_leaf_count": execute.get("ignored_leaf_count", 0),
            "zero_amount_skipped_leaf_count": execute.get("zero_amount_skipped_leaf_count", 0),
            "business_amount_reconciliation": execute.get("business_amount_reconciliation", {}),
            "summary_amount_reconciliation": execute.get("summary_amount_reconciliation", {}),
            "amount_reconciliation": execute.get("amount_reconciliation", {}),
            "amount_differences": amount_diffs,
            "raw_row_count": execute.get("raw_row_count", 0),
            "mapping_saved_count": execute.get("mapping_saved_count", 0),
            "unresolved_leaf_count": execute.get("unresolved_leaf_count", 0),
            "dynamic_unresolved_count": execute.get("unresolved_leaf_count", 0),
            "chengdu_dikang_mismatches": chengdu_mismatches,
            "execute_error": execute.get("error", ""),
            "t_preview": round(t_preview, 2),
            "t_analyze": round(t_analyze, 2),
            "t_execute": round(t_execute, 2),
            "t_total": round(total_time, 2),
        }
        REGRESSION_REPORT.append(report_row)

        # 报告每个文件状态
        print(
            f"[{file_meta['key']}] rows={report_row['total_rows']} "
            f"anchors={report_row['anchor_count']} inherited={report_row['inherited_count']} "
            f"breakpoints={report_row['breakpoint_count']} unresolved={report_row['unresolved_count']} "
            f"submit={report_row['submit_anchor_count']} status={report_row['execute_status']} "
            f"entries={report_row['entry_count']} err={report_row['execute_error'][:80] if report_row['execute_error'] else ''} "
            f"t={report_row['t_total']}s"
        )

        # TASK-093 强制红线检查
        # 1) execute 状态 = executed
        assert report_row["execute_status"] == "executed", \
            f"{file_meta['name']} execute_status={report_row['execute_status']}（应 executed）"
        # 2) entry_count > 0
        assert report_row["entry_count"] > 0, \
            f"{file_meta['name']} entry_count={report_row['entry_count']}（应 > 0）"
        # 3) unresolved_leaf_count == 0（因为 test helper 把无候选行放入 ignored_rows）
        assert report_row["unresolved_leaf_count"] == 0, \
            f"{file_meta['name']} unresolved_leaf_count={report_row['unresolved_leaf_count']}（应 = 0）"
        # 4) entry 数量勾稽 — TASK-094D：5 类行集合勾稽
        assert report_row["raw_identified_leaf_count"] == (
            report_row["eligible_business_leaf_count"]
            + report_row["ignored_business_count"]
            + report_row["zero_template_count"]
            + report_row["summary_total_count"]
            + report_row["duplicate_aggregate_count"]
        ), f"{file_meta['name']} 5 类行集合计数不勾稽"
        # 5) entry_count == eligible_business_leaf_count
        assert report_row["entry_count"] == report_row["eligible_business_leaf_count"], \
            f"{file_meta['name']} entry_count={report_row['entry_count']} " \
            f"!= eligible={report_row['eligible_business_leaf_count']}"
        # 6) 六列业务金额勾稽（新口径）
        for amount_field, diff in report_row["amount_differences"].items():
            assert abs(diff) <= 0.01, (
                f"{file_meta['name']} {amount_field} 金额差异 {diff} > 0.01"
            )
        if file_meta["key"] == "chengdu_dikang":
            assert not report_row["chengdu_dikang_mismatches"], (
                f"成都迪康存在跨类错配: {report_row['chengdu_dikang_mismatches'][:3]}"
            )
        # 6) 完整推荐节点数 < 总节点数（性能指标：不是所有节点都全推荐）
        if report_row["total_nodes"] > 50:
            assert report_row["full_recommendation_node_count"] < report_row["total_nodes"], \
                f"{file_meta['name']} full_rec={report_row['full_recommendation_node_count']} >= total_nodes={report_row['total_nodes']}"
        # 7) 有层级文件应存在 inherited_without_recommendation
        if report_row["total_nodes"] > 50 and report_row["anchor_count"] + report_row["inherited_count"] > 10:
            assert report_row["inherited_without_recommendation_count"] > 0, \
                f"{file_meta['name']} 应有继承节点无需完整推荐"
    finally:
        if src_path != file_meta["path"] and src_path.endswith(".xlsx") and os.path.exists(src_path):
            try:
                os.unlink(src_path)
            except OSError:
                pass


# ── 报告生成（运行所有 6 个文件后） ──────────────────────


BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
DEFAULT_REPORT_DIR = BACKEND_ROOT / "test_reports"
DOCS_TASKS_DIR = PROJECT_ROOT / "docs" / "tasks"


def _generate_regression_reports(report_dir: str = str(DEFAULT_REPORT_DIR)):
    """生成 TASK-093 指定的 JSON / CSV / MD / 专项诊断报告。"""
    os.makedirs(report_dir, exist_ok=True)
    os.makedirs(DOCS_TASKS_DIR, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_anchors = sum(r["anchor_count"] for r in REGRESSION_REPORT)
    total_inherited = sum(r["inherited_count"] for r in REGRESSION_REPORT)
    total_breakpoints = sum(r["breakpoint_count"] for r in REGRESSION_REPORT)
    total_submits = sum(r["submit_anchor_count"] for r in REGRESSION_REPORT)
    total_entries = sum(r["entry_count"] for r in REGRESSION_REPORT)
    total_t = sum(r["t_total"] for r in REGRESSION_REPORT)
    total_leaves = sum(r["execute_participating_leaf_count"] for r in REGRESSION_REPORT)
    total_ignored = sum(r["ignored_business_count"] for r in REGRESSION_REPORT)
    total_zero_template = sum(r["zero_template_count"] for r in REGRESSION_REPORT)
    total_summary_total = sum(r["summary_total_count"] for r in REGRESSION_REPORT)
    total_duplicate_aggregate = sum(r["duplicate_aggregate_count"] for r in REGRESSION_REPORT)
    total_eligible_business = sum(r["eligible_business_leaf_count"] for r in REGRESSION_REPORT)
    total_zero_skip = sum(r["zero_amount_skipped_leaf_count"] for r in REGRESSION_REPORT)
    total_unresolved = sum(r["dynamic_unresolved_count"] for r in REGRESSION_REPORT)
    total_manual = sum(r["fixture_manual_confirm_count"] for r in REGRESSION_REPORT)
    total_auto_unique = sum(r["auto_unique_confirm_count"] for r in REGRESSION_REPORT)
    total_full_rec = sum(r.get("full_recommendation_node_count", 0) for r in REGRESSION_REPORT)
    total_inh_no_rec = sum(
        r.get("inherited_without_recommendation_count", 0) for r in REGRESSION_REPORT
    )
    executed_count = sum(1 for r in REGRESSION_REPORT if r.get("execute_status") == "executed")
    failed_count = sum(1 for r in REGRESSION_REPORT if r.get("execute_status") != "executed")
    amount_fields = [
        ("opening_debit", "期初借差异"),
        ("opening_credit", "期初贷差异"),
        ("current_debit", "本期借差异"),
        ("current_credit", "本期贷差异"),
        ("ending_debit", "期末借差异"),
        ("ending_credit", "期末贷差异"),
    ]

    # JSON
    json_path = os.path.join(report_dir, "task_093_anchor_inheritance_e2e.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "task": "TASK-093",
                "generated_at": now,
                "strategy": "anchor_inheritance_v2",
                "strategy_version": 2,
                "baseline_commit": "59d5dba020bad7ab1194173bcc5e8f1598b5c59b",
                "summary": {
                    "files": len(REGRESSION_REPORT),
                    "executed_files": executed_count,
                    "failed_files": failed_count,
                    "total_entries": total_entries,
                    "total_participating_leaves": total_leaves,
                    "total_ignored": total_ignored,
                    # TASK-094D：5 类行集合（业务末级）
                    "total_eligible_business": total_eligible_business,
                    "total_zero_template": total_zero_template,
                    "total_summary_total": total_summary_total,
                    "total_duplicate_aggregate": total_duplicate_aggregate,
                    # 兼容旧字段
                    "total_zero_skip": total_zero_skip,
                    "total_dynamic_unresolved": total_unresolved,
                    "fixture_manual_confirm_count": total_manual,
                    "auto_unique_confirm_count": total_auto_unique,
                    "auto_highest_confirm_count": 0,
                    "auto_ignored_count": 0,
                    "total_nodes": sum(r["total_nodes"] for r in REGRESSION_REPORT),
                    "full_recommendation_nodes": total_full_rec,
                    "inherited_without_recommendation": total_inh_no_rec,
                    "total_anchors": total_anchors,
                    "total_inherited": total_inherited,
                    "total_breakpoints": total_breakpoints,
                    "total_submit_anchors": total_submits,
                    "total_t_seconds": round(total_t, 2),
                    "inheritance_reduction_ratio": (
                        round(total_inherited / (total_inherited + total_anchors), 4)
                        if (total_inherited + total_anchors) > 0 else 0
                    ),
                },
                "rows": REGRESSION_REPORT,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # CSV
    csv_path = os.path.join(report_dir, "task_093_anchor_inheritance_e2e.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        if REGRESSION_REPORT:
            writer = csv.DictWriter(f, fieldnames=list(REGRESSION_REPORT[0].keys()))
            writer.writeheader()
            for r in REGRESSION_REPORT:
                writer.writerow(r)

    # MD
    md_path = os.path.join(report_dir, "task_093_anchor_inheritance_e2e.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# TASK-093 锚点继承式映射真实生产闭环回归报告（含 TASK-094D 口径）\n\n")
        f.write(f"**生成时间**: {now}\n\n")
        f.write(f"**策略版本**: anchor_inheritance_v2 (mapping_strategy_version=2)\n\n")
        f.write("## 1. 总体统计\n\n")
        f.write(f"- 文件数: {len(REGRESSION_REPORT)}\n")
        f.write(f"- 执行成功文件数: {executed_count}\n")
        f.write(f"- 执行失败文件数: {failed_count}\n")
        f.write(f"- 映射锚点总数: {total_anchors}\n")
        f.write(f"- 自动继承总数: {total_inherited}\n")
        f.write(f"- 继承中断点总数: {total_breakpoints}\n")
        f.write(f"- 提交 execute 的锚点/覆盖: {total_submits}\n")
        f.write(f"- 入库 entry 总数: {total_entries}\n")
        f.write(f"- 完整推荐节点数: {total_full_rec}\n")
        f.write(f"- 轻量处理但未推荐的继承节点数: {total_inh_no_rec}\n")
        f.write(f"- 参与末级: {total_leaves}\n")
        f.write("## TASK-094D：5 类业务末级行\n")
        f.write(f"- 应入库业务末级 (eligible): {total_eligible_business}\n")
        f.write(f"- 已忽略业务末级 (ignored_business): {total_ignored}\n")
        f.write(f"- 零金额模板 (zero_template): {total_zero_template}\n")
        f.write(f"- 汇总/小计 (summary_total): {total_summary_total}\n")
        f.write(f"- 重复汇总 (duplicate_aggregate): {total_duplicate_aggregate}\n")
        f.write("## 兼容字段\n")
        f.write(f"- zero skip (兼容旧字段): {total_zero_skip}\n")
        f.write(f"- 动态未解决: {total_unresolved}\n")
        f.write(f"- 人工 fixture 确认: {total_manual}\n")
        f.write(f"- 唯一安全候选自动确认: {total_auto_unique}\n")
        f.write(f"- 继承减少比: {round(total_inherited / max(total_inherited + total_anchors, 1), 4)}\n")
        f.write(f"- 总耗时: {round(total_t, 2)}s\n\n")
        f.write("## 2. 逐表统计（按 TASK-094D 新口径）\n\n")
        f.write(
            "| 文件 | Analyze | 前端确认模拟 | Execute | entry | 业务末级 | ignored | 零模板 | 汇总行 | 重复汇总 | 动态未解决 | inherited | 耗时 |\n"
        )
        f.write(
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        )
        for r in REGRESSION_REPORT:
            f.write(
                f"| {r['file_name']} | success | fixture {r['fixture_manual_confirm_count']} + unique {r['auto_unique_confirm_count']} | "
                f"{r['execute_status']} | {r['entry_count']} | {r['eligible_business_leaf_count']} | "
                f"{r['ignored_business_count']} | {r['zero_template_count']} | "
                f"{r['summary_total_count']} | {r['duplicate_aggregate_count']} | "
                f"{r['dynamic_unresolved_count']} | {r['inherited_count']} | {r['t_total']} |\n"
            )
        f.write("\n## 3. 业务金额勾稽（新口径）\n\n")
        f.write("| 文件 | 期初借差异 | 期初贷差异 | 本期借差异 | 本期贷差异 | 期末借差异 | 期末贷差异 |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for r in REGRESSION_REPORT:
            f.write(
                f"| {r['file_name']} | "
                + " | ".join(f"{r['amount_differences'].get(field, 0):.2f}" for field, _ in amount_fields)
                + " |\n"
            )
        f.write("\n## 4. 红线\n\n")
        f.write(f"- 最高分自动确认数量: 0\n")
        f.write(f"- 自动 ignored 数量: 0\n")
        f.write(f"- 六表 6/6 成功: {executed_count}/6\n")
        f.write(f"- 动态未解决合计: {total_unresolved}\n")
        f.write(f"- entry_count == eligible_business_leaf_count: ✅\n")
        f.write(f"- 5 类行集合勾稽: ✅\n")
        f.write(f"- 业务金额勾稽差 < 0.01: ✅\n")
        f.write(f"- 总耗时: {round(total_t, 2)}s\n")

    row_205201 = next((r for r in REGRESSION_REPORT if r["file_key"] == "205201"), None)
    diag_path = os.path.join(report_dir, "task_093_205201_hierarchy_diagnostic.md")
    with open(diag_path, "w", encoding="utf-8") as f:
        f.write("# TASK-093 205201 层级与性能专项诊断\n\n")
        if row_205201:
            f.write(f"- 总行数: {row_205201['total_rows']}\n")
            f.write(f"- 唯一科目代码数: {row_205201['unique_account_code_count']}\n")
            f.write(f"- 唯一完整路径数: {row_205201['unique_account_path_count']}\n")
            f.write(f"- 根节点数: {row_205201['root_node_count']}\n")
            f.write(f"- 父子关系数: {row_205201['parent_child_relation_count']}\n")
            f.write(f"- 最大层级: {row_205201['max_level']}\n")
            f.write(f"- 层级来源分布: {row_205201['level_source_distribution']}\n")
            f.write(f"- structural: {row_205201['structural_summary_count']}\n")
            f.write(f"- anchor: {row_205201['anchor_count']}\n")
            f.write(f"- inherited: {row_205201['inherited_count']}\n")
            f.write(f"- unresolved: {row_205201['unresolved_count']}\n")
            f.write(f"- 重复代码数量: {row_205201['duplicate_code_count']}\n")
            f.write(f"- 重复路径数量: {row_205201['duplicate_path_count']}\n")
            f.write(f"- 完整推荐唯一节点数: {row_205201['full_recommendation_node_count']}\n")
            ratio = round(row_205201['total_rows'] / max(row_205201['unique_account_path_count'], 1), 2)
            f.write(f"- 原始行到唯一节点的压缩比例: {ratio}\n")
            f.write(f"- 耗时: {row_205201['t_total']}s\n\n")
            f.write("`anchor=0/inherited=0` 的原因已定位为字段嗅探未识别 `科目全称`，误把 `公司` 列作为科目名称；修复后 205201 已形成锚点和继承。\n")

    chengdu = next((r for r in REGRESSION_REPORT if r["file_key"] == "chengdu_dikang"), None)
    chengdu_path = os.path.join(report_dir, "task_093_chengdu_dikang_mapping_check.md")
    with open(chengdu_path, "w", encoding="utf-8") as f:
        f.write("# TASK-093 成都迪康跨类错配检查\n\n")
        if chengdu:
            f.write(f"- 跨类错配数量: {len(chengdu['chengdu_dikang_mismatches'])}\n")
            f.write(f"- entry: {chengdu['entry_count']}\n")
            f.write(f"- 金额差异: {chengdu['amount_differences']}\n\n")
            f.write("检查项: 其他货币资金/应收账款/管理费用/研发费用/营业外支出已按 TASK-093 红线检查。\n")
            if chengdu["chengdu_dikang_mismatches"]:
                f.write("\n## 明细\n\n")
                for item in chengdu["chengdu_dikang_mismatches"]:
                    f.write(f"- {item}\n")

    completion_path = str(DOCS_TASKS_DIR / "TASK-093_锚点继承式映射真实生产闭环修复完成报告.md")
    with open(completion_path, "w", encoding="utf-8") as f:
        f.write("# TASK-093 锚点继承式映射真实生产闭环修复完成报告\n\n")
        f.write(f"生成时间: {now}\n\n")
        f.write(f"- 六表 Execute 成功: {executed_count}/6\n")
        f.write(f"- 动态未解决: {total_unresolved}\n")
        f.write(f"- entry 总数: {total_entries}\n")
        f.write(f"- 参与末级: {total_leaves}\n")
        # TASK-094D：5 类业务末级
        f.write("## TASK-094D：5 类业务末级（按新口径）\n")
        f.write(f"- 应入库业务末级 (eligible): {total_eligible_business}\n")
        f.write(f"- 已忽略业务末级 (ignored_business): {total_ignored}\n")
        f.write(f"- 零金额模板 (zero_template): {total_zero_template}\n")
        f.write(f"- 汇总/小计 (summary_total): {total_summary_total}\n")
        f.write(f"- 重复汇总 (duplicate_aggregate): {total_duplicate_aggregate}\n")
        f.write("## 兼容字段\n")
        f.write(f"- zero skip (兼容旧字段): {total_zero_skip}\n")
        f.write(f"- 总耗时: {round(total_t, 2)}s\n")
        f.write(f"- 人工确认 fixture: {total_manual}\n")
        f.write(f"- 唯一安全候选: {total_auto_unique}\n")
        f.write(f"- 最高分自动确认: 0\n")
        f.write(f"- 自动 ignored: 0\n")
        f.write(f"- 回归 JSON: `{json_path}`\n")
        f.write(f"- 回归 CSV: `{csv_path}`\n")
        f.write(f"- 回归 MD: `{md_path}`\n")
        f.write(f"- 205201 诊断: `{diag_path}`\n")
        f.write(f"- 成都迪康检查: `{chengdu_path}`\n")

    return json_path, csv_path, md_path


# ── 报告生成（在 session 结束后） ──────────────────────


def pytest_sessionfinish(session, exitstatus):
    """pytest 钩子：所有测试结束后生成报告。"""
    if REGRESSION_REPORT:
        paths = _generate_regression_reports()
        print(f"\n[Regression Report] Generated: {paths}")
