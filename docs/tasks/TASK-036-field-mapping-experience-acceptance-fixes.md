# TASK-036：字段映射经验库验收阻塞修复

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 20:00
完成时间：2026-06-22 20:20

## 背景

总指挥复验 `TASK-031` 到 `TASK-035` 时，基础测试和构建通过，但发现字段映射经验库仍有验收阻塞项。

本任务只修复验收发现的问题，不新增财务软件识别、布局指纹识别、数据清洗规则、科目标准化映射或新的训练页面。

## 目标

修复字段映射经验推荐的隔离、安全、可部署性和前端确认记录问题，让 `TASK-035` 的验收场景可以真实通过。

## 允许修改范围

可以修改：

- `backend/app/services/mapping_experience_service.py`
- `backend/app/services/import_service.py`
- `backend/app/api/imports.py`
- `backend/alembic/versions/20260622_0001_add_field_mapping_experiences.py`
- `backend/tests/`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

不要修改其他业务模块。若确实必须扩大范围，先把原因写入本任务的 `BLOCKED` 回报，不要擅自扩范围。

## 必须修复

1. 经验推荐隔离：
   - 查询经验时只能使用当前 `company_id` 的经验和全局经验。
   - 其他单位的私有经验不得被当成 `global_experience`。
   - 未传 `company_id` 时，只允许使用全局经验，不得读取任意单位经验。
2. 推荐排序必须确定：
   - 优先级为：当前单位 + 上下文命中、全局 + 上下文命中、当前单位 + 非歧义表头、全局 + 非歧义表头。
   - 同一优先级内按 `success_count` 降序，再按 `updated_at` 降序。
   - 歧义表头 header-only 经验不得高置信自动填入。
3. Alembic 迁移必须真实可用：
   - `upgrade()` 创建 `field_mapping_experiences` 表和必要索引。
   - `downgrade()` 删除表或索引。
   - 不得继续使用空 `pass` 迁移。
4. 模板优先语义：
   - 显式套用模板后，模板映射不得被经验覆盖。
   - 如需要在 `mapping_suggestions_v2` 标记模板来源，必须以实际模板映射为准，而不是只改已有经验建议的 `source`。
5. 前端推荐展示：
   - 映射表必须显示推荐来源中文文案。
   - 映射表必须显示置信度，例如 `100%`、`85%`。
   - 用户修改后显示“用户手动修改”或等价中文状态。
6. 前端确认记录：
   - `original_field_key` 必须记录实际自动填入的推荐字段。
   - 用户未修改自动推荐时提交 `confirmation_type=user_confirmed`。
   - 用户修改推荐，或原本没有自动推荐但用户手动选择时，提交 `confirmation_type=user_corrected`。
   - 忽略列不提交 `mapping_confirmations`。
7. 看板收口：
   - 更新 `docs/COMMAND_CENTER.md`，把本轮验收结论和 `TASK-036` 状态登记清楚。
   - 修正旧的“推荐执行顺序”不要再指向 `TASK-031` 到 `TASK-035`。

## 必须补充测试

后端至少覆盖：

1. A 单位私有经验不得推荐给 B 单位。
2. A 单位私有经验不得在无 `company_id` 预览时被当成全局经验。
3. 全局经验可以在任意单位命中。
4. 同表头多条经验按优先级和 `success_count/updated_at` 确定选择。
5. 歧义表头只有 header-only 经验时不自动高置信推荐。
6. 显式模板映射优先于经验推荐。

前端至少覆盖人工或自动检查：

1. 推荐来源中文可见。
2. 置信度中文界面可见。
3. 自动推荐未修改时确认为 `user_confirmed`。
4. 修改推荐或手动选择时确认为 `user_corrected`。

## 总指挥已复现的阻塞脚本

当前实现会把 A 单位私有经验泄漏给 B 单位和无单位预览。修复后，以下脚本的 `company_b` 和 `no_company` 不得返回 A 单位经验。

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
@'
import asyncio, uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.database import Base
import app.models
from app.models.field_mapping_experience import FieldMappingExperience
from app.services.mapping_experience_service import (
    normalize_header,
    build_context_signature,
    build_lookup_key,
    recommend_from_experience,
)
from app.services.file_parser import build_columns

async def main():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        company_a = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        company_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        headers = ["凭证号", "凭证日期", "摘要", "科目编码", "科目名称"]
        columns = build_columns(headers)
        nh = normalize_header("摘要")
        ctx = build_context_signature(headers, 2)
        db.add(FieldMappingExperience(
            company_id=company_a,
            data_type="journal",
            source_header_original="摘要",
            source_header_normalized=nh,
            source_column_index=2,
            context_signature=ctx,
            target_field="summary",
            confirmation_type="user_confirmed",
            lookup_key=build_lookup_key(company_a, "journal", "", "", nh, ctx),
            use_count=5,
            success_count=5,
            is_active=True,
        ))
        await db.flush()

        for label, cid in [("company_b", company_b), ("no_company", None)]:
            suggestions = await recommend_from_experience(db, cid, "journal", columns)
            print(label, suggestions)

asyncio.run(main())
'@ | D:\python\python.exe -
```

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
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend frontend docs .gitignore
```

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
