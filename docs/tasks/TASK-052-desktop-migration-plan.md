# TASK-052：桌面端迁移任务规划

状态：DONE
优先级：P0（本轮优先）
是否可并行：否（必须先登记规划再执行后续）

## 目标

1. 创建设计文档 `docs/DESKTOP_MIGRATION_PLAN.md`，描述桌面端迁移的技术方案、架构和任务拆分。
2. 把 TASK-052 至 TASK-057 登记到 `docs/COMMAND_CENTER.md` 任务队列。
3. 创建 TASK-053 至 TASK-057 的任务文件，为后续执行做好准备。

## 设计口径

- 第一版桌面端不做登录、注册、授权。
- 保留现有 Vue + FastAPI 技术栈。
- 桌面端采用 Electron 作为第一版桌面壳。
- 后端继续使用 FastAPI，本地运行。
- 数据库使用 SQLite。
- 用户数据、上传文件、日志必须放到用户可写目录，不能放安装目录。
- Web/Docker 路线暂时保留，不要破坏现有浏览器开发方式。
- 第一阶段目标是 Windows 本地可运行，不要求正式安装包。

## 允许修改范围

- `docs/` 目录下的新建设计文档和任务文件。
- `docs/COMMAND_CENTER.md` 任务队列追加。

## 禁止事项

- 不要修改 `backend/`、`frontend/`、`docker-compose.yml` 等业务代码。
- 不要回滚、删除、清理任何现有文件。
- 不要修改任何已有任务文件。

## 验收标准

- [x] `docs/DESKTOP_MIGRATION_PLAN.md` 已创建，包含架构设计和任务拆分。
- [x] `docs/tasks/TASK-052-desktop-migration-plan.md` 已创建（本文件，状态最终为 DONE）。
- [x] `docs/tasks/TASK-053-backend-local-desktop-runtime.md` 已创建。
- [x] `docs/tasks/TASK-054-frontend-runtime-api-base.md` 已创建。
- [x] `docs/tasks/TASK-055-electron-shell-mvp.md` 已创建。
- [x] `docs/tasks/TASK-056-backend-pyinstaller-package.md` 已创建。
- [x] `docs/tasks/TASK-057-desktop-acceptance.md` 已创建。
- [x] `docs/COMMAND_CENTER.md` 在 TASK-051 后追加了 TASK-052 至 TASK-057。
- [x] 所有任务文件包含：状态、目标、允许修改范围、禁止事项、验收标准、验收命令、完成回报要求。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 23:05

### 修改文件

- `docs/DESKTOP_MIGRATION_PLAN.md`
- `docs/tasks/TASK-052-desktop-migration-plan.md`
- `docs/tasks/TASK-053-backend-local-desktop-runtime.md`
- `docs/tasks/TASK-054-frontend-runtime-api-base.md`
- `docs/tasks/TASK-055-electron-shell-mvp.md`
- `docs/tasks/TASK-056-backend-pyinstaller-package.md`
- `docs/tasks/TASK-057-desktop-acceptance.md`
- `docs/COMMAND_CENTER.md`

### 完成内容

- 创建桌面端迁移设计文档 `docs/DESKTOP_MIGRATION_PLAN.md`，包含架构设计（Electron + FastAPI + SQLite）、用户数据目录规划、任务拆分、风险与未决事项。
- 创建 TASK-052 至 TASK-057 共 6 个任务文件，每个文件包含完整的状态、目标、允许修改范围、禁止事项、验收标准、验收命令、完成回报要求。
- 更新 `docs/COMMAND_CENTER.md`，在 TASK-051 后追加 TASK-052 至 TASK-057，并新增「桌面端迁移分派」章节。
- 所有新建文件均为纯文档文件，未修改任何 `backend/`、`frontend/` 业务代码。

### 验证命令

```powershell
git diff --check -- docs
```

结果：

- 通过（仅有 LF/CRLF 换行警告，无实际错误）

### 风险和后续

- 无。TASK-053 ~ TASK-057 已就绪，等待领取执行。

## 验收命令

```powershell
git diff --check -- docs
```

## 完成回报要求

完成后将本文件状态改为 `DONE`，并按 `docs/tasks/DONE_TEMPLATE.md` 格式在本文件底部追加完成回报。
