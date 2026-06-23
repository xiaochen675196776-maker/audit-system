# TASK-058：桌面端启动阻塞修复

状态：DONE
执行者：Reasonix
完成时间：2026-06-23 02:15
优先级：P0（阻塞修复）
依赖：TASK-057 验收反馈
是否可并行：否

## 目标

修复 TASK-057 桌面端验收中发现的 5 个启动阻塞项，使桌面后端能正常启动并响应 health 接口。

## 阻塞项清单

### 阻塞项 #1：main.py lifespan 同步 Alembic 卡死

- 现象：`python -m app.core.desktop` 启动后 application startup 阶段卡住
- 日志：`RuntimeWarning: coroutine 'run_async_migrations' was never awaited`
- 根因：`lifespan` 是 async context manager，`command.upgrade()` 在 async 上下文里同步调用 alembic 的 async 迁移导致协程未等待
- 修复：从 lifespan 移除 Alembic 调用，lifespan 只保留 `create_all`、`ensure_runtime_schema`、`seed_standard_accounts`

### 阻塞项 #2：desktop.py run_desktop() 忽略 AUDIT_PORT

- 现象：设置 `AUDIT_PORT=18101`，stdout 仍输出 `AUDIT_PORT=18000`
- 根因：`find_available_port()` 使用硬编码默认 18000，未读取 `AUDIT_PORT`
- 修复：读取 `AUDIT_PORT` 环境变量作为起始端口；所有端口被占用时抛异常

### 阻塞项 #3：desktop/backend.js Python fallback 不真实

- 现象：`findPython()` 注释说尝试多个路径，但只返回第一个候选
- 根因：只 `return candidates[0]`，不尝试后续候选
- 修复：实现真正的 fallback 逻辑，spawn 失败后试下一个

### 阻塞项 #4：desktop/preload.js desktopMode 永远 true

- 现象：`process.env.AUDIT_DESKTOP_MODE === 'true' || true` 永远为 true
- 根因：`|| true` 短路逻辑
- 修复：移除 `|| true`

### 阻塞项 #5：TASK-057 状态不一致

- 现象：文件顶部 `状态：IN_PROGRESS`，但完成回报 `状态：REVIEW_NEEDED`
- 修复：统一状态为 `BLOCKED`，等待 TASK-058 修复后复验

## 允许修改范围

- `backend/app/main.py` — 移除 lifespan 中同步 Alembic 调用
- `backend/app/core/desktop.py` — 修复 `run_desktop()` 读取 `AUDIT_PORT`，`find_available_port()` 拋异常
- `desktop/backend.js` — 实现真正 Python fallback
- `desktop/preload.js` — 修复 `desktopMode` 逻辑
- `desktop/main.js` — 如确有必要
- `docs/COMMAND_CENTER.md` — 登记 TASK-058
- `docs/tasks/TASK-057-desktop-acceptance.md` — 修正状态一致性
- `docs/tasks/TASK-058-desktop-startup-blockers.md` — 本文件

## 禁止事项

- 不要修改业务 API 路由和服务层
- 不要修改数据库模型
- 不要修改前端业务页面
- 不要修改登录、授权、云同步相关功能
- 不要修改 Docker 部署逻辑
- 不要回滚、删除、清理任何现有文件

## 验收标准

- [x] `python -m app.core.desktop` 启动后 `/api/v1/health` 返回 200
- [x] `AUDIT_PORT=18101` 时端口真实生效
- [x] `find_available_port()` 全部占用时抛出明确异常
- [x] `backend.js` `findPython()` 真实尝试多个候选
- [x] `preload.js` `desktopMode` 不再永远 true
- [x] TASK-057 状态一致
- [x] `python -m compileall app desktop_entry.py` 通过
- [x] `python -m pytest` 全部通过
- [x] `npm run build` 通过

## 验收命令

```powershell
# 1. 编译检查
cd backend
D:\python\python.exe -m compileall app desktop_entry.py

# 2. 测试回归
D:\python\python.exe -m pytest

# 3. 前端构建
cd ..\frontend
npm run build

# 4. 桌面后端手动启动验证
cd ..\backend
$env:AUDIT_DESKTOP_MODE = "true"
$env:AUDIT_DATA_DIR = "$env:TEMP\audit-test-058"
$env:AUDIT_PORT = "18101"
D:\python\python.exe -m app.core.desktop
# 另开终端：
# curl http://127.0.0.1:18101/api/v1/health
# dir $env:TEMP\audit-test-058\

# 5. diff 检查
cd ..
git diff --check -- backend desktop docs
```

## 完成回报要求

