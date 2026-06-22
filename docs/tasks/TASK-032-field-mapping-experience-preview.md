# TASK-032：预览阶段接入字段映射经验推荐

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 18:15
完成时间：2026-06-22 18:30

## 前置依赖

必须等待 `TASK-031` 完成并通过总指挥验收。

## 目标

在 `/imports/preview` 阶段查询字段映射经验，返回按 `column_id` 标识的 `mapping_suggestions_v2`。本任务只做推荐，不保存经验。

推荐合并优先级：

```text
已显式套用的完整模板
→ 字段映射经验
→ 固定关键词匹配
```

模板映射不能被经验覆盖；经验推荐不能被关键词覆盖。

## 允许修改范围

可以修改：

- `backend/app/api/imports.py`
- `backend/app/services/import_service.py`
- `backend/app/services/mapping_experience_service.py`
- `backend/tests/`

不要修改前端，不要保存经验。

## API 契约

`POST /api/v1/imports/preview` 增加表单参数：

```python
company_id: str | None = Form(None, description="被审计单位ID，用于查询历史字段映射经验")
```

无效 `company_id` 返回中文 400：

```text
无效的公司 ID
```

返回新增：

```json
{
  "mapping_suggestions_v2": {
    "col_001": {
      "target_field": "account_name",
      "source": "company_experience",
      "confidence": 1.0,
      "experience_id": "..."
    },
    "col_002": {
      "target_field": "opening_debit",
      "source": "keyword_match",
      "confidence": 0.85
    }
  }
}
```

允许的 `source`：

- `template`
- `company_experience`
- `global_experience`
- `keyword_match`

## 服务规则

在 `mapping_experience_service.py` 中新增：

```python
async def recommend_from_experience(
    db: AsyncSession,
    company_id: uuid.UUID | None,
    data_type: str,
    columns: list[dict],
) -> dict[str, dict]: ...
```

查询优先级：

1. 同一客户 + 同一数据类型 + 相同标准化表头 + 相同上下文，`confidence=1.0`
2. 全局经验 + 同一数据类型 + 相同标准化表头 + 相同上下文，`confidence=0.9`
3. 同一客户 + 同一数据类型 + 相同标准化表头，非歧义表头才允许，`confidence=0.85`
4. 全局经验 + 同一数据类型 + 相同标准化表头，非歧义表头才允许，`confidence=0.75`

歧义表头必须有上下文命中才允许 `confidence >= 0.85`。如果只有 header-only 命中歧义表头，不得自动填入建议。

关键词匹配必须按 `column_id` 生成，不得用 `headers.index()` 或表头文本反查。重复表头时只给实际命中的列生成建议。

## 必须测试

后端测试覆盖：

1. 同客户上下文经验优先于全局经验。
2. 全局上下文经验可推荐。
3. 非歧义表头允许 header-only 经验推荐。
4. 歧义表头 `借方` 只有 header-only 经验时不得自动推荐。
5. 显式套用模板时，`mapping_suggestions_v2` 中模板字段 source 为 `template`，且经验不能覆盖模板字段。
6. 没有经验时仍返回关键词建议，source 为 `keyword_match`。
7. 预览接口传入非法 `company_id` 返回中文 400。
8. 重复表头场景下，推荐按 `col_00x` 命中正确列。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m compileall app
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend docs
```

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
