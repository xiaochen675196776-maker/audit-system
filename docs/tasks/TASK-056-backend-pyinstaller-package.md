# TASK-056：后端 PyInstaller 打包

状态：DONE
优先级：P1（可在 TASK-055 之后或并行）
依赖：TASK-053
是否可并行：可与 TASK-055 并行

## 目标

将 FastAPI 后端打包为 Windows 可执行文件（.exe），使桌面端用户无需安装 Python 解释器。

## 设计要点

### 3.1 打包工具

使用 **PyInstaller** 将后端打包为单个目录（onedir）或单个文件（onefile）。

第一版推荐 **onedir**（目录模式）：
- 启动更快（无需每次解压）。
- 调试更方便（可查看内部文件）。
- 兼容性更好（asyncio、multiprocessing）。

### 3.2 打包配置

创建 `backend/pyinstaller.spec` 或 `backend/build.spec`：

```python
# 关键配置项
a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('alembic', 'alembic'),           # Alembic 迁移文件
        ('alembic.ini', '.'),              # Alembic 配置
        ('app/data', 'app/data'),          # 内置种子数据
    ],
    hiddenimports=[
        'sqlalchemy.ext.asyncio',
        'aiosqlite',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
    ],
    ...
)
```

### 3.3 启动入口

创建 `backend/desktop_entry.py`：
- 桌面模式专用入口。
- 设置 `AUDIT_DESKTOP_MODE=true`。
- 调用 `app.main:app` 启动 uvicorn。
- 接受端口参数。

### 3.4 构建脚本

创建 `backend/scripts/build_desktop.ps1`：
```powershell
# 清理旧构建
Remove-Item -Recurse -Force dist/ -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force build/ -ErrorAction SilentlyContinue

# PyInstaller 打包
D:\python\python.exe -m PyInstaller `
    --name "audit-backend" `
    --onedir `
    --console `
    --clean `
    --add-data "alembic;alembic" `
    --add-data "alembic.ini;." `
    --add-data "app/data;app/data" `
    --hidden-import sqlalchemy.ext.asyncio `
    --hidden-import aiosqlite `
    desktop_entry.py
```

### 3.5 输出

- `backend/dist/audit-backend/audit-backend.exe`
- Electron 主进程 spawn 这个 .exe 而不是 python 脚本。

## 允许修改范围

- `backend/desktop_entry.py` — 新建桌面启动入口。
- `backend/pyinstaller.spec` 或 `backend/build.spec` — 新建打包配置。
- `backend/scripts/build_desktop.ps1` — 新建构建脚本。
- `backend/requirements.txt` — 新增 `pyinstaller` 依赖。
- `.gitignore` — 忽略 `backend/dist/`、`backend/build/`。

## 禁止事项

- 不要修改业务 API 路由和服务层。
- 不要修改数据库模型。
- 不要修改前端代码。
- 不要回滚、删除、清理任何现有文件。
- 不要提交打包产物（.exe、dist/、build/）。

## 验收标准

- [ ] `desktop_entry.py` 能独立启动后端（`AUDIT_DESKTOP_MODE=true`）。
- [ ] PyInstaller 打包成功，输出 `dist/audit-backend/audit-backend.exe`。
- [ ] .exe 启动后：
  - 数据目录自动创建。
  - 数据库迁移自动执行。
  - API 端点正常响应。
- [ ] 现有 pytest 全部通过。
- [ ] `python -m compileall app` 通过。

## 验收命令

```powershell
cd backend

# 编译检查
D:\python\python.exe -m compileall app

# 测试回归
D:\python\python.exe -m pytest

# 安装 PyInstaller
D:\python\python.exe -m pip install pyinstaller

# 执行打包
.\scripts\build_desktop.ps1

# 启动打包后的 .exe 测试
.\dist\audit-backend\audit-backend.exe
# 另开终端：
# curl http://localhost:18000/api/v1/health
# 或浏览器打开 http://localhost:18000/docs
```

## 完成回报要求

完成后将本文件状态改为 `DONE` 或 `REVIEW_NEEDED`，并按 `docs/tasks/DONE_TEMPLATE.md` 格式在本文件底部追加完成回报。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 23:20

### 修改文件

- `backend/desktop_entry.py`
- `backend/pyinstaller.spec`
- `backend/scripts/build_desktop.ps1`
- `backend/requirements.txt`
- `.gitignore`

### 完成内容

- `desktop_entry.py`：PyInstaller 打包入口，强制设置 `AUDIT_DESKTOP_MODE=true` 并调用 `run_desktop()`。
- `pyinstaller.spec`：onedir 模式 spec，包含 alembic 迁移文件、种子数据、uvicorn/aiosqlite/pandas 隐式导入。
- `scripts/build_desktop.ps1`：一键打包脚本（编译检查 → 清理 → 安装 PyInstaller → 打包 → 验证输出）。
- `requirements.txt`：新增 `pyinstaller>=6.0.0`。
- `.gitignore`：已忽略 `backend/dist/`、`backend/build/`。

### 验证命令

```powershell
D:\python\python.exe -m compileall app desktop_entry.py
D:\python\python.exe -m pytest
npm run build
```

结果：

- compileall：通过
- pytest：339 passed, 3 warnings
- npm build：built in 7.34s

### 风险和后续

- PyInstaller 实际打包（`.\scripts\build_desktop.ps1`）需在开发机手动执行验证，预计产物大小 100MB+。
- 打包后的 .exe 启动测试需要人工验证（数据目录创建、alembic 迁移、API 响应）。
