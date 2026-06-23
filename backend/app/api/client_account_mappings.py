"""客户科目映射经验 API — 推荐与保存"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.client_account_mapping_service import recommend_mappings, save_mapping
from app.schemas.standard_trial_balance import (
    ClientAccountMappingRecommendRequest,
    ClientAccountMappingRecommendResponse,
    ClientAccountMappingConfirmRequest,
    ClientAccountMappingConfirmResponse,
)

router = APIRouter(prefix="/client-account-mappings", tags=["客户科目映射经验"])


@router.post("/recommend", response_model=ClientAccountMappingRecommendResponse)
async def recommend(
    body: ClientAccountMappingRecommendRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    为客户科目列表推荐标准科目映射候选。

    优先级：
    1. 同一客户历史确认映射（company_history）
    2. 全局映射经验（global_history）
    3. 标准科目代码精确匹配（code_match）
    4. 标准科目名称相似度候选（name_similarity）

    停用标准科目：
    - 历史映射指向停用标准科目时，不自动套用，返回为 warning 候选。
    """
    client_accounts = [
        {
            "client_account_code": ac.client_account_code,
            "client_account_name": ac.client_account_name,
        }
        for ac in body.client_accounts
    ]

    items = await recommend_mappings(
        db=db,
        data_type=body.data_type,
        client_accounts=client_accounts,
        customer_label=body.customer_label,
        source_label=body.source_label,
    )

    return ClientAccountMappingRecommendResponse(items=items)


@router.post("/confirm", response_model=ClientAccountMappingConfirmResponse)
async def confirm(
    body: ClientAccountMappingConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    确认保存客户科目到标准科目的映射经验。

    - 同一客户科目已有相同标准科目映射：累加 usage_count
    - 同一客户科目已有不同标准科目映射：返回冲突信息（除非 allow_overwrite=True）
    - 全新映射：创建新记录
    """
    if not body.client_account_code and not body.client_account_name:
        raise HTTPException(
            status_code=400,
            detail="客户科目代码和名称至少提供一个",
        )

    result = await save_mapping(
        db=db,
        data_type=body.data_type,
        customer_label=body.customer_label,
        client_account_code=body.client_account_code,
        client_account_name=body.client_account_name,
        standard_account_id=body.standard_account_id,
        standard_account_code=body.standard_account_code,
        standard_account_name=body.standard_account_name,
        source=body.source,
        confidence=body.confidence,
        allow_overwrite=body.allow_overwrite,
    )

    return ClientAccountMappingConfirmResponse(**result)
