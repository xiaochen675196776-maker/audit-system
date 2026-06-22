# TASK-037：模板套用来源与确认记录收口

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 20:30
完成时间：2026-06-22 20:45

## 背景

总指挥复验 `TASK-036` 时，字段映射经验隔离、排序、迁移、基础测试和构建已通过，但模板套用的来源展示和确认记录仍未闭环。

复现结果：

```text
applied_mapping_v2 {'col_001': 'voucher_no', 'col_002': 'voucher_date', 'col_003': 'summary'}
mapping_suggestions_v2 {}
```

这说明指定 `template_id` 预览时，后端虽然返回了模板映射，但没有把模板映射按 `mapping_suggestions_v2` 的契约补齐为 `source=template`。前端 `applyTemplateCandidate()` 也只更新了 `field_key/status`，没有把行来源、置信度和 `original_field_key` 更新为模板推荐。

## 目标

修复显式套用模板后的推荐来源、置信度和确认类型记录，使模板映射在预览、展示、执行确认三个环节语义一致。

## 允许修改范围

可以修改：

- `backend/app/services/import_service.py`
- `backend/tests/`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

不要修改模板匹配评分、模板 CRUD、字段经验保存策略或其他业务模块。若必须扩大范围，先把原因写入本任务的 `BLOCKED` 回报。

## 必须修复

1. 后端模板建议补齐：
   - `/imports/preview` 指定 `template_id` 且成功生成 `applied_mapping_v2` 时，`mapping_suggestions_v2` 必须包含每个模板映射列：
     ```json
     {
       "col_001": {
         "target_field": "voucher_no",
         "source": "template",
         "confidence": 1.0
       }
     }
     ```
   - 模板建议必须优先于经验建议和关键词建议。
   - 模板列以外的列可以继续保留经验建议；无经验时可以保留关键词兜底建议。
   - 即使未传 `company_id`，指定模板预览也要返回模板来源建议。
2. 前端套用模板后更新映射行元数据：
   - `field_key` 设置为模板字段。
   - `status` 设置为已映射。
   - `suggestion_source` 设置为 `template`。
   - `suggestion_confidence` 设置为 `1.0`。
   - `original_field_key` 设置为模板字段。
3. 确认类型：
   - 用户套用模板后未修改该列，提交 `confirmation_type=user_confirmed`。
   - 用户套用模板后又改成其他字段，提交 `confirmation_type=user_corrected`。
   - 原本没有推荐但用户手动选择，仍提交 `user_corrected`。
4. 取消套用模板：
   - 继续清空 `selectedTemplateId` 和 `templateDefaultValues`。
   - 不得继续显示“导入模板”来源给已经取消模板的状态。
   - 若保留当前字段选择，应按手动映射处理确认基准，避免误记为模板确认。
5. 文档收口：
   - 更新 `docs/COMMAND_CENTER.md`，登记 `TASK-036` 复验未通过和 `TASK-037` 新任务。

## 必须补充测试

后端至少覆盖：

1. 指定 `template_id` 预览时，`mapping_suggestions_v2` 包含所有 `applied_mapping_v2` 模板列，来源为 `template`，置信度为 `1.0`。
2. 同一列同时存在模板映射和经验建议时，返回模板建议。
3. 未传 `company_id` 但指定 `template_id` 时，仍返回模板建议。
4. 未指定模板时，现有经验/关键词建议行为不回退。

前端至少覆盖人工或自动检查：

1. 套用模板后，映射表显示“导入模板”和 `100%`。
2. 套用模板后未修改字段，提交 `user_confirmed`。
3. 套用模板后修改字段，提交 `user_corrected`。
4. 取消套用模板后，不再显示“导入模板”来源。

## 总指挥已复现的脚本

修复后，以下脚本的 `mapping_suggestions_v2` 必须包含 `col_001`、`col_002`、`col_003`，且 `source=template`、`confidence=1.0`。

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
@'
import asyncio, os, tempfile, uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.database import Base
import app.models
from app.services.template_service import create_template
from app.services.import_service import preview_import

async def main():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        t = await create_template(db, {
            "name": "套用模板",
            "data_type": "journal",
            "is_active": True,
            "header_signature": {"col_001": "凭证号", "col_002": "凭证日期", "col_003": "摘要"},
            "column_rules": {"col_001": "voucher_no", "col_002": "voucher_date", "col_003": "summary"},
        })
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="")
        tmp.write("凭证号,凭证日期,摘要\r\n001,2024-01-15,采购")
        tmp.close()
        try:
            result = await preview_import(tmp.name, "journal", db=db, template_id=str(t.id), company_id=str(uuid.uuid4()))
            print("applied_mapping_v2", result.get("applied_mapping_v2"))
            print("mapping_suggestions_v2", result.get("mapping_suggestions_v2"))
        finally:
            os.unlink(tmp.name)
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
