# TASK-015：后端导入校验回归修复

状态：DONE
执行者：Reasonix
开始时间：2025-01-21 13:10
完成时间：2025-01-21 13:15

## 目标

按最新业务口径修复后端导入校验，并同步修正不符合口径的测试。

最新口径：

- 负数金额允许导入，不需要拦截。
- 序时账凭证级借贷不平衡可以拦截。
- 科目余额表不做借贷平衡拦截。

## 当前失败证据

总指挥在 2026-06-18 复跑：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest -q
```

结果：

- `3 failed, 79 passed, 1 warning`
- `tests/test_import_service.py::TestImportDataJournal::test_import_journal_unbalanced_voucher`
- `tests/test_import_service.py::TestImportDataErrors::test_negative_amount_rejected`
- `tests/test_validator.py::TestValidateRow::test_negative_amount_error`

当前测试失败分两类处理：

1. 借方 `10000`、贷方 `8000` 的同一序时账凭证没有返回“借贷不平衡”错误。这个要修。
2. 负数金额相关测试仍要求“不能为负数”。这个测试口径已经失效，要改为允许负数金额导入。

## 初步定位

请先自己复核，不要机械照抄。

- `backend/app/services/validator.py` 里 `_validate_row` 当前只判断金额是否为有效数字。负数金额按最新口径允许，不要新增负数拦截。
- `backend/app/services/validator.py` 里 `validate_rows` 当前注释掉了 `_validate_balance(valid_rows, error_rows, data_type)`。
- 注释原因写的是“多级科目导入时下级科目不一定借贷相等”，所以不要粗暴恢复所有数据类型的余额表平衡校验。只恢复 `journal` 的凭证级借贷平衡校验，避免重新引入科目余额表误报。

## 允许修改范围

可以修改：

- `backend/app/services/validator.py`
- `backend/app/services/import_service.py`（只有确实需要时）
- `backend/tests/test_import_service.py`
- `backend/tests/test_validator.py`

不要修改：

- `frontend/`
- UI 文案任务文件
- 数据库模型结构
- 与导入校验无关的接口

## 必须修复的问题

### 1. 负数金额允许导入

负数金额不是错误，不要拦截。

需要调整现有测试：

- `tests/test_import_service.py::TestImportDataErrors::test_negative_amount_rejected`
- `tests/test_validator.py::TestValidateRow::test_negative_amount_error`

这些测试不应再期待“不能为负数”。可以改为验证负数金额能通过数字校验并保持为负数，或删除失效断言并补充更符合当前口径的用例。

非法数字仍然要报错，例如非数字文本不能静默当作 `0` 入库。

### 2. 序时账凭证借贷不平衡必须检出

对 `journal` 数据按凭证号分组，借方合计和贷方合计差额超过 `0.01` 时，必须返回错误，错误消息包含：

```text
借贷不平衡
```

注意：已有测试只要求返回错误，不要求删除其他正常凭证。不要因为一个凭证不平衡导致整个文件抛异常。

不要因为一个凭证不平衡导致整个文件抛异常。按现有导入返回结构写入错误列表。

### 3. 科目余额表不做借贷平衡拦截

科目余额表存在多级科目和汇总科目，不能按普通借贷合计直接拦截。

不要恢复 `trial_balance` 的总体借贷平衡校验。若有测试要求科目余额表借贷平衡拦截，应按最新口径调整或删除。

### 4. 辅助明细账不要顺手扩范围

本任务明确要求修 `journal`。除非现有测试已经覆盖并且业务语义完全一致，否则不要把 `subsidiary` 的行为一起改掉。

## 验收命令

必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m compileall app
D:\python\python.exe -m pytest -q
```

必须再运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend
```

验收标准：

- `compileall` 通过。
- `pytest` 全部通过，允许保留现有 Pydantic 弃用警告。测试数量可以因删除或改写失效负数用例发生合理变化。
- 序时账借贷不平衡用例必须保留并通过。
- 负数金额允许导入的用例必须保留或新增并通过。
- 科目余额表不得新增借贷平衡拦截。
- `git diff --check -- backend` 通过。
- 不修改前端文件。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2025-01-21 13:15

### 修改文件

- `backend/app/services/validator.py`
- `backend/tests/test_validator.py`
- `backend/tests/test_import_service.py`

### 完成内容

1. **恢复序时账凭证级借贷平衡校验**：`validate_rows()` 中取消注释，但仅对 `data_type == "journal"` 调用 `_validate_journal_balance()`。科目余额表和辅助明细账不做借贷平衡拦截。

2. **负数金额允许导入**：`_validate_row()` 本身从未拦截负数（只校验是否为有效数字），仅测试期望错误。修改两处测试：
   - `test_validator.py::test_negative_amount_error` → `test_negative_amount_allowed`：断言 `errors == []`
   - `test_import_service.py::test_negative_amount_rejected` → `test_negative_amount_allowed`：断言 `success == 1`

3. **科目余额表不恢复借贷平衡**：`_validate_trial_balance` 函数保留但不在 `validate_rows` 中调用。

### 验证命令

```powershell
D:/python/python.exe -m compileall app
D:/python/python.exe -m pytest -q
```

结果：**82 passed, 1 warning**（Pydantic 弃用警告，非本任务引入）

```powershell
git diff --check -- backend
```

结果：**通过** — 无空白错误

### 风险和后续

- 无阻塞问题
- `_validate_balance` 和 `_validate_trial_balance` 函数保留在代码中但不再被 `validate_rows` 调用；如有需要可在未来配置驱动恢复
- 辅助明细账（subsidiary）始终保持不拦截借贷平衡，符合多级科目业务语义
