"""导入模板管理 API"""

import uuid
import shutil
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.schemas.import_template import (
    TemplateCreate, TemplateUpdate, TemplateResponse, TemplateListResponse,
    TemplateTestResult, FromSampleRequest,
)
from app.services.template_service import (
    get_templates, get_template, create_template, update_template, delete_template,
    from_sample, test_template,
)

router = APIRouter(prefix="/import-templates", tags=["导入模板库"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="模板不存在，请检查模板 ID 是否正确")


# ── 列表 ──────────────────────────────────────────────

@router.get("", response_model=TemplateListResponse)
async def list_templates(
    db: AsyncSession = Depends(get_db),
    data_type: str | None = Query(None, description="按数据类型筛选"),
    is_active: bool | None = Query(None, description="按启用状态筛选"),
):
    """获取模板列表，支持按 data_type 和 is_active 筛选"""
    items = await get_templates(db, data_type=data_type, is_active=is_active)
    return TemplateListResponse(
        items=[TemplateResponse.model_validate(t) for t in items],
        total=len(items),
    )


# ── 详情 ──────────────────────────────────────────────

@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template_api(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取单个模板详情"""
    t = await get_template(db, template_id)
    if t is None:
        raise _not_found()
    return TemplateResponse.model_validate(t)


# ── 创建 ──────────────────────────────────────────────

@router.post("", response_model=TemplateResponse, status_code=201)
async def create_template_api(
    body: TemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    """手动创建模板"""
    data = body.model_dump(exclude_unset=True)
    t = await create_template(db, data)
    return TemplateResponse.model_validate(t)


# ── 更新 ──────────────────────────────────────────────

@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template_api(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新模板（部分更新）"""
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="请求体为空，请提供至少一个要更新的字段")
    t = await update_template(db, template_id, data)
    if t is None:
        raise _not_found()
    return TemplateResponse.model_validate(t)


# ── 删除 ──────────────────────────────────────────────

@router.delete("/{template_id}", status_code=204)
async def delete_template_api(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """删除模板"""
    ok = await delete_template(db, template_id)
    if not ok:
        raise _not_found()


# ── 样本生成 ──────────────────────────────────────────

@router.post("/from-sample")
async def from_sample_api(
    file: UploadFile = File(...),
    data_type: str = Form(..., description="数据类型: trial_balance / journal / subsidiary"),
    name: str | None = Form(None, description="模板名称"),
    save: bool = Form(False, description="是否直接保存"),
    db: AsyncSession = Depends(get_db),
):
    """从样本文件生成模板草稿（默认不保存，仅返回草稿）"""
    if data_type not in ("trial_balance", "journal", "subsidiary"):
        raise HTTPException(400, detail=f"不支持的数据类型: {data_type}")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(400, detail=f"不支持的文件格式: {ext}（仅支持 .xlsx .xls .csv）")

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"template_sample_{uuid.uuid4().hex}{ext}"

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        draft = await from_sample(str(temp_path), data_type, template_name=name)

        if save:
            # 从草稿提取可保存字段
            create_data = {
                "name": draft["name"],
                "data_type": draft["data_type"],
                "source_label": draft["source_label"],
                "is_active": False,
                "header_signature": draft["header_signature"],
                "parse_config": draft["parse_config"],
                "column_rules": draft["column_rules"],
                "default_values": draft["default_values"],
            }
            t = await create_template(db, create_data)
            return {"saved": True, "template": TemplateResponse.model_validate(t).model_dump(), **draft}
        else:
            draft["saved"] = False
            return draft
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("from_sample 异常")
        raise HTTPException(status_code=400, detail=f"生成模板草稿失败: {e}")
    finally:
        if temp_path.exists():
            temp_path.unlink()


# ── 测试 ──────────────────────────────────────────────

@router.post("/{template_id}/test", response_model=TemplateTestResult)
async def test_template_api(
    template_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """用文件测试模板套用效果"""
    template = await get_template(db, template_id)
    if template is None:
        raise _not_found()

    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(400, detail=f"不支持的文件格式: {ext}")

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"template_test_{uuid.uuid4().hex}{ext}"

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        result = await test_template(template, str(temp_path))
        return TemplateTestResult(**result)
    except Exception as e:
        logger.exception("test_template 异常")
        raise HTTPException(status_code=400, detail=f"模板测试失败: {e}")
    finally:
        if temp_path.exists():
            temp_path.unlink()
