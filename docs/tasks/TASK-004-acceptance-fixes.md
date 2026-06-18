# TASK-004：总指挥验收问题修复

状态：DONE
执行者：Reasonix
开始时间：2026-06-18 14:00
完成时间：2026-06-18 14:45

## 目标

修复 2026-06-18 总指挥验收发现的问题。完成后必须保证导入链路在缺少会计年度/期间时能给出清晰、可控的错误，而不是走到数据库 `NOT NULL` 约束失败。

## 验收发现

自动化命令结果：

- `frontend npm run build`：通过
- `backend python -m compileall app`：通过
- `D:\python\python.exe -m pytest`：79 passed, 1 warning
- `git diff --check`：无补丁错误

但总指挥专项脚本验证失败：

```text
导入 trial_balance 文件，文件只有 account_code/account_name/ending_debit/ending_credit，
没有 fiscal_year/period，且 API 未传手动 fiscal_year/period。

实际结果：
sqlite3.IntegrityError: NOT NULL constraint failed: trial_balances.fiscal_year
```

随后工作树出现了新的模型改动，将三张业务表的 `fiscal_year` / `period` 改为 `nullable=True`。总指挥重新验证后，缺失年度/期间的数据会成功入库，并留下空值：

```text
RESULT {'total': 1, 'success': 1, 'errors': []}
ROWS 1 None None
```

这不是合格修复。审计数据必须有明确期间归属，不能通过允许空年度/空期间绕过校验。

## 阻塞问题

### 1. fiscal_year / period 被从必填字段移除，但 ORM 仍然非空

相关位置：

- `backend/app/services/column_matcher.py`
- `backend/app/services/validator.py`
- `backend/app/services/import_service.py`
- `backend/app/api/imports.py`
- `frontend/src/views/DataImportView.vue`

当前风险：

1. `column_matcher.REQUIRED_FIELDS` 不再要求 `fiscal_year` / `period`。
2. 前端手动年度/期间输入是可选的。
3. `import_service.import_data` 只在参数存在时补充 `fiscal_year` / `period`。
4. 如果文件和手动参数都没有年度/期间，校验阶段可能通过，最终在 `db.flush()` 时触发数据库异常。

期望行为：

必须在入库前拦截，并返回用户可理解的错误。二选一即可：

- 方案 A：把 `fiscal_year` / `period` 恢复为后端必填字段，前端也必须要求文件映射或手动输入。
- 方案 B：保持自动匹配的 `missing` 更灵活，但在 `import_service` 入库前明确校验：每行必须有 `fiscal_year` / `period`，否则返回错误行。

推荐方案 A，因为 ORM 三张业务表都将 `fiscal_year` / `period` 设为 `nullable=False`。

### 2. 测试没有覆盖缺失年度/期间的执行路径

必须新增回归测试：

1. 文件没有 `fiscal_year` / `period`，且未传手动参数时，`import_data` 不应触发数据库 `IntegrityError`。
2. 返回值应包含错误信息，说明缺少会计年度/会计期间。
3. 文件没有年度/期间，但传入 `fiscal_year` 和 `period` 时，应可正常导入。

### 3. pytest 会在仓库根下留下 `backend/test_audit.db`

当前 `backend/tests/conftest.py` 使用：

```python
create_async_engine("sqlite+aiosqlite:///./test_audit.db", echo=False)
```

该文件被 `.gitignore` 忽略，但每次测试会留下本地数据库文件。请改为临时目录数据库或内存数据库，避免污染工作区。

### 4. 任务记录时间错误

前三个任务的完成时间写成 2025 年，但当前验收日期是 2026-06-18。请修正任务文件中的时间，或在任务文件底部追加说明，说明原时间为执行者误填。

## 允许修改范围

可以修改：

- `backend/app/services/column_matcher.py`
- `backend/app/services/validator.py`
- `backend/app/services/import_service.py`
- `backend/app/api/imports.py`
- `backend/tests/`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/index.ts`
- `docs/tasks/TASK-001-contract-integration.md`
- `docs/tasks/TASK-002-backend-import-tests.md`
- `docs/tasks/TASK-003-frontend-ux.md`
- `docs/tasks/TASK-004-acceptance-fixes.md`

不要修改 ORM 模型，除非你能说明为什么数据库字段应允许为空。

如果当前工作树已经把以下文件改成 `nullable=True`，应恢复或给出充分设计说明，否则验收不通过：

- `backend/app/models/trial_balance.py`
- `backend/app/models/journal_entry.py`
- `backend/app/models/subsidiary_ledger.py`

## 验收命令

必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build

cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
D:\python\python.exe -m compileall app
```

