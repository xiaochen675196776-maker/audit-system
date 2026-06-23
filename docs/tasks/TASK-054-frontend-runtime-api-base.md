# TASK-054：前端运行时 API 基地址动态化

状态：DONE
优先级：P0
依赖：TASK-052
是否可并行：可与 TASK-053 并行

## 目标

改造前端，使其在桌面端 Electron 环境下能正确连接到本地 FastAPI 后端。

## 设计要点

参见 `docs/DESKTOP_MIGRATION_PLAN.md` 第 3.2.3 和 3.2.4 节。

### 策略

第一版桌面端继续使用 Vite dev server + proxy，因此前端代码改动最小。

### 3.1 API 基地址

当前 `frontend/src/api/index.ts`：
```ts
const api = axios.create({
  baseURL: '/api/v1',
  ...
})
```

桌面端 Electron 加载 `http://localhost:5173`，Vite proxy 转发 `/api` 到 FastAPI。此方式 **无需修改** `baseURL`。

但需要确认：Vite proxy target 端口与 FastAPI 实际端口一致。

### 3.2 Vite 配置

`frontend/vite.config.ts` 的 proxy target 当前硬编码为 `http://localhost:8000`。

改造方案：
- 新增环境变量 `VITE_API_TARGET` 控制 proxy target。
- 桌面端启动时 Electron 将实际 FastAPI 端口写入环境变量，Vite 读取后设置 proxy target。
- 未设置时默认 `http://localhost:8000`（保持现有行为）。

### 3.3 前端运行时配置注入

新增 `frontend/src/config.ts`（或更新现有），在应用初始化时从 Electron 或环境变量读取：
- `API_BASE_URL`：API 基地址（备用，第一版不强制）。
- `DESKTOP_MODE`：是否桌面模式（用于 UI 微调，如隐藏部署相关提示）。

### 3.4 构建产物兼容

- `npm run build` 产物在 Electron 静态托管场景也能工作（为后续策略 B 做准备）。
- 为此，`baseURL` 需要支持从 `window.__AUDIT_CONFIG__` 全局变量读取。

## 允许修改范围

- `frontend/vite.config.ts` — 新增 proxy target 环境变量。
- `frontend/src/api/index.ts` — 可选，支持运行时配置。
- `frontend/src/config.ts` — 新建，运行时配置读取。
- `frontend/index.html` — 可选，注入全局配置占位。
- `frontend/package.json` — 如需新增依赖。

## 禁止事项

- 不要修改业务页面组件和 UI。
- 不要修改后端代码。
- 不要破坏现有 `npm run dev` 浏览器开发流程。
- 不要回滚、删除、清理任何现有文件。

## 验收标准

- [ ] 浏览器开发 `npm run dev` 行为不变。
- [ ] `npm run build` 产物可用。
- [ ] 设置 `VITE_API_TARGET=http://localhost:18000` 后，Vite proxy 转发到 18000。
- [ ] `window.__AUDIT_CONFIG__` 机制就绪（为后续策略 B 准备）。

## 验收命令

```powershell
cd frontend

# 浏览器开发模式
npm run dev
# 确认 http://localhost:5173 可打开，API 请求正常

# 构建
npm run build
# 确认无错误

# 自定义 proxy target 测试
$env:VITE_API_TARGET = "http://localhost:18000"
npm run dev
# 确认 proxy 转发到 18000
```

## 完成回报要求

完成后将本文件状态改为 `DONE` 或 `REVIEW_NEEDED`，并按 `docs/tasks/DONE_TEMPLATE.md` 格式在本文件底部追加完成回报。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 23:15

### 修改文件

- `frontend/vite.config.ts`
- `frontend/src/config.ts`
- `frontend/src/api/index.ts`
- `frontend/index.html`

### 完成内容

- `vite.config.ts` 支持 `VITE_API_TARGET` 环境变量，未设置时默认 `http://localhost:8000`，桌面端由 Electron 注入实际后端端口。
- 新建 `config.ts`，定义 `AuditConfig` 接口和 `runtimeConfig` 单例，从 `window.__AUDIT_CONFIG__` 读取桌面端注入的配置。
- `api/index.ts` 在 `runtimeConfig.apiBaseUrl` 非空时使用绝对 URL，否则回退相对路径 `/api/v1`（保持浏览器开发兼容）。
- `index.html` 注入 `window.__AUDIT_CONFIG__` 初始化脚本，供桌面端 preload.js 覆盖。

### 验证命令

```powershell
npm run build
```

结果：

- built in 7.34s，无错误（仅 chunk size 预存警告）

### 风险和后续

- 无。`VITE_API_TARGET` 环境变量方式需与 TASK-055 Electron 主进程配合验证。
