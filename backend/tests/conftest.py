"""pytest 配置和共享 fixture"""

import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.database import Base

# 模块级引擎（内存数据库，所有测试共享，不留文件）
_engine = create_async_engine("sqlite+aiosqlite://", echo=False)


@pytest.fixture
async def db() -> AsyncSession:
    """每个测试独立的数据库会话（自动建表 + 回滚）"""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session() as session:
        yield session
        await session.rollback()

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def sample_company_id() -> uuid.UUID:
    """测试用公司 ID"""
    return uuid.UUID("a0000000-0000-0000-0000-000000000001")
