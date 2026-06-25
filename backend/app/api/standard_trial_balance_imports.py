"""科目余额表标准化导入 API — TASK-044

端点：
  POST /preview   — 上传文件预览
  POST /{batch_id}/analyze  — 字段映射 + 层级识别 + 科目映射推荐
  POST /{batch_id}/execute  — 执行导入生成标准余额表
  GET  /{batch_id}          — 查询导入批次详情
"""

import uuid
import os
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.schemas.standard_trial_balance import (
    PreviewRequest,
    PreviewResponse,
    AnalyzeRequest,
    AnalyzeResponse,
    ExecuteRequest,
    ExecuteResponse,
    ImportBatchResponse,
)
from app.services.standard_trial_balance_import_service import (
    preview_standard_import,
    analyze_standard_import,
    execute_standard_import,
    get_import_batch,
)

router = APIRouter(prefix="/standard-trial-balance-imports", tags=["科目余额表标准化导入"])
settings = get_settings()
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(settings.UPLOAD_DIR) if settings.UPLOAD_DIR else Path("uploads")


# ── POST /preview ──────────────────────────────────

@router.post("/preview", response_model=PreviewResponse)
async def preview(
    file: UploadFile = File(...),
    fiscal_year: int | None = Form(None, description="会计年度"),
    period: int | None = Form(None, ge=1, le=12, description="会计期间"),
    customer_label: str | None = Form(None, description="客户标识"),
    source_label: str | None = Form(None, description="来源标识"),
    db: AsyncSession = Depends(get_db),
):
    """
    上传客户科目余额表 → 解析表头 + 取样本行 → 创建 draft 批次。

    返回 batch_id、列结构、样本数据，供前端展示字段映射界面。
    """
    # 校验文件格式
    ext = Path(file.filename or "unknown.xlsx").suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}（仅支持 .xlsx .xls .csv）",
        )

    # 保存上传文件
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"stb_preview_{uuid.uuid4().hex}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name

    try:
        content = await file.read()
        file_path.write_bytes(content)
    except Exception as e:
        logger.error(f"保存上传文件失败: {e}")
        raise HTTPException(status_code=500, detail="保存上传文件失败")

    try:
        result = await preview_standard_import(
            db=db,
            file_path=str(file_path),
            file_name=file.filename or "unknown",
            fiscal_year=fiscal_year,
            period=period,
            customer_label=customer_label,
            source_label=source_label,
        )
        return PreviewResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"预览失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器预览文件失败")


# ── POST /{batch_id}/analyze ───────────────────────

@router.post("/{batch_id}/analyze", response_model=AnalyzeResponse)
async def analyze(
    batch_id: uuid.UUID,
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    提交字段映射和金额配置 → 识别层级 + 推荐科目映射 + 拆分金额。

    返回层级树、科目映射候选、金额明细、错误和警告列表。
    批次状态变为 analyzed（或 blocked，如果存在严重错误）。
    """
    # 找到预览时保存的文件
    batch_info = await get_import_batch(db, batch_id)
    if batch_info is None:
        raise HTTPException(status_code=404, detail=f"批次 {batch_id} 不存在")

    # 查找对应的上传文件
    file_path = None
    for f in UPLOAD_DIR.iterdir():
        if f.is_file() and batch_info["file_name"] in f.name:
            file_path = str(f)
            break

    if file_path is None:
        raise HTTPException(status_code=404, detail="找不到对应的上传文件，请重新预览")

    field_mappings = [
        {
            "column_id": fm.column_id,
            "field_name": fm.field_name,
            "period_type": fm.period_type,
            "split_mode": fm.split_mode,
            "debit_column_id": fm.debit_column_id,
            "credit_column_id": fm.credit_column_id,
        }
        for fm in body.field_mappings
    ]

    try:
        result = await analyze_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            field_mappings=field_mappings,
            fiscal_year=body.fiscal_year,
            period=body.period,
            customer_label=body.customer_label,
            source_label=body.source_label,
            hierarchy_mode=body.hierarchy_mode,
        )
        return AnalyzeResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"分析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器分析导入数据失败")


# ── POST /{batch_id}/execute ───────────────────────

@router.post("/{batch_id}/execute", response_model=ExecuteResponse)
async def execute(
    batch_id: uuid.UUID,
    body: ExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    确认映射和警告 → 保存原始行快照 → 生成标准科目余额表。

    阻止条件：
    - 末级客户科目未映射到启用标准科目
    - 按标准方向拆分但标准科目无方向
    - 存在未确认的警告（warnings_confirmed=false）

    入库后保存客户科目映射经验，批次状态变为 executed。
    """
    # 找到上传文件
    batch_info = await get_import_batch(db, batch_id)
    if batch_info is None:
        raise HTTPException(status_code=404, detail=f"批次 {batch_id} 不存在")
    if batch_info["status"] not in ("previewed", "analyzed", "blocked"):
        raise HTTPException(
            status_code=400,
            detail=f"批次状态为 {batch_info['status']}，不能执行导入（需要 previewed/analyzed/blocked）",
        )

    file_path = None
    for f in UPLOAD_DIR.iterdir():
        if f.is_file() and batch_info["file_name"] in f.name:
            file_path = str(f)
            break

    if file_path is None:
        raise HTTPException(status_code=404, detail="找不到对应的上传文件，请重新预览")

    confirmed_mappings = [
        {
            "row_index": cm.row_index,
            "client_account_code": cm.client_account_code,
            "client_account_name": cm.client_account_name,
            "standard_account_id": cm.standard_account_id,
            "standard_account_code": cm.standard_account_code,
            "standard_account_name": cm.standard_account_name,
        }
        for cm in body.confirmed_mappings
    ]

    try:
        result = await execute_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            confirmed_mappings=confirmed_mappings,
            ignored_rows=body.ignored_rows,
            warnings_confirmed=body.warnings_confirmed,
            save_mapping_experience=body.save_mapping_experience,
        )
        return ExecuteResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"执行导入失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务器执行导入失败")


# ── GET /{batch_id} ────────────────────────────────

@router.get("/{batch_id}", response_model=ImportBatchResponse)
async def get_batch(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    查询导入批次详情，含状态、条目数、警告/错误汇总。
    """
    result = await get_import_batch(db, batch_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"批次 {batch_id} 不存在")
    return ImportBatchResponse(**result)
