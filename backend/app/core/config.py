"""应用配置"""

import os

from pydantic import model_validator
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
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # 桌面模式
    AUDIT_DESKTOP_MODE: bool = False
    AUDIT_DATA_DIR: str = ""
    AUDIT_PORT: int = 18000

    @model_validator(mode="after")
    def _apply_desktop_mode(self):
        if self.AUDIT_DESKTOP_MODE:
            data_dir = self.AUDIT_DATA_DIR
            if not data_dir:
                appdata = os.environ.get("APPDATA", "")
                if appdata:
                    data_dir = os.path.join(appdata, "审计系统")
                else:
                    data_dir = os.path.join(os.path.expanduser("~"), ".audit-system")
                object.__setattr__(self, "AUDIT_DATA_DIR", data_dir)
            db_path = os.path.join(data_dir, "audit.db")
            object.__setattr__(self, "DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
            object.__setattr__(self, "UPLOAD_DIR", os.path.join(data_dir, "uploads"))
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
