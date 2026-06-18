"""数据导入 API"""

import uuid
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.services.import_service import preview_import, import_data

router = APIRouter(prefix="/imports", tags=["数据导入"])

settings = get_settings()


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    data_type: str = Form(..., description="数据类型: trial_balance / journal / subsidiary"),
):
    """
    预览导入：上传文件 → 返回表头识别结果和自动匹配。

    返回 matched（已匹配）、unmatched（未匹配）、missing（缺少的必填字段）。
    """
    # 校验数据类型
    if data_type not in ("trial_balance", "journal", "subsidiary"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的数据类型: {data_type}（可选: trial_balance / journal / subsidiary）",
        )

    # 校验文件扩展名
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(400, detail=f"不支持的文件格式: {ext}（仅支持 .xlsx .xls .csv）")

    # 保存临时文件
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"preview_{uuid.uuid4().hex}{ext}"

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        result = await preview_import(str(temp_path), data_type)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # 清理临时文件
        if temp_path.exists():
            temp_path.unlink()


@router.post("/execute")
async def execute(
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    company_id: str = Form(..., description="被审计单位 ID"),
    data_type: str = Form(..., description="数据类型: trial_balance / journal / subsidiary"),
    column_mapping: str | None = Form(None, description="JSON格式列映射: {\"原始表头\": \"标准字段\"}"),
):
    """
    执行导入：上传文件 + 确认映射 → 校验 → 入库。

    column_mapping 为 JSON 字符串，key 为文件中表头，value 为标准字段。
    若不传则使用自动匹配。
    """
    # 校验数据类型
    if data_type not in ("trial_balance", "journal", "subsidiary"):
        raise HTTPException(400, detail=f"不支持的数据类型: {data_type}")

    # 校验公司
    try:
        cid = uuid.UUID(company_id)
    except ValueError:
        raise HTTPException(400, detail="无效的公司 ID")

    # 保存上传文件
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(400, detail=f"不支持的文件格式: {ext}")

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"import_{uuid.uuid4().hex}{ext}"

    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # 解析用户映射
        import json
        mapping = None
        if column_mapping:
            try:
                mapping = json.loads(column_mapping)
            except json.JSONDecodeError:
                raise HTTPException(400, detail="column_mapping JSON 格式无效")

        result = await import_data(
            db=db,
            company_id=cid,
            file_path=str(file_path),
            data_type=data_type,
            column_mapping=mapping,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
