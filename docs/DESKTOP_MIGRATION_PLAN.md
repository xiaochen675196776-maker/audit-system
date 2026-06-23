# 桌面端迁移设计方案

> 版本：v0.1.0（第一版设计）
> 设计日期：2026-06-22
> 关联任务：TASK-052 ~ TASK-057

## 1. 目标

将当前基于浏览器 + Docker 部署的审计系统迁移为 Windows 桌面端可本地运行的应用。

第一版里程碑：**Windows 本地可运行，不要求正式安装包。**

## 2. 设计原则

### 2.1 第一版不做

- 不做登录、注册、授权、多用户隔离。
- 不做云同步、自动更新、崩溃上报。
- 不做 macOS / Linux 适配（代码尽量通用，但不验证）。
- 不做正式安装包（.exe / .msi / 签名）。
- 不做系统托盘、开机自启、卸载程序。

### 2.2 技术栈保留

- **后端**：Python 3.12 + FastAPI + SQLAlchemy
- **前端**：Vue 3 + Element Plus + TypeScript
- **数据库**：SQLite（桌面端单机唯一数据库）

### 2.3 桌面壳选型

第一版采用 **Electron** 作为桌面壳，原因：
- 与 Vue 3 + Vite 生态兼容最好。
- 成熟稳定，社区庞大。
- 可以用 `electron-builder` 在后续版本生成安装包。

备选方案（第二版可评估）：
- Tauri（更小体积，Rust 运行时，当前团队不熟悉）
- PWA（无原生窗口控制）

### 2.4 Web/Docker 路线保留

- 现有 `npm run dev` + `uvicorn` 开发方式不受影响。
- `docker compose up -d` 继续可用。
- 桌面端只是一个新的运行方式，不替换任何现有代码路径。

## 3. 架构设计

### 3.1 桌面端运行时拓扑

```text
┌─────────────────────────────────────────┐
│              Electron Shell             │
│                                         │
│  ┌──────────────┐  ┌─────────────────┐  │
│  │  BrowserView  │  │   Main Process  │  │
│  │  (Vue 前端)   │  │                 │  │
│  │              │  │  - 启动 FastAPI  │  │
│  │  localhost:   │  │  - 生命周期管理  │  │
│  │    5173      │  │  - 窗口管理      │  │
│  └──────┬───────┘  │  - 原生对话框    │  │
│         │          └────────┬────────┘  │
│         │ API 请求           │ spawn     │
│         │ /api/v1/*          │           │
│         ▼                    ▼           │
│  ┌─────────────────────────────────────┐ │
│  │        FastAPI 后端进程              │ │
│  │        localhost:{{port}}            │ │
│  │        SQLite 数据库                 │ │
│  └─────────────────────────────────────┘ │
│                                         │
│  用户数据目录（%APPDATA%/审计系统/）      │
│  ├── audit.db                           │
│  ├── uploads/                           │
│  └── logs/                              │
└─────────────────────────────────────────┘
```

### 3.2 关键决策

#### 3.2.1 用户数据目录

所有运行时数据必须放在用户可写目录，**禁止写入安装目录**。

Windows 路径约定：

| 数据类型 | 路径 | 说明 |
| --- | --- | --- |
| SQLite 数据库 | `%APPDATA%\审计系统\audit.db` | 主数据库 |
| 上传文件 | `%APPDATA%\审计系统\uploads\` | 用户导入的 Excel/CSV |
| 日志 | `%APPDATA%\审计系统\logs\` | 后端日志 |
| 配置 | `%APPDATA%\审计系统\.env` | 可选用户配置覆盖 |

Electron 主进程负责在启动时确保这些目录存在，并将路径通过环境变量或命令行参数传递给 FastAPI 后端进程。

#### 3.2.2 后端端口分配

FastAPI 后端在本地运行，端口策略：

- **默认端口**：从 18000 开始尝试，被占用则递增（18000 → 18001 → …）。
- Electron 主进程找到一个可用端口后，将其传给 FastAPI 子进程和前端 Vite dev server。
- 前端 `baseURL` 根据实际端口动态设置（见 TASK-054）。

#### 3.2.3 前端运行方式

第一版桌面端，前端有两种可选策略：

**策略 A（推荐第一版）：Vite dev server 内嵌**

- Electron 主进程启动 Vite dev server（`npx vite --port 5173`）。
- Electron BrowserWindow 加载 `http://localhost:5173`。
- 利用 Vite proxy 转发 API 到 FastAPI。
- 优点：开发体验一致，HMR 可用。
- 缺点：首次启动稍慢（Vite 预构建），生产环境不合适。

**策略 B（后续版本）：Vite build 产物 + Electron 静态托管**

- `npm run build` 产出 `dist/`。
- Electron 主进程用 `express` 或内置 scheme 托管静态文件。
- 优点：启动快，无 Vite 依赖。
- 缺点：无 HMR，需额外处理路由 history mode。

**第一版采用策略 A**，后续版本迁移到策略 B。

#### 3.2.4 API 基地址切换

当前前端 `baseURL: '/api/v1'` 依赖 Vite proxy 转发。桌面端有两种方案：

- **方案 1**：继续用 Vite proxy — 简单，零改动。
- **方案 2**：前端改为绝对 URL `http://localhost:18000/api/v1` — 需要动态获取端口。

第一版采用方案 1，利用 Vite proxy；后续生产构建再用方案 2。

### 3.3 数据库迁移策略

- 桌面端继续使用 Alembic 管理迁移。
- FastAPI 启动时自动运行 `alembic upgrade head`。
- SQLite 兼容性：现有模型需确认无 PostgreSQL 专有语法（如 `ARRAY`、`JSONB`）。

## 4. 任务拆分

| 任务 | 说明 | 依赖 |
| --- | --- | --- |
| TASK-052 | 本设计文档 + 任务登记 | 无 |
| TASK-053 | 后端本地桌面运行时改造（数据目录、端口、启动逻辑） | TASK-052 |
| TASK-054 | 前端运行时 API 基地址动态化 | TASK-052，可与 TASK-053 并行 |
| TASK-055 | Electron 壳 MVP（主进程、窗口、生命周期） | TASK-053, TASK-054 |
| TASK-056 | 后端 PyInstaller 打包为可执行文件 | TASK-053 |
| TASK-057 | 桌面端整体验收 | TASK-055, TASK-056 |

## 5. 风险与未决事项

1. **SQLite 并发**：SQLAlchemy + aiosqlite 在单用户场景下足够，但需确认现有代码无 PostgreSQL 专有语法。
2. **PyInstaller 体积**：Python + FastAPI + 依赖打包后可能较大（100MB+），第一版可接受。
3. **Electron 体积**：Electron 本身约 150MB+，第一版可接受。
4. **端口冲突**：18000 端口可能被占用，需实现端口探测逻辑。
5. **杀毒软件误报**：PyInstaller 打包产物可能被误报，需在设计中说明。

## 6. 后续版本规划（不在本轮范围）

- 策略 B：Vite build + 静态托管。
- electron-builder 生成 Windows 安装包。
- 自动更新（electron-updater）。
- macOS / Linux 适配。
- 系统托盘与后台运行。
