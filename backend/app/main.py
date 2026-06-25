"""FastAPI 应用入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import engine, Base, async_session_factory
from app.core.schema import ensure_runtime_schema

# 导入所有模型，确保注册到 Base.metadata
import app.models  # noqa: F401

from app.api.health import router as health_router
from app.api.companies import router as companies_router
from app.api.imports import router as imports_router
from app.api.client_account_mappings import router as client_account_mappings_router
from app.api.standard_accounts import router as standard_accounts_router
from app.api.standard_trial_balances import router as standard_trial_balances_router
from app.api.standard_trial_balance_imports import router as standard_trial_balance_imports_router
from app.services.standard_account_service import seed_standard_accounts

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时创建表，初始化内置标准科目，关闭时释放连接

    桌面模式下的 Alembic 迁移在 app.core.desktop.run_desktop() 启动 uvicorn 前执行，
    此处只负责 create_all（幂等）和种子数据初始化。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(ensure_runtime_schema)
    # 初始化内置标准科目主数据
    async with async_session_factory() as session:
        await seed_standard_accounts(session)
        await session.commit()
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health_router, prefix="/api/v1")
app.include_router(companies_router, prefix="/api/v1")
app.include_router(imports_router, prefix="/api/v1")
app.include_router(client_account_mappings_router, prefix="/api/v1")
app.include_router(standard_accounts_router, prefix="/api/v1")
app.include_router(standard_trial_balances_router, prefix="/api/v1")
app.include_router(standard_trial_balance_imports_router, prefix="/api/v1")
