"""应用配置"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 应用
    APP_NAME: str = "审计系统基座"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # 数据库 — 默认 SQLite，生产切 PostgreSQL
    DATABASE_URL: str = "sqlite+aiosqlite:///./audit.db"

    # 文件上传
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 100

    # CORS（前端地址）
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
