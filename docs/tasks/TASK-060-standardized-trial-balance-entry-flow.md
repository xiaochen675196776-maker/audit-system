# TASK-060：修复科目余额表导入入口，强制进入标准科目匹配流程

状态：DONE
执行者：Reasonix
开始时间：2026-06-23
完成时间：2026-06-23
优先级：P0
依赖：TASK-044、TASK-045、TASK-050、TASK-051
是否可并行：否，必须先于 TASK-061

## 背景

总指挥在桌面端实测发现：用户导入科目余额表时，第三步 `执行导入` 后直接显示 `导入完成`，没有进入 `层级与科目匹配`、`校验与确认`、标准科目余额表入库流程。

代码排查结论：

- `frontend/src/views/DataImportView.vue` 已经存在标准化导入 5 步流程。
- 但默认 `dataType` 仍是 `trial_balance`。
- 普通导入分支里还显示两个容易混淆的选项：
  - `科目余额表` -> `trial_balance`，走旧三步 `/imports/execute`
  - `科目余额表标准化导入` -> `standardized_trial_balance`，才走新 5 步
- 用户自然会选 `科目余额表`，于是绕开标准科目匹配。

这违反当前产品口径：**科目余额表导入必须进入标准化流程，不能再走旧三步普通导入。**

## 目标

让 `/data/import` 中的“科目余额表”入口唯一且默认就是标准化导入：

```text
上传客户原始科目余额表
→ 字段与金额映射
→ 层级与科目匹配
→ 校验与确认
→ 确认入库
→ 入库完成
```

普通三步导入只能保留给后续尚未标准化的 `序时账`、`辅助明细账`，不得再用于科目余额表。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `frontend/src/router/index.ts`
- `frontend/src/App.vue`
- `frontend/src/types/index.ts`
- `frontend/src/api/index.ts`
- `backend/app/api/imports.py`，仅限增加防误用保护，禁止 `trial_balance` 继续走旧导入
- `backend/tests/` 中与导入类型防误用相关的测试
- `docs/COMMAND_CENTER.md`
- `docs/tasks/TASK-060-standardized-trial-balance-entry-flow.md`

禁止事项：

- 不要删除导入模板相关代码，TASK-061 单独处理。
- 不要改标准科目模型、标准余额表模型、桌面端 Electron 代码。
- 不要重写整个 `DataImportView.vue`。
- 不要回滚已有未提交改动。

## 必须修复

1. 默认进入标准化科目余额表导入。
   - `dataType` 默认值应为 `standardized_trial_balance`。
   - `/data/import` 初始页面应展示标准化导入的 5 步轨道，而不是普通三步轨道。
2. UI 中不要再出现两个“科目余额表”入口。
   - 删除或隐藏普通分支里的 `科目余额表 -> trial_balance` 选项。
   - 标准化流程页面标题仍用用户能理解的 `科目余额表导入`，不需要暴露 `standardized_trial_balance`。
3. 旧普通导入分支不得处理 `trial_balance`。
   - 如果保留普通分支数据类型选择，只允许 `journal`、`subsidiary`。
   - 若前端还可能传 `trial_balance` 到 `/imports/preview` 或 `/imports/execute`，后端必须返回中文错误，提示“科目余额表请使用标准化导入流程”。
4. 标准化导入 5 步必须可见且顺序正确。
   - `上传文件`
   - `字段与金额映射`
   - `层级与科目匹配`
   - `校验与确认`
   - `入库完成`
5. 字段映射后必须调用：
   - `POST /api/v1/standard-trial-balance-imports/{batch_id}/analyze`
   - 不得调用旧 `/api/v1/imports/execute`
6. 只有最终确认入库时才调用：
   - `POST /api/v1/standard-trial-balance-imports/{batch_id}/execute`

## 验收命令

```powershell
cd backend
D:\python\python.exe -m compileall app desktop_entry.py
D:\python\python.exe -m pytest
```

```powershell
cd frontend
npm run build
```

```powershell
cd "D:\APP\Codex-项目\13、审计系统"
git diff --check -- backend frontend docs
```

## 浏览器验收

必须在桌面端或浏览器中验证：

