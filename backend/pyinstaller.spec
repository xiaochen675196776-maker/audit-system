# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格文件

将 FastAPI 后端打包为 onedir（目录模式），输出到 dist/audit-backend/。

关键配置：
- 入口脚本：desktop_entry.py
- 数据文件：alembic 迁移、内置种子数据
- 隐式导入：FastAPI/uvicorn/SQLAlchemy 的 asyncio 子模块
"""

import os
import sys
from pathlib import Path

# 后端根目录
_basedir = Path(os.path.dirname(os.path.abspath(__file__)))

# 需要打包的数据文件：(源路径, 目标相对路径)
_datas = []

# Alembic 迁移文件
_alembic_dir = _basedir / "alembic"
if _alembic_dir.is_dir():
    _datas.append((str(_alembic_dir), "alembic"))

# Alembic 配置文件
_alembic_ini = _basedir / "alembic.ini"
if _alembic_ini.is_file():
    _datas.append((str(_alembic_ini), "."))

# 内置种子数据
_app_data_dir = _basedir / "app" / "data"
if _app_data_dir.is_dir():
    _datas.append((str(_app_data_dir), "app/data"))

# 隐式导入模块列表
_hidden_imports = [
    # SQLAlchemy async
    "sqlalchemy.ext.asyncio",
    "aiosqlite",
    # uvicorn 子模块
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # pydantic
    "pydantic",
    # openpyxl (Excel 导入)
    "openpyxl",
    # pandas (数据处理)
    "pandas",
]

a = Analysis(
    ["desktop_entry.py"],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="audit-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="audit-backend",
)
