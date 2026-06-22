# TASK-034：导入页接入字段映射经验推荐

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 18:45
完成时间：2026-06-22 19:00

## 前置依赖

必须等待 `TASK-032` 和 `TASK-033` 完成并通过总指挥验收。

## 目标

前端导入页展示字段推荐来源，记录用户确认或修改，并在执行导入时把确认信息提交给后端保存经验。

本任务不新增单独的“训练系统”页面。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/`
- `frontend/src/utils/error.ts`
- `docs/tasks/`

不要修改后端。

## 前端契约

`ImportPreviewResponse` 增加：

```ts
mapping_suggestions_v2?: Record<string, {
  target_field: string
  source: 'template' | 'company_experience' | 'global_experience' | 'keyword_match'
  confidence: number
  experience_id?: string
}>
```

`MappingRow` 增加：

```ts
column_id: string
column_index: number
suggestion_source?: string
suggestion_confidence?: number
original_field_key?: string | null
```

构造映射行时必须以 `data.columns` 为主，不再只用 `headers.map()`。

## 交互要求

1. 预览请求必须传入 `company_id`。
2. 映射表显示推荐来源：
   - `template`：导入模板
   - `company_experience`：该客户历史确认
   - `global_experience`：通用历史经验
   - `keyword_match`：系统字段识别
   - 用户修改后显示：用户手动修改
3. 映射表显示置信度，例如 `100%`、`85%`。
4. 只自动填入 `confidence >= 0.85` 的建议。
5. `confidence < 0.85` 的建议只展示来源和候选，不自动把字段选中。
6. 用户没有修改原推荐：提交 `confirmation_type=user_confirmed`。
7. 用户修改推荐，或原本没有推荐但用户手动选择：提交 `confirmation_type=user_corrected`。
8. 忽略列不提交 `mapping_confirmations`。
9. 增加复选框：

```text
记住本次字段映射，下次自动推荐
```

默认勾选，对应 `remember_mapping=true`。

## 执行请求要求

`goExecute()` 追加：

```text
remember_mapping
mapping_confirmations
```

`mapping_confirmations` 必须以 `column_id` 为 key。不得用表头文本当 key。

已确认套用模板时，仍必须保留现有 `template_id` 提交流程；不得破坏 `templateDefaultValues` 清理逻辑。

## 必须验收

1. `npm run build` 通过。
2. 页面无英文裸露文案。
3. 重复表头时，确认信息使用不同 `column_id`。
4. 取消套用模板后，不残留模板默认值。
5. 无经验时仍能走关键词匹配和手动映射。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- frontend docs
```

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