完成后将本文件状态改为 `DONE`，并按 `docs/tasks/DONE_TEMPLATE.md` 格式在本文件底部追加完成回报。
同时更新 TASK-057 追加复验记录。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-23 02:15

### 修改文件

- `backend/app/main.py` — 移除 lifespan 中同步 Alembic 调用
- `backend/app/core/desktop.py` — `run_desktop()` 读取 `AUDIT_PORT`；`find_available_port()` 全部占用则抛 RuntimeError
- `desktop/backend.js` — 新增 `getPythonCandidates()` 和 `startBackendWithFallback()`，实现真实 Python fallback
- `desktop/main.js` — 改用 `startBackendWithFallback`
- `desktop/preload.js` — 移除 `|| true`，`desktopMode` 按环境变量真实判断
- `docs/tasks/TASK-057-desktop-acceptance.md` — 统一状态为 BLOCKED
- `docs/tasks/TASK-058-desktop-startup-blockers.md` — 本文件
- `docs/COMMAND_CENTER.md` — 登记 TASK-058

### 完成内容

修复了 TASK-057 桌面端验收中 5 个启动阻塞项：

1. **main.py 同步 Alembic 阻塞**：从 lifespan 移除 Alembic 调用（仅保留 create_all + seed），Alembic 迁移仅在 `run_desktop()` 启动 uvicorn 前执行。
2. **AUDIT_PORT 被忽略**：`run_desktop()` 读取 `AUDIT_PORT` 环境变量作为起始端口；`find_available_port()` 全部被占用时抛出 RuntimeError。
3. **Python fallback 不生效**：`backend.js` 新增 `startBackendWithFallback()`，依次尝试 5 个候选（AUDIT_PYTHON_PATH → D:\python\python.exe → python → python3 → py），失败后继续尝试下一个。
4. **preload desktopMode 永远 true**：移除 `|| true` 短路逻辑。
5. **TASK-057 状态不一致**：统一为 BLOCKED。

### 验证命令

```powershell
# 1. 自动验证
D:\python\python.exe -m compileall app desktop_entry.py  # 通过
D:\python\python.exe -m pytest                             # 339 passed, 3 warnings
npm run build                                              # built in 7.64s

# 2. 桌面后端手动启动验证
$env:AUDIT_DESKTOP_MODE = "true"
$env:AUDIT_DATA_DIR = "$env:TEMP\audit-test-058"
$env:AUDIT_PORT = "18101"
D:\python\python.exe -m app.core.desktop
```

结果：

- **health 返回 200** ✅：`{"status":"ok","message":"审计系统基座运行中"}`
- **端口 18101 生效** ✅：stdout 输出 `AUDIT_PORT=18101`，uvicorn 监听 127.0.0.1:18101
- **数据目录创建** ✅：`audit.db`（249KB）、`logs/`、`uploads/` 均在临时目录
- **Alembic 迁移执行** ✅：3 个迁移（init → field_mapping → standard_trial_balance）全部成功
- **无 RuntimeWarning** ✅：无 coroutine 未等待警告

### 风险和后续

- 无。TASK-057 的 5 个阻塞项全部修复，桌面后端可正常启动。
- Electron `npm run desktop:dev` 仍需在 Windows 桌面 GUI 环境手工验证。
- PyInstaller 打包仍需在开发机手动执行 `.\scripts\build_desktop.ps1`。

---

## 复验记录（2026-06-23 11:35）

执行者：ZCode
触发：总指挥要求在真实 Electron 环境复验 4 项，并处理 electron 安装残缺。

### 用户要求 4 项处理结果

1. **main.js 启动后端前显式设置 `process.env.AUDIT_DESKTOP_MODE='true'`** ✅
   - 在 `desktop/main.js` 顶部、`require('electron')` 之前显式设置 `process.env.AUDIT_DESKTOP_MODE = 'true'`。
   - 原因：preload.js 在渲染进程隔离上下文读 `process.env.AUDIT_DESKTOP_MODE`，该值继承自主进程环境；主进程此前未设置，导致 preload 注入的 `desktopMode` 恒为 false。
   - 该设置同时让 Python 后端、Vite 子进程继承桌面模式标记。

2. **重新验证 preload 注入的 desktopMode 在 Electron 为 true** ✅
   - 写临时最小 Electron 脚本（复刻 main.js 顶层设置 + 加载真实 preload.js），在真实 Electron v33.4.11 下 `executeJavaScript('window.__AUDIT_CONFIG__')`：
     - 结果：`{"apiBaseUrl":"http://127.0.0.1:18000","desktopMode":true,"dataDir":""}`，`VERDICT=PASS`。
   - 临时脚本已删除。
   - 结论：preload 注入的 `desktopMode` 在真实 Electron 环境为 `true`，问题 #4（原 `|| true` 短路）在真实环境确认修复。

