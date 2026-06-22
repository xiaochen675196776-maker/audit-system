# TASK-035：字段映射经验库总体验收

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 19:00
完成时间：2026-06-22 19:15

## 前置依赖

必须等待 `TASK-031`、`TASK-032`、`TASK-033`、`TASK-034` 全部完成并通过总指挥验收。

## 目标

对字段映射经验库做总体验收和最小回归修复。只修验收发现的问题，不新增新功能。

## 允许修改范围

可以修改：

- 前面任务涉及的后端和前端文件
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

不要新增财务软件识别、布局指纹识别、数据清洗、科目标准化映射、正式数据表改造。

## 必须验收场景

1. 首次形成经验：
   - 上传科目余额表合成样本。
   - 用户把 `会计科目` 映射为 `account_name`。
   - 导入成功后新增公司级经验。
2. 再次自动推荐：
   - 同一公司再次上传相似样本。
   - 预览返回 `mapping_suggestions_v2`。
   - `会计科目` 自动推荐为 `account_name`，来源为“该客户历史确认”。
3. 用户纠正错误经验：
   - 旧经验 `借方 -> debit_amount`。
   - 用户改为 `借方 -> opening_debit`。
   - 导入成功后旧经验停用并增加冲突，新经验 active。
4. 关闭记忆：
   - `remember_mapping=false`。
   - 导入成功但不新增经验。
5. 导入失败：
   - 成功行数为 0。
   - 不新增经验。
6. 歧义字段安全：
   - 只有 header-only 的 `借方` 经验时，不得自动高置信填入。
   - 有上下文命中时才允许高置信推荐。
7. 模板优先：
   - 显式套用模板后，模板映射不能被经验覆盖。
8. 重复表头：
   - 两个 `摘要` 或两个 `说明` 能通过 `column_id` 区分。
9. 回归：
   - 原导入模板库功能仍可用。
   - 无经验库数据时，导入页仍能手动映射和执行导入。

## 最终验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m compileall app
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend frontend docs .gitignore
```

## 浏览器验收

启动后端和前端，至少打开并操作：

```text
http://127.0.0.1:5173/data/import
```

检查：

- 推荐来源中文可见。
- 记忆开关中文可见。
- 无控制台错误。
- 取消套用模板后默认值不残留。

## 文档收口

更新 `docs/COMMAND_CENTER.md`：

- 登记 `TASK-031` 到 `TASK-035` 的验收结论。
- 记录最终命令结果。
- 标明字段映射经验库第一版范围：只做逐列字段经验，不做清洗、布局指纹、软件识别、科目标准化。

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
