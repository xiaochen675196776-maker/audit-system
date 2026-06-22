# TASK-030：取消套用模板后的默认值状态清理

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 17:15
完成时间：2026-06-22 17:25

## 背景

`TASK-029` 复验未通过。确认套用模板后的最终导入链路已经能把 `template_id` 提交给 `/imports/execute`，后端也能按模板 `parse_config` 和 `default_values` 完成导入。

但前端存在状态残留：

- 点击“取消套用”时只清空 `selectedTemplateId`，没有清空 `templateDefaultValues`。
- 重新预览普通文件时会清空 `selectedTemplateId`，但也没有清空 `templateDefaultValues`。

这会导致前端 `mappingValid` 继续把旧模板默认年度/期间当作有效补齐来源；最终执行导入时因为没有提交 `template_id`，后端不会使用这些默认值，可能出现“前端允许开始导入，后端又报缺少年度/期间”的断链。

## 目标

清理导入页模板状态残留，确保只有当前已确认套用的模板默认值才参与前端校验。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

不要修改：

- 后端模板匹配和导入逻辑，除非验收复现直接证明仍有后端问题。
- 模板管理页。
- 与导入模板库无关的 UI。

## 必须交付

1. 新增明确的取消套用方法，例如 `cancelTemplateApply()`。
2. 点击“取消套用”时必须同时清空：
   - `selectedTemplateId`
   - `templateDefaultValues`
3. 重新执行普通预览 `goPreview()` 时必须清空旧的 `templateDefaultValues`。
4. 套用模板失败时必须清空旧的 `templateDefaultValues`。
5. `mappingValid` 只能在 `selectedTemplateId` 存在且 `templateDefaultValues` 属于当前模板时，才使用模板默认年度/期间补齐。
6. 不改变用户已经手动调整的列映射；取消模板只取消模板身份和模板默认值。

## 验收

必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- frontend docs
```

手工或浏览器验收：

1. 套用一个带 `default_values.fiscal_year/period` 的模板。
2. 不填写年度/期间，确认“开始导入”可用。
3. 点击“取消套用”。
4. 期望：模板默认值不再参与校验；如果文件和手工输入都没有年度/期间，不能开始导入。
5. 再重新预览一个普通文件，确认旧模板默认值不会残留。

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。

## 总指挥验收结论

- 验收日期：2026-06-22
- 结论：通过。
- 验收结果：
  - `npm run build`：通过。
  - `git diff --check -- frontend docs`：通过。
  - `D:\python\python.exe -m pytest`：通过，134 passed。
  - `D:\python\python.exe -m compileall app`：通过。
  - `git diff --check -- backend frontend docs .gitignore`：通过。
  - 浏览器烟测：`/data/import`、`/data/templates` 可打开，无控制台错误。
- 复核点：
  - 点击“取消套用”会同时清空 `selectedTemplateId` 和 `templateDefaultValues`。
  - 重新普通预览会清空旧模板默认值。
  - 套用模板失败会清空旧模板默认值。
  - `mappingValid` 只有在仍选中模板时才使用模板默认年度/期间补齐。
