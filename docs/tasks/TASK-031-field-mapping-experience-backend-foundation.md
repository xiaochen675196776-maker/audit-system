# TASK-031：字段映射经验库后端基础

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 18:00
完成时间：2026-06-22 18:15

## 目标

新增“字段映射经验库”的数据库模型、迁移和核心服务函数。第一版只记录用户确认过的逐列字段映射经验，不修改导入执行流程，不改前端。

经验库和 `ImportTemplate` 的边界必须清楚：

- `ImportTemplate`：整张表模板，负责表头行、数据起始行、编码、默认年度/期间、完整列映射。
- `FieldMappingExperience`：逐列经验，负责“某客户/全局曾确认过某个表头在某种上下文中映射到哪个标准字段”。

## 允许修改范围

可以修改：

- `backend/app/models/`
- `backend/app/services/mapping_experience_service.py`
- `backend/alembic/versions/`
- `backend/tests/`

如果必须修改范围外文件，先把任务状态改为 `BLOCKED` 并说明原因。

## 数据模型要求

新建 `backend/app/models/field_mapping_experience.py`，注册到 `backend/app/models/__init__.py`。

字段：

- `id`
- `company_id`，可空，空表示全局经验
- `data_type`
- `software_code`，预留，默认空字符串
- `layout_fingerprint`，预留，默认空字符串
- `source_header_original`
- `source_header_normalized`
- `source_column_index`
- `context_signature`
- `target_field`
- `confirmation_type`：`user_confirmed` / `user_corrected` / `system_reused`
- `lookup_key`
- `use_count`
- `success_count`
- `conflict_count`
- `is_active`
- `last_used_at`
- `created_at`
- `updated_at`

关键约束：

1. 不要给 `lookup_key` 加唯一约束。冲突处理需要同一 `lookup_key` 下保留历史停用记录。
2. 增加索引：
   - `company_id`
   - `data_type`
   - `source_header_normalized`
   - `lookup_key`
   - `is_active`
3. 增加 Alembic 迁移：`backend/alembic/versions/20260622_0001_add_field_mapping_experiences.py`。

## 服务函数要求

新建 `backend/app/services/mapping_experience_service.py`，至少实现：

```python
def normalize_header(value: str | None) -> str: ...
def build_context_signature(headers: list[str], column_index: int) -> str: ...
def build_lookup_key(
    company_id: uuid.UUID | None,
    data_type: str,
    software_code: str,
    layout_fingerprint: str,
    source_header_normalized: str,
    context_signature: str,
) -> str: ...
def is_ambiguous_header(normalized_header: str) -> bool: ...
```

`normalize_header()` 必须：

- 使用 `unicodedata.normalize("NFKC", text)`
- 去除首尾空白
- 转小写
- 去除换行、回车和连续空白
- 去除常见中英文括号、冒号、逗号、顿号、句号、点、下划线、短横线

`build_context_signature()` 必须使用“前一列 + 当前列 + 后一列”的标准化表头生成 sha256。

`is_ambiguous_header()` 第一版至少把以下标准化表头视为歧义：

```text
借
借方
贷
贷方
余额
本期
期初
期末
发生额
```

歧义表头后续只能在上下文匹配时高置信推荐，不能只靠 header-only 自动推荐。

## 必须测试

新增或修改后端测试，覆盖：

1. `normalize_header(" 本币期间异动(借) ") == "本币期间异动借"`。
2. 全角字符和英文大小写被稳定规范化。
3. `build_context_signature()` 对同一组三列表头稳定，对相邻列变化敏感。
4. `build_lookup_key()` 对不同 `company_id`、`data_type`、`context_signature` 生成不同值。
5. `lookup_key` 不唯一：同一 `lookup_key` 可以存在一条 active 和一条 inactive 历史记录。
6. Alembic 迁移能通过模型元数据测试，`Base.metadata.create_all()` 能创建新表。

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