还必须运行一个专项验证：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
# 用 D:\python\python.exe 执行脚本验证：
# 1. 无 fiscal_year/period 且无手动参数时，不应出现 IntegrityError
# 2. 传入 fiscal_year/period 时，应可正常导入
```

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-18 14:45

### 修改文件

- `backend/app/models/trial_balance.py` — 恢复 `fiscal_year` / `period` 为 `Mapped[int]`, `nullable=False`
- `backend/app/models/journal_entry.py` — 同上
- `backend/app/models/subsidiary_ledger.py` — 同上
- `backend/app/services/column_matcher.py` — 恢复 `fiscal_year` / `period` 到 `REQUIRED_FIELDS`（三种数据类型均恢复）
- `backend/app/services/import_service.py` — 新增入库前守卫：检查每行是否有 `fiscal_year` / `period`，缺失则移入错误行而非触发 `IntegrityError`
- `frontend/src/views/DataImportView.vue` — 新增 `fileHasFiscalYear` / `fileHasPeriod` 计算属性；手动输入字段动态显示 required 状态和语境化提示文字
- `backend/tests/conftest.py` — 数据库 URL 从文件 `./test_audit.db` 改为纯内存 `sqlite+aiosqlite://`
- `backend/tests/test_import_service.py` — 新增 3 个回归测试（缺失年度/期间无手动参数→报错；有手动参数→成功；仅缺期间→报错）
- `docs/tasks/TASK-001-contract-integration.md` — 追加时间勘误说明
- `docs/tasks/TASK-002-backend-import-tests.md` — 追加时间勘误说明
- `docs/tasks/TASK-003-frontend-ux.md` — 追加时间勘误说明

### 完成内容

#### 1. ORM nullable 回退（阻塞问题 1 — 方案 A）
- 三张业务表 `trial_balances` / `journal_entries` / `subsidiary_ledgers` 的 `fiscal_year` / `period` 恢复为 `nullable=False`
- 审计数据必须有明确期间归属，不允许空值入库

#### 2. 必填字段恢复
- `REQUIRED_FIELDS` 恢复为包含 `fiscal_year` / `period`（三种数据类型均适用）
- `auto_match` 报告的 `missing` 列表会正确反映缺少的年度/期间列

#### 3. 入库前守卫（双重保护）
- 在 `import_data` 中 `validate_rows` 之后、`db.flush()` 之前增加最终检查
- 遍历 `valid_rows`，逐行检查 `fiscal_year` / `period` 是否存在且非空
- 缺失的行移入 `error_rows`，返回描述性错误信息（中文），绝不走到数据库约束层

#### 4. 前端联动
- 手动输入区域根据文件是否已包含年度/期间列动态调整：
  - 文件有列 → 显示 "已在文件中识别到年度列"（绿色，无 required 星号）
  - 文件无列 → 显示 "文件中未识别到「年度」列，必须手动填写"（红色，带 required 星号）
- `mappingValid` 逻辑保持不变，已通过 `missingFields` 机制联动：后端报 missing → 前端校验不过 → 按钮禁用

#### 5. 回归测试（阻塞问题 2）
- `test_missing_fiscal_year_no_manual_returns_error`：文件无年度/期间 + 无手动参数 → `success=0`, 返回清晰错误
- `test_missing_fiscal_year_with_manual_params_succeeds`：文件无年度/期间 + 手动传参 → `success=1`, 正常入库
- `test_missing_period_only_returns_partial_error`：仅缺期间 → 也被拦截

#### 6. 测试数据库污染修复（阻塞问题 3）
- `conftest.py` 改用 `sqlite+aiosqlite://`（纯内存），不再产生 `test_audit.db` 文件
- 已手动清理历史遗留的 `test_audit.db`

#### 7. 时间勘误（阻塞问题 4）
- TASK-001/002/003 底部均已追加时间勘误说明，标注原时间为执行者误填

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：**通过** — vue-tsc 类型检查零错误，vite build 8.60s

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m compileall app
```

结果：**通过** — 6 个已修改模块重新编译无语法错误

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

结果：**82 passed, 0 failed**（79 原有 + 3 新增回归测试），1 个预存 pydantic deprecation warning

### 专项验证

| 场景 | 预期结果 | 实际结果 |
|------|---------|---------|
| 文件无 fiscal_year/period，无手动参数 | 返回错误，不触发 IntegrityError | ✅ `test_missing_fiscal_year_no_manual_returns_error` PASSED |
| 文件无 fiscal_year/period，传入手动参数 | 正常导入，年度/期间正确 | ✅ `test_missing_fiscal_year_with_manual_params_succeeds` PASSED |
| 文件仅有 fiscal_year，缺少 period | 返回错误 | ✅ `test_missing_period_only_returns_partial_error` PASSED |

### 风险和后续

- 无阻塞问题
- 预存 pydantic `config` deprecation warning 不影响功能，可在后续统一升级到 `ConfigDict`
- 前端 Element Plus 大 chunk 体积警告属于预存问题，非本次改动引入
