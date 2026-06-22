# TASK-022：模板匹配与预览集成

状态：OPEN
执行者：
开始时间：
完成时间：

## 目标

上传文件预览时自动推荐导入模板，并在用户确认后可套用模板映射。

本任务只做后端模板匹配和预览集成，不做前端展示。

## 前置依赖

- 必须等待 `TASK-020` 完成并验收。
- 建议等待 `TASK-021` 完成并验收；如果 `TASK-021` 尚未完成，本任务应标记 `BLOCKED`。
- 开始前阅读 `docs/COMMAND_CENTER.md` 和本任务。
- 开始前运行 `git status --short`。

## 允许修改范围

可以修改：

- `backend/app/services/`
- `backend/app/api/imports.py`
- `backend/app/api/import_templates.py`（如果已存在）
- `backend/tests/`

不要修改：

- 前端
- ORM 字段结构，除非 `TASK-021` 已留下明确缺口并经总指挥确认
- `docs/UI_OPTIMIZATION_PLAN.md`

## 必须完成

1. 实现表头指纹，基于：
   - 规范化表头
   - 列顺序
   - 重复表头序号
2. 模板匹配评分：
   - 完全一致返回 100。
   - 相似表头按字段覆盖率和 Jaccard 相似度评分。
   - 缺必填字段、重复列冲突、数据类型不一致必须降分并给出中文 warnings。
3. `/imports/preview` 返回 `template_candidates`，每个候选至少包含：
   - `template_id`
   - `name`
   - `score`
   - `matched_fields`
   - `missing_fields`
   - `warnings`
4. `/imports/preview` 支持可选 `template_id`：
   - 指定模板时返回套用模板后的 `column_mapping_v2` 草稿。
   - 指定模板不存在、停用或数据类型不一致时返回中文错误。
5. 增加负向匹配规则：
   - `本币期间异动(借)` / `本币期间异动(贷)` 不能识别为 `period`。
   - `本币本年累计(借)` / `本币本年累计(贷)` 不能识别为 `fiscal_year`。
6. 对真实样本暴露的重复表头形态给出解释性 warning，而不是静默错配。

## 必须测试

后端测试至少覆盖：

1. 完全一致模板命中 100 分。
2. 相似表头模板返回中等分数和中文 warnings。
3. 必填字段缺失会降分。
4. 10 列科目余额表合成样本不误判年度/期间。
5. 74 列序时账合成样本能识别核心字段，并对重复表头给 warning。
6. 指定 `template_id` 能返回 `column_mapping_v2` 草稿。

测试样本必须合成生成。

## 验收命令

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
