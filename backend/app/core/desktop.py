"""桌面运行时工具模块

提供桌面模式下所需的目录管理、端口探测和启动入口。
"""

import os
import socket
import sys
import logging

logger = logging.getLogger(__name__)


def get_data_dir() -> str:
    """返回用户数据目录路径。

    优先使用环境变量 AUDIT_DATA_DIR，否则使用系统默认路径。
    Windows: %APPDATA%\\审计系统
    其他: ~/.audit-system
    """
    data_dir = os.environ.get("AUDIT_DATA_DIR", "")
    if data_dir:
        return data_dir
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return os.path.join(appdata, "审计系统")
    return os.path.join(os.path.expanduser("~"), ".audit-system")


def ensure_directories(data_dir: str | None = None) -> str:
    """确保数据目录及子目录存在，返回实际数据目录路径。

    创建以下子目录：
    - {data_dir}/uploads  上传文件
    - {data_dir}/logs     日志
    """
    if data_dir is None:
        data_dir = get_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "uploads"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)
    return data_dir


def find_available_port(start_port: int = 18000, max_attempts: int = 10) -> int:
    """从 start_port 开始查找可用端口，最多尝试 max_attempts 次。

    返回第一个可用的端口号。
    如果全部被占用，抛出 RuntimeError。
    """
    for offset in range(max_attempts):
        port = start_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"无法找到可用端口：{start_port}–{start_port + max_attempts - 1} 均被占用"
    )


def run_alembic_upgrade() -> None:
    """运行 Alembic 数据库迁移到最新版本。"""
    import os as _os
    from alembic.config import Config as AlembicConfig
    from alembic import command

    # 清除缓存的配置以使用最新的 DATABASE_URL
    from app.core.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()

    # alembic.ini 路径：backend/alembic.ini
    alembic_ini = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
        "alembic.ini",
    )
    if not _os.path.exists(alembic_ini):
        logger.warning("alembic.ini not found at %s, skipping migration", alembic_ini)
        return

    alembic_cfg = AlembicConfig(alembic_ini)
    alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic upgrade completed")


def run_desktop() -> None:
    """桌面模式启动入口。

    执行完整启动流程：
    1. 查找可用端口
    2. 确保数据目录存在
    3. 运行数据库迁移
    4. 启动 uvicorn
    """
    import uvicorn

    # 读取环境变量 AUDIT_PORT 作为起始端口
    start_port = int(os.environ.get("AUDIT_PORT", "18000"))
    port = find_available_port(start_port)
    data_dir = ensure_directories()

    # 环境变量会覆盖 config.py 的默认值
    os.environ["AUDIT_DESKTOP_MODE"] = "true"
    os.environ["AUDIT_PORT"] = str(port)
    os.environ["AUDIT_DATA_DIR"] = data_dir

    # 输出端口号供 Electron 主进程解析
    print(f"AUDIT_PORT={port}", flush=True)
    print(f"AUDIT_DATA_DIR={data_dir}", flush=True)

    # 清除缓存的配置，使其重新读取环境变量
    from app.core.config import get_settings
    get_settings.cache_clear()

    # 运行数据库迁移
    run_alembic_upgrade()

    # 启动 uvicorn
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    run_desktop()
