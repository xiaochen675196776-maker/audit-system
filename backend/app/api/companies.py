"""被审计单位管理 API"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.company import Company
from app.schemas.company import CompanyCreate, CompanyUpdate, CompanyResponse, CompanyListResponse

router = APIRouter(prefix="/companies", tags=["被审计单位管理"])


@router.get("", response_model=CompanyListResponse)
async def list_companies(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    keyword: str | None = Query(None, description="搜索关键词（名称/编码）"),
    db: AsyncSession = Depends(get_db),
):
    """获取被审计单位列表"""
    base_query = select(Company)
    count_query = select(func.count(Company.id))

    if keyword:
        like = f"%{keyword}%"
        filter_clause = Company.name.ilike(like) | Company.code.ilike(like)
        base_query = base_query.where(filter_clause)
        count_query = count_query.where(filter_clause)

    # 总数
    total = (await db.execute(count_query)).scalar() or 0

    # 分页
    offset = (page - 1) * page_size
    result = await db.execute(
        base_query.order_by(Company.created_at.desc()).offset(offset).limit(page_size)
    )
    items = result.scalars().all()

    return CompanyListResponse(
        items=[CompanyResponse.model_validate(item) for item in items],
        total=total,
    )


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取单个被审计单位"""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="被审计单位不存在")
    return CompanyResponse.model_validate(company)


@router.post("", response_model=CompanyResponse, status_code=201)
async def create_company(
    data: CompanyCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建被审计单位"""
    # 检查编码唯一性
    existing = await db.execute(select(Company).where(Company.code == data.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"公司编码 '{data.code}' 已存在")

    company = Company(**data.model_dump())
    db.add(company)
    await db.flush()
    await db.refresh(company)
    return CompanyResponse.model_validate(company)


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: uuid.UUID,
    data: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新被审计单位"""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="被审计单位不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(company, key, value)

    await db.flush()
    await db.refresh(company)
    return CompanyResponse.model_validate(company)


@router.delete("/{company_id}", status_code=204)
async def delete_company(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """删除被审计单位（级联删除关联数据）"""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="被审计单位不存在")

    await db.delete(company)
    await db.flush()
