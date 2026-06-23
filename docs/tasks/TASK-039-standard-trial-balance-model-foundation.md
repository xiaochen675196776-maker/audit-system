# TASK-039：标准科目与标准科目余额表模型底座

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 20:00
完成时间：2026-06-22 20:15
完成时间：-

## 目标
为“科目余额表标准化导入”建立后端数据模型底座。后续标准科目导入、客户科目映射、标准余额表生成、数据查看都必须基于这批模型继续开发。

## 依赖
无。此任务必须最先完成。

## 允许范围
- `backend/app/models/`
- `backend/app/schemas/`
- `backend/app/core/`
- `backend/alembic/versions/`
- `backend/tests/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

如项目当前没有 Alembic 迁移机制，按现有数据库建表模式补齐运行期建表逻辑，但必须在完成回报里说明。

## 交付
1. 新增全局标准科目模型 `standard_accounts`：
   - `id`
   - `account_code`
   - `account_name`
   - `account_category`
   - `balance_direction`
   - `level`
   - `parent_id`
   - `is_leaf`
   - `is_active`
   - `source_row_index`
   - `created_at`
   - `updated_at`
2. 新增客户科目映射经验模型 `client_account_mappings`：
   - `id`
   - `data_type`
   - `customer_label`
   - `source_label`
   - `client_account_code`
   - `client_account_name`
   - `normalized_client_account_name`
   - `standard_account_id`
   - `standard_account_code_snapshot`
   - `standard_account_name_snapshot`
   - `confidence`
   - `scope`
   - `usage_count`
   - `last_used_at`
   - `is_active`
   - `created_at`
   - `updated_at`
3. 新增标准化导入批次模型 `standard_trial_balance_import_batches`：
   - `id`
   - `file_name`
   - `customer_label`
   - `source_label`
   - `fiscal_year`
   - `period`
   - `status`
   - `field_mapping`
   - `amount_mapping_config`
   - `hierarchy_config`
   - `warnings`
   - `errors`
   - `created_at`
   - `updated_at`
4. 新增原始行快照模型 `standard_trial_balance_raw_rows`：
   - `id`
   - `batch_id`
   - `row_index`
   - `raw_values`
   - `client_account_code`
   - `client_account_name`
   - `client_balance_direction`
   - `client_account_category`
   - `detected_level`
   - `parent_raw_row_id`
   - `is_leaf`
   - `mapped_standard_account_id`
   - `mapping_status`
   - `warnings`
   - `created_at`
5. 新增标准余额表明细模型 `standard_trial_balance_entries`：
   - `id`
   - `batch_id`
   - `raw_row_id`
   - `standard_account_id`
   - `standard_account_code_snapshot`
   - `standard_account_name_snapshot`
   - `standard_account_category_snapshot`
   - `standard_balance_direction_snapshot`
   - `client_account_code`
   - `client_account_name`
   - `fiscal_year`
   - `period`
   - `opening_debit`
   - `opening_credit`
   - `current_debit`
   - `current_credit`
   - `ending_debit`
   - `ending_credit`
   - `created_at`
6. 补齐必要索引和唯一约束：
   - 标准科目代码唯一。
   - 映射经验按数据类型、客户标识、客户科目代码/名称建立检索索引。
   - 标准余额表按批次、标准科目、年度、期间建立检索索引。
7. 后端测试覆盖模型创建、字段默认值、标准科目停用状态、标准余额表快照字段。

## 验收
- `D:\python\python.exe -m pytest`
- `D:\python\python.exe -m compileall backend/app`
- `git diff --check -- backend docs`

## 完成回报要求
- 列出新增表和关键字段。
- 说明是否使用迁移文件；如果没有，说明项目当前采用的建表方式。
- 贴出测试命令结果。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 20:15

### 修改文件

- `backend/app/models/standard_account.py` — 新增：标准科目模型 StandardAccount
- `backend/app/models/client_account_mapping.py` — 新增：客户科目映射经验模型 ClientAccountMapping
- `backend/app/models/standard_trial_balance_import_batch.py` — 新增：标准化导入批次模型 StandardTrialBalanceImportBatch
- `backend/app/models/standard_trial_balance_raw_row.py` — 新增：原始行快照模型 StandardTrialBalanceRawRow
- `backend/app/models/standard_trial_balance_entry.py` — 新增：标准科目余额表明细模型 StandardTrialBalanceEntry
- `backend/app/models/__init__.py` — 修改：导出 5 个新模型
- `backend/app/schemas/standard_trial_balance.py` — 新增：6 类 Schema（Create/Update/Response/ListResponse）
- `backend/alembic/versions/20260622_0002_add_standard_trial_balance_tables.py` — 新增：Alembic 迁移文件
- `backend/tests/test_standard_trial_balance_models.py` — 新增：32 个测试用例
- `docs/tasks/TASK-039-standard-trial-balance-model-foundation.md` — 修改：状态更新

### 完成内容

#### 新增 5 张表

| 表名 | 关键字段 | 唯一约束/索引 |
| --- | --- | --- |
| `standard_accounts` | `account_code`(unique), `account_name`, `account_category`, `balance_direction`, `level`, `parent_id`(自引用FK), `is_leaf`, `is_active`, `source_row_index` | `account_code` unique; `is_active` index |
| `client_account_mappings` | `data_type`, `customer_label`, `client_account_code`, `client_account_name`, `normalized_client_account_name`, `standard_account_id`(FK), `confidence`, `scope`, `usage_count`, `last_used_at`, `is_active` | `data_type`/`customer_label`/`client_account_code`/`standard_account_id`/`is_active` index |
| `standard_trial_balance_import_batches` | `file_name`, `customer_label`, `source_label`, `fiscal_year`, `period`, `status`, `field_mapping`(JSON), `amount_mapping_config`(JSON), `hierarchy_config`(JSON), `warnings`(JSON), `errors`(JSON) | `status` index |
| `standard_trial_balance_raw_rows` | `batch_id`(FK), `row_index`, `raw_values`(JSON), `client_account_code`, `client_account_name`, `client_balance_direction`, `client_account_category`, `detected_level`, `parent_raw_row_id`(自引用FK), `is_leaf`, `mapped_standard_account_id`(FK), `mapping_status`, `warnings`(JSON) | `batch_id` index |
| `standard_trial_balance_entries` | `batch_id`(FK), `raw_row_id`(FK), `standard_account_id`(FK), `*_snapshot`×4, `client_account_code`, `client_account_name`, `fiscal_year`, `period`, `opening_debit/credit`, `current_debit/credit`, `ending_debit/credit` | `batch_id`/`standard_account_id` index |

#### 建表方式

项目使用双重建表机制：
1. **运行期建表**：`app/main.py` lifespan 中调用 `Base.metadata.create_all()` —— 新模型在 `app/models/__init__.py` 导入后自动注册到 `Base.metadata`，下次启动自动建表。
2. **Alembic 迁移**：本次同步创建了迁移文件 `20260622_0002`（链在 `20260622_0001` 之后），含完整 `upgrade()`/`downgrade()`。

#### 测试覆盖（32 个测试，全部通过）

- **StandardAccount** (7): 创建、唯一约束、默认值、停用/启用切换、父子层级、NULL 可选字段、`__repr__`
- **ClientAccountMapping** (7): 创建含 FK、默认值、使用计数/最后使用时间、scope 枚举、停用切换、三种数据类型、`__repr__`
- **StandardTrialBalanceImportBatch** (5): 创建、默认值、状态流转、JSON 配置字段、`__repr__`
- **StandardTrialBalanceRawRow** (7): 创建含 FK、默认值、映射状态枚举、关联标准科目、父子层级、警告字段、`__repr__`
- **StandardTrialBalanceEntry** (6): 创建含 FK 和金额、金额默认值=0、快照不受标准科目后续变更影响、关联原始行、Numeric(20,2) 精度、`__repr__`

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m compileall app
D:\python\python.exe -m pytest
```

结果：

- `compileall`：通过，所有新模型和 Schema 编译成功。
- `pytest`：**198 passed**（166 已有 + 32 新增），3 warnings（均为已有代码的 Pydantic v2 弃用和 `utcnow` 弃用警告，非本次引入）。
- `git diff --check -- backend docs`：通过（仅有 CRLF 换行符警告）。

### 风险和后续

- 无阻塞项。
- 5 张新表通过 `create_all` + Alembic 迁移双通道建表；依赖于本任务的 `TASK-040`、`TASK-042`、`TASK-043`、`TASK-046` 可以并行开工。
- 模型中的 FK 关系使用了 `ondelete="SET NULL"` / `"CASCADE"` / `"RESTRICT"`，后续实现 Service 层时需注意级联删除行为。
