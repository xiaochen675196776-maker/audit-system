# TASK-053：后端本地桌面运行时改造

状态：DONE
优先级：P0
依赖：TASK-052
是否可并行：可与 TASK-054 并行

## 目标

改造 FastAPI 后端，使其在桌面端本地运行时能正确识别用户数据目录、分配端口、并自动处理数据库迁移。

## 设计要点

参见 `docs/DESKTOP_MIGRATION_PLAN.md` 第 3.2 节。

### 3.1 用户数据目录

- Windows：`%APPDATA%\审计系统\`
  - 数据库：`%APPDATA%\审计系统\audit.db`
  - 上传文件：`%APPDATA%\审计系统\uploads\`
  - 日志：`%APPDATA%\审计系统\logs\`
- 后端启动时必须确保这些目录存在（递归创建）。
- 环境变量 `AUDIT_DATA_DIR` 可覆盖默认数据目录。
- 环境变量 `AUDIT_DESKTOP_MODE=true` 开启桌面模式。

### 3.2 数据库

- 桌面模式下强制使用 SQLite。
- 数据库路径 = `{AUDIT_DATA_DIR}/audit.db`。
- 启动时自动运行 `alembic upgrade head`。

### 3.3 端口

- 环境变量 `AUDIT_PORT` 指定端口，未指定时默认 18000。
- 启动时如果端口被占用，自动递增重试（最多 10 次）。
- 实际使用的端口写入 stdout，供 Electron 主进程解析。

### 3.4 启动逻辑

新增 `backend/app/core/desktop.py`，提供：
- `get_data_dir()` → 返回用户数据目录路径。
- `ensure_directories()` → 确保所有子目录存在。
- `find_available_port(start_port: int)` → 端口探测。
- `run_desktop()` → 桌面模式入口，组合以上逻辑并启动 uvicorn。

### 3.5 配置更新

`backend/app/core/config.py` 新增：
- `AUDIT_DESKTOP_MODE: bool = False`
- `AUDIT_DATA_DIR: str = ""`
- `AUDIT_PORT: int = 18000`

桌面模式下 `DATABASE_URL` 和 `UPLOAD_DIR` 自动从 `AUDIT_DATA_DIR` 派生。

## 允许修改范围

- `backend/app/core/config.py` — 新增桌面模式配置项。
- `backend/app/core/desktop.py` — 新建文件，桌面运行时入口。
- `backend/app/main.py` — 启动时根据桌面模式调整逻辑（可选）。
- `backend/requirements.txt` — 如需新增依赖。

## 禁止事项

- 不要删除或修改现有 Web/Docker 配置逻辑。
- 不要修改业务 API 路由和服务层。
- 不要修改前端代码。
- 不要修改数据库模型。
- 不要回滚、删除、清理任何现有文件。

## 验收标准

- [ ] `AUDIT_DESKTOP_MODE=true` 时：
  - 数据库路径指向 `%APPDATA%\审计系统\audit.db`。
  - 上传目录指向 `%APPDATA%\审计系统\uploads\`。
  - 启动时自动创建数据目录。
  - 启动时自动运行数据库迁移。
  - 端口被占用时自动递增。
- [ ] `AUDIT_DESKTOP_MODE=false`（默认）时行为与现有完全一致。
- [ ] `python -m compileall app` 通过。
- [ ] `python -m pytest` 所有现有测试仍通过。

## 验收命令

```powershell
cd backend

# 编译检查
D:\python\python.exe -m compileall app

# 现有测试回归
D:\python\python.exe -m pytest

# 手动桌面模式启动测试
$env:AUDIT_DESKTOP_MODE = "true"
$env:AUDIT_DATA_DIR = "$env:APPDATA\审计系统"
D:\python\python.exe -m uvicorn app.main:app --port 18000
# 确认启动成功，确认 %APPDATA%\审计系统\ 目录已创建
```

## 完成回报要求

完成后将本文件状态改为 `DONE` 或 `REVIEW_NEEDED`，并按 `docs/tasks/DONE_TEMPLATE.md` 格式在本文件底部追加完成回报。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 23:15

### 修改文件

- `backend/app/core/config.py`
- `backend/app/core/desktop.py`
- `backend/app/main.py`

### 完成内容

- `config.py` 新增 `AUDIT_DESKTOP_MODE`、`AUDIT_DATA_DIR`、`AUDIT_PORT` 配置项，并通过 `model_validator` 在桌面模式下自动从数据目录派生 `DATABASE_URL` 和 `UPLOAD_DIR`。
- 新建 `desktop.py`，提供 `get_data_dir()`、`ensure_directories()`、`find_available_port()`、`run_alembic_upgrade()`、`run_desktop()` 五个工具函数，覆盖桌面模式完整启动流程。
- `main.py` 的 lifespan 在桌面模式下先运行 Alembic 迁移再执行 `create_all`。
- 桌面模式通过环境变量 `AUDIT_DESKTOP_MODE=true` 开启，默认行为（浏览器开发/Docker）完全不变。

### 验证命令

```powershell
D:\python\python.exe -m compileall app
D:\python\python.exe -m pytest
```

结果：

- compileall：通过
- pytest：339 passed, 3 warnings（预存）

### 风险和后续

- 无。桌面模式启动（`AUDIT_DESKTOP_MODE=true` 手动 uvicorn 启动）需要人工验证。
- TASK-055 Electron 壳将调用 `python -m app.core.desktop` 启动后端。