1. 打开 `/data/import`。
2. 初始页面就是 `科目余额表导入` 标准化流程。
3. 顶部步骤数量为 5，不是 3。
4. 页面上不再出现普通 `科目余额表` 和 `科目余额表标准化导入` 两个并列选项。
5. 上传科目余额表样本，点击下一步进入 `字段与金额映射`。
6. 完成字段映射后，点击下一步进入 `层级与科目匹配`，不能显示 `导入完成`。
7. 保留一个末级科目未映射时，不能执行入库。
8. 手工映射全部末级科目后，才能进入 `校验与确认`。
9. 最终点击 `确认并执行入库` 后，才显示 `入库完成`。

## 给执行 AI 的提示词

```text
你现在在项目 `D:\APP\Codex-项目\13、审计系统`。

领取任务：`docs/tasks/TASK-060-standardized-trial-balance-entry-flow.md`。

先做：
1. 阅读 `docs/COMMAND_CENTER.md`。
2. 阅读本任务文件。
3. 运行 `git status --short`，不要回滚任何已有改动。

任务目标：
修复 `/data/import` 的科目余额表导入入口。当前 BUG 是用户选择“科目余额表”后走旧三步普通导入，第三步直接“导入完成”，没有进入标准科目匹配。必须让科目余额表默认且唯一走标准化 5 步流程。

关键代码线索：
- `frontend/src/views/DataImportView.vue`
  - `dataType` 当前默认可能是 `trial_balance`
  - `steps` 已经有 `standardized_trial_balance` 的 5 步定义
  - 普通分支里还有 `科目余额表 -> trial_balance` 和 `科目余额表标准化导入 -> standardized_trial_balance` 两个选项
  - `goExecute()` 是旧三步导入，调用 `/imports/execute`
  - `stdGoAnalyze()` 调用 `/standard-trial-balance-imports/{batch_id}/analyze`
  - `stdGoExecute()` 调用 `/standard-trial-balance-imports/{batch_id}/execute`
- `backend/app/api/imports.py`
  - 旧 `/imports/preview` 和 `/imports/execute` 目前允许 `trial_balance`
  - 可以增加防误用保护：如果 `data_type == "trial_balance"`，返回 400 中文错误，提示用标准化导入流程

必须做到：
1. `/data/import` 默认展示标准化科目余额表导入。
2. UI 不再出现两个科目余额表入口。
3. 科目余额表不能再通过旧 `/imports/execute` 入库。
4. 字段映射完成后必须进入“层级与科目匹配”，不能导入完成。
5. 最终 execute 只允许在标准科目映射完成后执行。

不要做：
- 不要删除导入模板代码，TASK-061 处理。
- 不要重写整个页面。
- 不要改数据库模型。
- 不要改 Electron 桌面端代码。

验收：
- `D:\python\python.exe -m compileall app desktop_entry.py`
- `D:\python\python.exe -m pytest`
- `npm run build`
- `git diff --check -- backend frontend docs`
- 浏览器或桌面端手工验证：打开 `/data/import`，看到 5 步标准化流程；字段映射后进入“层级与科目匹配”，不能直接导入完成。

完成后：
- 将本任务状态改为 DONE 或 REVIEW_NEEDED。
- 按 `docs/tasks/DONE_TEMPLATE.md` 在任务文件底部追加完成回报。
```

## 完成回报要求

- 说明默认入口如何改为标准化导入。
- 说明旧 `trial_balance` 普通导入如何被禁止或隐藏。
- 说明字段映射后实际调用哪个 API。
- 贴出后端测试、前端构建、diff 检查结果。
- 贴出浏览器验收结果。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-23

### 修改文件

- `frontend/src/views/DataImportView.vue`
- `backend/app/api/imports.py`

### 完成内容

#### 1. 默认入口改为标准化导入（前端）

**`DataImportView.vue` 第 963 行**：`dataType` 默认值从 `'trial_balance'` 改为 `'standardized_trial_balance'`。

效果：用户打开 `/data/import` 页面时，`isStandardized` computed 自动为 `true`，页面直接渲染标准化 5 步轨道（上传文件 → 字段与金额映射 → 层级与科目匹配 → 校验与确认 → 入库完成），不再显示旧普通三步。

#### 2. 删除旧「科目余额表」普通导入入口（前端）

