"""数据导入 API"""

import uuid
import shutil
import traceback
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.services.import_service import preview_import, import_data

router = APIRouter(prefix="/imports", tags=["数据导入"])

settings = get_settings()
logger = logging.getLogger(__name__)


def _format_execute_error(e: Exception) -> dict:
    """将执行异常转为结构化中文错误，避免吐出原始 Python 异常字符串。"""
    msg = str(e)

    # 已知业务错误 → 直接翻译
    if "extra_fields" in msg and "invalid keyword argument" in msg:
        return {
            "message": "导入入库失败",
            "reason": "当前数据类型不支持自定义辅助字段，请减少辅助字段映射或等待系统升级支持",
            "suggestion": "请在字段映射步骤中将辅助字段列标记为「忽略此列」，或联系开发人员升级数据模型",
        }
    if "NOT NULL constraint failed" in msg:
        return {
            "message": "导入入库失败",
            "reason": "存在必填字段缺失，数据无法写入数据库",
            "suggestion": "请检查字段映射是否完整，确保所有必填列均已映射到正确的系统字段",
        }
    if "UNIQUE constraint failed" in msg:
        return {
            "message": "导入入库失败",
            "reason": "导入数据中存在重复记录，违反了数据库唯一性约束",
            "suggestion": "请检查文件中的重复行或重复的凭证号/科目组合",
        }
    if "FOREIGN KEY constraint failed" in msg:
        return {
            "message": "导入入库失败",
            "reason": "数据引用了不存在的单位或科目，外键关联失败",
            "suggestion": "请确认被审计单位已正确创建，且科目编码在系统中已存在",
        }

    # 未知异常 → 记录详细日志，返回用户友好的中文说明
    logger.error(f"导入执行异常: {type(e).__name__}: {msg}\n{traceback.format_exc()}")
    return {
        "message": "服务器处理导入数据时发生错误",
        "reason": "系统内部异常，详细原因已记录到服务端日志",
        "suggestion": "请查看服务端日志获取详细错误信息，或联系开发人员排查",
    }


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    data_type: str = Form(..., description="数据类型: trial_balance / journal / subsidiary"),
    template_id: str | None = Form(None, description="指定模板 ID，返回套用后的 column_mapping_v2 草稿"),
    db: AsyncSession = Depends(get_db),
):
    """
    预览导入：上传文件 → 返回表头识别结果和自动匹配。

    返回 matched（已匹配）、unmatched（未匹配）、missing（缺少的必填字段）、
    template_candidates（模板候选列表）、applied_mapping_v2（指定模板时）。
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

        result = await preview_import(
            str(temp_path), data_type,
            db=db, template_id=template_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    column_mapping: str | None = Form(None, description="JSON格式列映射 v1: {\"原始表头\": \"标准字段\"}"),
    column_mapping_v2: str | None = Form(None, description="JSON格式列映射 v2: {\"col_001\": \"标准字段\", ...}"),
    template_id: str | None = Form(None, description="模板 ID，用于应用 parse_config 和默认值"),
    fiscal_year: int | None = Form(None, description="会计年度（文件中无此列时手动指定）"),
    period: int | None = Form(None, description="会计期间（文件中无此列时手动指定）"),
):
    """
    执行导入：上传文件 + 确认映射 → 校验 → 入库。

    column_mapping_v2 为 JSON 字符串，key 为列 ID（col_001），value 为标准字段。
    若同时传了 column_mapping 和 column_mapping_v2，优先使用 v2。
    若不传任何映射则使用自动匹配。
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
        mapping_v2 = None

        if column_mapping_v2:
            try:
                mapping_v2 = json.loads(column_mapping_v2)
            except json.JSONDecodeError:
                raise HTTPException(400, detail="column_mapping_v2 JSON 格式无效，请检查是否为合法 JSON 对象")
        elif column_mapping:
            try:
                mapping = json.loads(column_mapping)
            except json.JSONDecodeError:
                raise HTTPException(400, detail="column_mapping JSON 格式无效，请检查是否为合法 JSON 对象")

        # 加载模板配置
        parse_config = None
        template_default_values = None
        if template_id:
            from app.services.template_service import get_template
            tmpl = await get_template(db, uuid.UUID(template_id))
            if tmpl:
                parse_config = tmpl.parse_config or None
                template_default_values = tmpl.default_values or None

        result = await import_data(
            db=db,
            company_id=cid,
            file_path=str(file_path),
            data_type=data_type,
            column_mapping=mapping,
            column_mapping_v2=mapping_v2,
            fiscal_year=fiscal_year,
            period=period,
            parse_config=parse_config,
            template_default_values=template_default_values,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=_format_execute_error(e))
