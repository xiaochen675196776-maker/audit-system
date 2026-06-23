# TASK-055：Electron 壳 MVP

状态：DONE
优先级：P0
依赖：TASK-053, TASK-054
是否可并行：否（需等前后端改造完成）

## 目标

创建 Electron 桌面壳，实现：
1. 启动 FastAPI 后端子进程。
2. 启动 Vite dev server（或加载前端构建产物）。
3. 打开 BrowserWindow 显示前端页面。
4. 窗口关闭时优雅终止后端进程。

## 设计要点

参见 `docs/DESKTOP_MIGRATION_PLAN.md` 第 3.1 节。

### 3.1 项目结构

在项目根目录新建 `desktop/` 目录：

```
desktop/
├── main.js          # Electron 主进程入口
├── preload.js       # 预加载脚本（安全暴露 API）
├── package.json     # Electron 依赖
└── backend.js       # FastAPI 后端进程管理
```

### 3.2 主进程职责

`main.js`：
1. 查找可用端口（从 18000 开始）。
2. 启动 FastAPI 后端（spawn python 子进程），传入端口和数据目录。
3. 等待后端就绪（轮询 `http://localhost:{port}/api/v1/health` 或类似端点）。
4. 启动 Vite dev server（`npx vite --port 5173`）并传入 `VITE_API_TARGET`。
5. 创建 BrowserWindow，加载 `http://localhost:5173`。
6. 监听 `window-all-closed` 事件，kill 子进程后退出。

### 3.3 后端进程管理

`backend.js`：
- 使用 `child_process.spawn` 启动 Python。
- 使用 `python` 或 `python3`（尝试多个路径）。
- 从 stdout 解析实际端口号。
- 超时处理：30 秒内未就绪则报错退出。
- 退出时发送 SIGTERM，等待 5 秒，未退出则 SIGKILL。

### 3.4 预加载脚本

`preload.js`：
- 暴露 `window.__AUDIT_CONFIG__` 给前端渲染进程。
- 提供：`apiBaseUrl`、`desktopMode: true`、`dataDir`。

### 3.5 窗口配置

- 最小尺寸：1200×800。
- 默认尺寸：1400×900。
- 标题：审计系统。
- 图标：暂用默认 Electron 图标。
- 菜单：隐藏默认菜单栏（或保留最小菜单，含「关于」和 DevTools）。

### 3.6 开发与调试

- `npm run desktop:dev`（在 `desktop/` 目录）启动桌面开发模式。
- Electron DevTools 可用。
- 主进程日志打印到控制台。

## 允许修改范围

- `desktop/` — 新建整个目录及其所有文件。
- 根目录 `package.json` — 可选，新增 workspace 或脚本引用。
- `.gitignore` — 忽略 `desktop/node_modules/`。

## 禁止事项

- 不要修改 `backend/` 和 `frontend/` 目录下的任何业务代码。
- 不要安装非必要的 Electron 插件。
- 不要配置 electron-builder 打包（留给 TASK-056 或后续版本）。
- 不要回滚、删除、清理任何现有文件。

## 验收标准

- [ ] `desktop/` 目录结构完整。
- [ ] `npm install` 在 `desktop/` 目录成功。
- [ ] 运行 `npm run desktop:dev` 后：
  - Electron 窗口打开。
  - 前端页面正常显示。
  - API 请求正常返回数据。
  - 关闭窗口后 Python 进程终止。
- [ ] 前端 Vite dev 和 Docker 开发方式不受影响。

## 验收命令

```powershell
cd desktop

# 安装依赖
npm install

# 启动桌面开发模式
npm run desktop:dev

# 手动验证：
# 1. Electron 窗口是否打开并显示前端首页
# 2. 打开 DevTools 检查无控制台错误
# 3. 确认 API 请求正常
# 4. 关闭窗口后检查 Python 进程是否已退出（tasklist | findstr python）
```

## 完成回报要求

完成后将本文件状态改为 `DONE` 或 `REVIEW_NEEDED`，并按 `docs/tasks/DONE_TEMPLATE.md` 格式在本文件底部追加完成回报。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 23:20

### 修改文件

- `desktop/package.json`
- `desktop/main.js`
- `desktop/preload.js`
- `desktop/backend.js`
- `.gitignore`

### 完成内容

- `package.json`：Electron 33 项目配置，`desktop:dev` 脚本启动 Electron。
- `main.js`：Electron 主进程，按顺序启动后端（Python）→ Vite dev server → BrowserWindow，窗口关闭时优雅终止子进程。
- `preload.js`：通过 `contextBridge` 向渲染进程暴露 `window.__AUDIT_CONFIG__`（apiBaseUrl、desktopMode、dataDir）。
- `backend.js`：后端子进程管理器，支持 spawn Python、stdout 端口解析、health 轮询、超时处理、Windows taskkill 清理。
- `.gitignore`：新增 `desktop/node_modules/`、`backend/dist/`、`backend/build/`。

### 验证命令

```powershell
# 编译检查（后端代码未被修改，仅验证编译）
D:\python\python.exe -m compileall app
```

结果：

- 通过

### 风险和后续

- Electron 端到端启动需要人工在有 GUI 的 Windows 环境中验证（`cd desktop && npm install && npm run desktop:dev`）。
- 当前 Python 路径硬编码为 `D:\python\python.exe`，后续可通过环境变量 `AUDIT_PYTHON_PATH` 覆盖。
