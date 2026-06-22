"""FastAPI 应用入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import engine, Base
from app.core.schema import ensure_runtime_schema

# 导入所有模型，确保注册到 Base.metadata
import app.models  # noqa: F401

from app.api.health import router as health_router
from app.api.companies import router as companies_router
from app.api.imports import router as imports_router
from app.api.import_templates import router as templates_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时创建表，关闭时释放连接"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(ensure_runtime_schema)
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
app.include_router(templates_router, prefix="/api/v1")