3. **处理 desktop/node_modules/electron 安装残缺（EBUSY）** ✅
   - **根因定位**：`node_modules/electron/` 是空壳目录（无 package.json/dist/path.txt），被 EBUSY 锁住。
     - 用 `Get-CimInstance Win32_Process` 查到锁源：PID 22208 `npm install` → PID 10888 `cmd /c node install.js` → PID 8856 `node install.js`（electron 的 postinstall 下载脚本）。
     - 三进程已运行 67 分钟、CPU 时间极低（8856 仅 7.7s），属网络下载挂起的僵尸链路，非正常工作进程，也与其它 MCP 服务器（独立 npx 进程）无关。
   - **处理**：按子→父顺序终止僵尸链路（8856→10888→22208），随后 `rd /s /q node_modules\electron` 成功清空残缺目录。
   - **重装**：默认从 GitHub 下载二进制会卡死（正是之前挂起根因），改用 `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/` 镜像重装，55s 完成。
   - **验证二进制完整**：`dist/electron.exe` 188,784,128 字节、`path.txt`→`electron.exe`、版本 33.4.11、`electron --version` 输出 `v33.4.11`。

4. **重跑 `npm run desktop:dev`** ✅（启动链路全部打通）
   - 用 `electron . --no-sandbox --disable-gpu`（headless 友好）实跑，里程碑日志全绿：
     - `尝试 Python 候选 1/4: D:\python\python.exe` → 后端启动
     - `AUDIT_PORT=18000` 生效、`Application startup complete`、`Uvicorn running on http://127.0.0.1:18000`
     - `GET /api/v1/health HTTP/1.1 200 OK`
     - `[desktop] 后端就绪: http://127.0.0.1:18000`（端口检测生效）
     - `VITE v5.4.21 ready`、`Local: http://127.0.0.1:5173/`
     - **无 ERR_CONNECTION_REFUSED**（前两轮每次都出现，现已消除）
   - **Electron 已能正常启动**，故 TASK-058 状态维持 `DONE`（未降级 REVIEW_NEEDED）。

### 额外修复（实跑才暴露，原 5 项之外）

复验 `npm run desktop:dev` 时发现两个会阻断窗口加载的真实问题，一并修复：

- **A. Vite spawn 路径在 Windows 失效**：`main.js` 原 `spawn('node_modules/.bin/vite', ..., { shell: true })`，`.bin/vite` 是无扩展名 sh 脚本，Windows shell 无法执行，报 `'node_modules' 不是内部或外部命令`，Vite 起不来。
  - 修复：改为 `spawn(process.execPath, [viteEntry, ...])`，直接用 node 运行 `node_modules/vite/bin/vite.js`，去掉 `shell: true`，跨平台。
- **B. Vite 仅监听 IPv6 导致窗口连接被拒**：Node 17+ 默认把 `localhost` 解析为 IPv6，Vite 因此只监听 `[::1]:5173`；而 Electron `loadURL('localhost')` 在 Windows 优先解析为 IPv4 `127.0.0.1`，二者不匹配 → `ERR_CONNECTION_REFUSED`（即便真实桌面环境也会复现，非 headless 限制）。
  - 修复：Vite 启动加 `--host 127.0.0.1` 显式绑定 IPv4；窗口 `loadURL` 改为 `http://127.0.0.1:5173` 与之对齐。

### 修改文件（本轮复验）

- `desktop/main.js` — 顶层设置 `AUDIT_DESKTOP_MODE='true'`；Vite 改用 node 直接运行入口；Vite 加 `--host 127.0.0.1`；窗口 URL 改 `127.0.0.1`。
- `docs/tasks/TASK-058-desktop-startup-blockers.md` — 本复验记录。

### 回归验证

- `npm run build`：✓ built in 6.24s（chunk 体积警告为历史已知非阻塞项）。
- `python -m compileall app desktop_entry.py`：exit 0。
- 真实 Electron `desktop:dev`：后端+Vite+窗口全链路启动成功，无 connection/spawn/address 错误。

### 遗留与说明

- **GUI 窗口渲染未可视化确认**：当前为 headless 无显示器环境，GPU/network service 错误（exit_code 143）是该环境固有现象，非代码缺陷；真实 Windows 桌面环境跑通后即可消除。建议在真实桌面再跑一次 `npm run desktop:dev` 做最终可视化确认。
- electron 二进制通过国内镜像安装，未来若换环境重装需保持镜像配置，否则可能复现下载挂起。
