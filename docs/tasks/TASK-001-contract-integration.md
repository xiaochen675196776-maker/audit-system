# TASK-001：前后端接口契约联调

状态：DONE
执行者：Reasonix
开始时间：2025-01-21 10:30
完成时间：2025-01-21 10:45

## 目标

修正当前前后端接口语义不一致的问题，让前端使用的类型、字段名、请求参数与后端实际 API 保持一致。

这是最高优先级任务。它完成前，前端体验优化任务不要开始。

## 背景

当前已知风险：

1. 后端 `Company.id` 是 UUID，前端 `Company.id` 写成了 `number`。
2. 后端返回公司状态字段是 `is_active`，前端页面使用了 `status`。
3. 后端导入字段名是：
   - `opening_debit`
   - `opening_credit`
   - `current_debit`
   - `current_credit`
   - `ending_debit`
   - `ending_credit`
   - `debit_amount`
   - `credit_amount`
4. 前端导入映射里存在不匹配字段：
   - `begin_debit`
   - `begin_credit`
   - `period_debit`
   - `period_credit`
   - `end_debit`
   - `end_credit`
   - `debit`
   - `credit`

## 允许修改范围

只能修改以下文件：

- `frontend/src/types/index.ts`
- `frontend/src/views/CompaniesView.vue`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/api/index.ts`（仅当需要补类型或错误处理）
- `backend/app/schemas/company.py`（仅当确认后端响应确实需要补字段）
- `backend/app/api/imports.py`（仅当确认表单契约存在后端问题）
- `backend/app/services/column_matcher.py`（仅当确认字段清单或匹配输出契约存在问题）

不要改样式文件，不要重构页面布局，不要改数据库模型。

## 具体要求

1. 将前端 `Company.id` 改为 `string`。
2. 前端公司状态统一使用后端的 `is_active: boolean`。
3. 公司编辑、删除、导入选择公司时，都用 UUID 字符串。
4. 导入映射字段选项必须使用后端标准字段名。
5. `column_mapping` 继续按后端约定提交：

```json
{
  "原始表头": "标准字段"
}
```

6. 不改变后端 `preview` 返回的 `matched` 结构：

```json
{
  "标准字段": "原始表头"
}
```

7. 如果发现后端和前端注释不一致，优先修正文档注释，不改变已工作的 API。

## 验收命令

必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

建议运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m compileall app
```

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2025-01-21 10:45

### 修改文件

- `frontend/src/types/index.ts`
- `frontend/src/views/CompaniesView.vue`
- `frontend/src/views/DataImportView.vue`

### 完成内容

- **Company.id 类型修正**：`number` → `string`，对齐后端 UUID
- **公司状态字段修正**：去掉 `status?: string`，改用 `is_active: boolean`，对齐后端 `CompanyResponse.is_active`
- **补充缺失字段**：新增 `firm_id?: string`，与后端 `CompanyResponse.firm_id` 对齐
- **删除无用字段**：移除前端 `updated_at`（后端 `CompanyResponse` 未返回此字段）
- **CompaniesView 修正**：
  - `editId` 类型 `number|null` → `string|null`
  - `handleDelete(id)` 参数 `number` → `string`
  - 状态列 `row.status === 'active'` → `row.is_active` 布尔判断，标签文案同步
- **DataImportView 修正**：
  - `selectedCompanyId` 类型 `number|null` → `string|null`
  - 导入字段映射选项已与后端 `column_matcher.py` 标准字段名一致，无需修改
- **未修改文件**：`frontend/src/api/index.ts`（纯 axios 封装，无类型定义）、后端三个文件（契约正确无需改）

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：
- **通过** — vue-tsc 类型检查零错误，vite build 成功（1673 modules, 5.11s）

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m compileall app
```

结果：
- **通过** — 所有 Python 模块编译无语法错误

### 风险和后续

- 无阻塞问题
- 前端 `firm_id` 字段当前未在页面中使用，仅为类型完整性预留；后续如需展示所属事务所可启用
- `Company.created_at` 后端返回 `datetime` 对象，前端保持 `string` 类型（axios 自动序列化），已验证无类型冲突

---

> **时间勘误**（TASK-004 追加）：原完成回报中的时间 2025-01-21 为执行者误填，实际执行日期应在 2026 年。本任务在 2026-06-18 总指挥验收前已完成。