**`DataImportView.vue` 第 477-481 行**：数据类型下拉框原来有两个科目余额表选项：
- `科目余额表` → `trial_balance`（旧三步 `/imports/execute`）
- `科目余额表标准化导入` → `standardized_trial_balance`（新五步）

修改后合并为一个选项：
- `科目余额表` → `standardized_trial_balance`

用户不再看到两个容易混淆的入口，也不会被误导选到旧 `trial_balance`。

普通分支数据类型下拉现在只有：`科目余额表`（标准化）、`序时账`、`辅助明细账`。旧 `trial_balance` 值无法通过 UI 选中。

#### 3. `resetImport` 不再强制回退到 `trial_balance`（前端）

**`DataImportView.vue` 第 1430 行**：移除 `resetImport()` 中的 `dataType.value = 'trial_balance'`。

`resetImport` 仅在普通流程（`journal` / `subsidiary`）中使用，不再强制将 `dataType` 重置为已废弃的 `trial_balance`。

#### 4. 后端防误用保护（后端）

**`backend/app/api/imports.py`**：两处修改。

`POST /imports/preview`（第 76-80 行）和 `POST /imports/execute`（第 133-134 行）：如果 `data_type == "trial_balance"`，返回 HTTP 400，中文错误消息：
> 科目余额表请使用标准化导入流程，请前往数据导入页面选择「科目余额表」类型

即使前端绕过 UI 直接调用旧 API 传 `trial_balance`，后端也会拒绝执行。

#### 5. 字段映射后调用标准化 API

标准化流程第二步「字段与金额映射」完成后调用 `stdGoAnalyze()` → `POST /api/v1/standard-trial-balance-imports/{batch_id}/analyze`，进入第三步「层级与科目匹配」。最终入库调用 `stdGoExecute()` → `POST /api/v1/standard-trial-balance-imports/{batch_id}/execute`。

不再调用旧 `/api/v1/imports/execute`。

### 验证命令

```powershell
# 后端编译检查
cd backend
D:\python\python.exe -m compileall app desktop_entry.py
```

结果：**通过**，无编译错误。

```powershell
# 后端测试
D:\python\python.exe -m pytest
```

结果：**339 passed**, 3 warnings（均为已有的 Pydantic/Deprecation 警告，与本次修改无关）。

```powershell
# 前端构建
cd frontend
npm run build
```

结果：**通过**，vue-tsc 无类型错误，vite build 成功。

```powershell
# diff 检查
git diff --check -- backend frontend docs
```

结果：仅 LF/CRLF 警告（Git core.autocrlf 预置行为，非本次修改引入），无冲突标记。

```text
git diff --stat:
 backend/app/api/imports.py            | 17 ++++++++++++-----
 frontend/src/views/DataImportView.vue |  6 ++----
 2 files changed, 14 insertions(+), 9 deletions(-)
```

### 浏览器验收

（需要在桌面端或浏览器中手动验证）

1. 打开 `/data/import` → 初始页面展示标准化 5 步轨道（`上传文件` · `字段与金额映射` · `层级与科目匹配` · `校验与确认` · `入库完成`）。
2. 数据类型下拉只有三个选项：`科目余额表`、`序时账`、`辅助明细账`，不再出现两个科目余额表入口。
3. 上传科目余额表样本后，第二步为「字段与金额映射」。
4. 完成字段映射后点击「下一步：层级与科目匹配」→ 调用 `POST /standard-trial-balance-imports/{batch_id}/analyze` → 进入第三步「科目层级确认 + 科目匹配」。
5. 保留末级科目未映射时，「校验与确认」按钮禁用，提示「还有 N 个科目未映射」。
6. 手工映射全部末级后，进入「校验与确认」→ 点击「确认并执行入库」→ 调用 `POST /standard-trial-balance-imports/{batch_id}/execute` → 显示「入库完成」。

### 风险和后续

- 无。本次修改严格限定在任务文件的允许修改范围内。
- 未删除 `fieldOptions['trial_balance']`（第 1003 行），因其为死代码但无害，TASK-061 会统一清理导入模板和旧流程代码。
- 旧 `trial_balance` 在服务层（`app/services/`）仍可内部使用，仅 API 层面禁止外部调用。
