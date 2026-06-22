# TASK-038：取消套用模板后的确认基准修复

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 21:00
完成时间：2026-06-22 21:05

## 背景

总指挥复验 `TASK-037` 时，后端模板建议补齐已经通过，前端套用模板后也能显示 `导入模板 / 100%` 并把 `original_field_key` 设置为模板字段。

剩余阻塞在取消套用模板：

```ts
if (m.suggestion_source === 'template') {
  m.suggestion_source = undefined
  m.suggestion_confidence = undefined
  m.original_field_key = m.field_key
}
```

这会导致用户取消模板后，如果保留当前字段选择并直接导入，该列仍提交 `confirmation_type=user_confirmed`。但取消模板后已经没有模板推荐语义，保留字段应按手动映射处理，不能误记为“确认了模板推荐”。

## 目标

修复取消套用模板后的确认基准：取消后不再显示模板来源，也不再把模板字段当作自动推荐基准。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

不要修改后端、模板匹配评分、导入服务或经验保存策略。若必须扩大范围，先把原因写入本任务的 `BLOCKED` 回报。

## 必须修复

1. `cancelTemplateApply()` 清除模板来源：
   - `suggestion_source` 清空。
   - `suggestion_confidence` 清空。
   - 不再把 `original_field_key` 设置为当前 `field_key`。
2. 取消模板后如果保留当前字段选择：
   - 执行导入时该列必须提交 `confirmation_type=user_corrected`。
   - 不得提交为 `user_confirmed`。
3. 如果用户取消模板后继续手动修改字段：
   - 仍提交 `confirmation_type=user_corrected`。
4. 若实现选择恢复套用模板前的映射快照，也可以接受，但必须满足：
   - 不显示“导入模板”。
   - 不把已取消的模板推荐作为确认基准。
   - 不破坏此前已有的取消模板默认值清理逻辑。

## 建议实现

最小实现可以在取消模板时将模板来源行的 `original_field_key` 置为 `null`：

```ts
m.suggestion_source = undefined
m.suggestion_confidence = undefined
m.original_field_key = null
```

这样保留当前字段并执行时，现有逻辑会把该列判定为 `user_corrected`。

## 必须验收

1. 套用模板后，映射表显示“导入模板”和 `100%`。
2. 取消套用模板后，映射表不再显示“导入模板”和 `100%`。
3. 取消后不改字段直接执行，`mapping_confirmations[col_id].confirmation_type` 为 `user_corrected`。
4. 取消后再手动改字段执行，`confirmation_type` 仍为 `user_corrected`。
5. 取消套用模板后，`selectedTemplateId` 和 `templateDefaultValues` 仍被清空。

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
