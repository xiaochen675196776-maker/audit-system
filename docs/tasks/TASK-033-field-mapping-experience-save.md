# TASK-033：执行导入后保存字段映射经验

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 18:30
完成时间：2026-06-22 18:45

## 前置依赖

必须等待 `TASK-031` 完成并通过总指挥验收。建议在 `TASK-032` 之后执行，避免同时修改 `imports.py` 和 `import_service.py`。

## 目标

导入执行成功后，根据用户确认信息保存字段映射经验。不得在预览阶段保存经验。

保存时点必须是：

```text
用户确认映射
→ 执行导入
→ 校验完成
→ 成功写入至少一行
→ 保存经验
```

## 允许修改范围

可以修改：

- `backend/app/api/imports.py`
- `backend/app/services/import_service.py`
- `backend/app/services/mapping_experience_service.py`
- `backend/tests/`

不要修改前端。

## API 契约

`POST /api/v1/imports/execute` 增加表单参数：

```python
remember_mapping: bool = Form(True, description="是否保存本次用户确认的字段映射经验")
mapping_confirmations: str | None = Form(None, description="用户确认信息 JSON")
```

`mapping_confirmations` JSON 格式：

```json
{
  "col_001": {
    "target_field": "account_name",
    "confirmation_type": "user_confirmed"
  },
  "col_002": {
    "target_field": "current_debit",
    "confirmation_type": "user_corrected"
  }
}
```

无效 JSON 返回中文 400：

```text
mapping_confirmations JSON 格式无效
```

## 服务规则

`import_data()` 增加参数：

```python
remember_mapping: bool = True
mapping_confirmations: dict | None = None
```

新增：

```python
async def save_mapping_experiences(
    db: AsyncSession,
    company_id: uuid.UUID,
    data_type: str,
    columns: list[dict],
    mapping_confirmations: dict,
) -> None: ...
```

保存规则：

1. `success_count == 0` 不保存。
2. `remember_mapping is False` 不保存。
3. 没有 `mapping_confirmations` 不保存。
4. `target_field` 为 `ignore`、`__ignore__`、空值，不保存。
5. 原始表头为空，不保存。
6. `confirmation_type` 不在 `user_confirmed/user_corrected`，不保存。
7. `target_field` 不在当前 `data_type` 的 `TYPE_FIELDS` 中，不保存。第一版不保存辅助字段经验。
8. 同一 `lookup_key` 下 active 经验目标字段相同：`use_count += 1`、`success_count += 1`、更新 `last_used_at`。
9. 同一 `lookup_key` 下 active 经验目标字段不同：旧 active 记录 `use_count += 1`、`conflict_count += 1`、`is_active=False`；新增一条 active 的 `user_corrected` 经验。
10. 无历史记录：新增 active 经验，`use_count=1`、`success_count=1`、`conflict_count=0`。

## 必须测试

后端测试覆盖：

1. 首次成功导入后新增公司级经验。
2. 同一映射再次成功导入后累加 `use_count/success_count`。
3. 用户纠正旧经验时，旧经验停用并增加 `conflict_count`，新经验 active。
4. `remember_mapping=false` 不保存。
5. 成功行数为 0 不保存。
6. `ignore`、空表头、未确认类型、辅助字段、自定义字段不保存。
7. `mapping_confirmations` 非法 JSON 返回中文 400。
8. 使用模板 `parse_config` 导入时，保存经验使用模板解析后的真实列和表头。

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
