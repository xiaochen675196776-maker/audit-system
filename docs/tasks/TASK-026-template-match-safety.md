# TASK-026：模板匹配安全与重复表头纠偏

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 15:00
完成时间：2026-06-22 15:30

## 目标

修复总指挥验收发现的模板错配风险：模板候选和显式套用模板时，必须校验当前文件表头与模板签名是否匹配，不能只按 `col_001`、`col_002` 位置直接套用。

当前阻塞证据：

- 一个完全不相关的 9 列文件（`customer,vendor,department,project,amount,note,status,date,number`）会被序时账模板判为候选，分数可达 63。
- `test_template()` 对同列数但不同表头的文件返回 `applicable=True`，并生成完整 `column_mapping_v2`。
- 从样本生成模板时，重复表头使用 `{header: column_id}` 反查，同名表头会保留最后一列；英文样本 `summary,summary` 中，`summary` 被保存到 `col_004`，`col_003` 变成辅助字段。

## 前置依赖

- `TASK-025` 当前总体验收未通过。
- 开始前必须阅读 `docs/COMMAND_CENTER.md`、本任务和 `docs/tasks/TASK-025-template-library-final-acceptance.md`。
- 开始前运行 `git status --short`，不要回滚已有未提交改动。

## 允许修改范围

可以修改：

- `backend/app/services/template_matcher.py`
- `backend/app/services/template_service.py`
- `backend/app/services/column_matcher.py`（仅当需要复用匹配置信度/负向规则）
- `backend/tests/test_template_service.py`
- `backend/tests/test_import_service.py`
- `docs/tasks/TASK-026-template-match-safety.md`

不要修改：

- 前端
- ORM 模型
- 路由结构
- 与模板匹配无关的导入校验逻辑

## 必须修复

### 1. 模板评分必须基于当前文件实际表头匹配

`match_templates()` 不能只看 `template.column_rules` 覆盖了哪些标准字段。

评分必须至少同时考虑：

- 模板签名列与当前文件列的表头相似度。
- 模板规则中的标准字段是否能在当前文件对应列找到合理表头。
- 必填字段是否在当前文件中被可靠命中。

硬性要求：

- 完全不相关表头文件不能返回高分候选。
- 如果当前文件与模板签名没有足够列级相似度，候选要么不返回，要么分数低于 40 且带中文 warning。
- 缺必填字段必须降分。
- 重复表头必须给中文 warning，但不能因为重复表头而自动错列。

### 2. 显式套用模板也必须校验签名

`apply_template_to_columns()` 或调用它的路径必须校验当前文件列与模板签名。

硬性要求：

- 如果模板列签名和当前文件不匹配，不得直接按 `col_001` 位置套用。
- 返回/抛出的错误必须是中文，并说明“模板与当前文件表头不匹配”。
- 只有列签名匹配或相似度达到安全阈值时，才允许生成 `column_mapping_v2`。

### 3. 从样本生成模板要正确处理重复表头

`from_sample()` 不能用 `{header: column_id}` 这种丢失重复列的反查方式。

硬性要求：

- 对重复表头，自动匹配器实际选择哪一列，模板就保存哪一列。
- 如果无法可靠判断，应只映射第一处高置信列，其他重复列标为辅助字段并给 warning。
- 英文样本 `summary,summary` 必须把第一处 `summary` 保存为 `summary`，第二处不能覆盖第一处。

## 必须新增测试

至少新增这些测试：

1. `test_match_templates_rejects_unrelated_same_width_file`
   - 模板是正常序时账签名。
   - 文件是 `customer,vendor,department,project,amount,note,status,date,number`。
   - 断言不返回候选，或候选分数 `< 40` 且 warnings 包含“表头不匹配”。

2. `test_test_template_rejects_unrelated_same_width_file`
   - 同上，但调用 `test_template()`。
   - 断言 `applicable is False`，`column_mapping_v2 == {}`。

3. `test_apply_template_to_columns_rejects_signature_mismatch`
   - 直接调用模板套用函数。
   - 断言不会返回完整映射。

4. `test_from_sample_duplicate_english_summary_keeps_first_summary_column`
   - 文件表头含 `summary,summary`。
   - 断言 `column_rules["col_003"] == "summary"`，`column_rules["col_004"] != "summary"`。

5. 保留现有重复中文表头测试，并让断言明确，不允许“至少有一个匹配”这种宽松条件。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_template_service.py tests/test_import_service.py
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend docs
```

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
