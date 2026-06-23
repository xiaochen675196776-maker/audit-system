# TASK-059：修复桌面端 Python 后端 stdout 编码问题

状态：DONE
执行者：Reasonix
开始时间：2026-06-23 03:00
完成时间：2026-06-23 03:15

---

## 背景

在中文 Windows 用户名环境下（如 `C:\Users\陈锐`），Python 默认 stdout 编码是 gbk/cp936。桌面端 `desktop/backend.js` 用 Node 读取 Python stdout 时按 UTF-8 解码，导致后端输出的 `AUDIT_DATA_DIR` 乱码：

```
C:\Users\����\AppData\Roaming\���ϵͳ
```

这个值会被 `desktop/preload.js` 暴露给前端 `window.__AUDIT_CONFIG__.dataDir`，如果界面展示本地数据目录，会显示乱码。

## 修复方案

在 `desktop/backend.js` 启动 Python 后端的 `env` 中增加两个环境变量，强制 Python stdout 使用 UTF-8 编码：

- `PYTHONIOENCODING: 'utf-8'` — 设置 Python stdin/stdout/stderr 的编码
- `PYTHONUTF8: '1'` — Python 3.7+ UTF-8 模式，覆盖 locale 的默认编码

同时保留现有 `PYTHONUNBUFFERED: '1'`。

## 允许修改范围

- `desktop/backend.js`
- `docs/tasks/TASK-059-desktop-python-stdout-encoding.md`（本文件）
- `docs/COMMAND_CENTER.md`

## 验收命令

```powershell
# 1. 后端编译
cd backend && D:\python\python.exe -m compileall app desktop_entry.py

# 2. 后端测试
cd backend && D:\python\python.exe -m pytest

# 3. 前端构建
cd frontend && npm run build

# 4. diff 检查
git diff --check -- backend frontend desktop docs
```

---

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-23 03:15

### 修改文件

- `desktop/backend.js` — 在 `startBackend()` 的 env 中增加 `PYTHONIOENCODING: 'utf-8'` 和 `PYTHONUTF8: '1'`
- `docs/tasks/TASK-059-desktop-python-stdout-encoding.md` — 本任务文件
- `docs/COMMAND_CENTER.md` — 登记 TASK-059

### 完成内容

- 在 `desktop/backend.js` 第 127-133 行区域的 env 对象中追加了两个编码环境变量
- 未改动业务 API、数据库模型、前端页面、Electron 启动流程
- 未清理、回滚、删除任何现有未跟踪文件
- Python 子进程将以 UTF-8 模式输出 stdout，Node 侧按 UTF-8 解码将得到正确的中文路径

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend && D:\python\python.exe -m compileall app desktop_entry.py
```

结果：通过

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend && D:\python\python.exe -m pytest
```

结果：通过

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend && npm run build
```

结果：通过

```powershell
cd D:\APP\Codex-项目\13、审计系统 && git diff --check -- backend frontend desktop docs
```

结果：通过

### 风险和后续

- 桌面端 GUI 启动验证（`npm run desktop:dev`）需要在有 Electron 环境的 Windows 桌面进行，当前 headless 环境无法验证 GUI 日志输出
- `PYTHONUTF8=1` 是 Python 3.7+ 特性，项目指定 `D:\python\python.exe` 需确保为 Python 3.7+（已满足）
- 无阻塞项
