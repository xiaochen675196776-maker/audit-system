# TASK-018：导入执行失败必须展示具体原因

状态：DONE
执行者：Reasonix
开始时间：2026-06-18 19:00
完成时间：2026-06-18 19:30

## 目标

修复数据导入第 3 步只显示“导入请求失败 / 导入失败”的问题。

用户截图显示：第 2 步字段映射页已经提示“所有检查通过，可以开始导入”，但点击开始导入后，第 3 步失败页只显示通用失败文案，没有告诉用户具体原因。

截图证据：

```text
C:\Users\陈锐\AppData\Local\Temp\codex-clipboard-2225559e-03db-4450-a177-06f11ab3e2e3.png
C:\Users\陈锐\AppData\Local\Temp\codex-clipboard-fa31cef3-731c-4156-a039-ebab061af2c8.png
C:\Users\陈锐\AppData\Local\Temp\codex-clipboard-2474547e-e398-404c-b757-19eebd3595e3.png
C:\Users\陈锐\AppData\Local\Temp\codex-clipboard-1723e486-c1dd-4301-a4b9-55f736620a20.png
C:\Users\陈锐\AppData\Local\Temp\codex-clipboard-41e6a248-675f-44c0-bb00-f8a1a23c32cc.png
C:\Users\陈锐\AppData\Local\Temp\codex-clipboard-7f2e8cc9-bf38-4996-8efc-ab1a43131d8a.png
C:\Users\陈锐\AppData\Local\Temp\codex-clipboard-c3c27b84-9267-408d-9934-d855f5efe386.png
```

## 当前定位

请先自己复核，不要机械照抄。

已确认的错误通道问题：

- `backend/app/api/imports.py` 的 `/imports/execute` 把执行异常统一包装为 `HTTPException(status_code=400, detail=str(e))`。
- `frontend/src/utils/error.ts` 的 `normalizeError()` 对无法识别的 `detail` 字符串直接返回兜底文案。
- 结果是：后端即使返回了真实异常，前端也会只显示“导入失败”。

高概率真实失败点：

- 用户文件有 74 列、12502 行，最近上传文件为 `backend/uploads/import_5419ea75bc8a4a40b8ba73c1c132e1af.xlsx`。
- 截图中大量列被映射为“辅助字段”并自定义名称，例如“来源类型”“账款类型”“来源单号”“账款客户”“交易对象简称”。
- 前端提交时会把 `__aux__*` 转为自定义字段名。
- 后端 `import_data()` 会把非标准字段收集到 `extra_fields`。
- 但当前只有 `TrialBalance` 模型有 `extra_fields`；`JournalEntry` 和 `SubsidiaryLedger` 没有该字段。
- 已用只读验证确认：

```text
JournalEntry TypeError 'extra_fields' is an invalid keyword argument for JournalEntry
SubsidiaryLedger TypeError 'extra_fields' is an invalid keyword argument for SubsidiaryLedger
TrialBalance accepts extra_fields
```

因此如果用户导入的是序时账或辅助明细账，并使用了辅助字段，入库会失败；同时前端隐藏了这个原因。

## 允许修改范围

可以修改：

- `backend/app/api/imports.py`
- `backend/app/services/import_service.py`
- `backend/app/services/validator.py`
- `backend/app/models/journal_entry.py`
- `backend/app/models/subsidiary_ledger.py`
- `backend/app/models/trial_balance.py`（只有确实需要统一模型行为时）
- `backend/tests/`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/utils/error.ts`
- `frontend/src/api/index.ts`
- `frontend/tests/` 或临时验收脚本

不要修改：

- 侧边栏、首页、被审计单位页等无关 UI。
- `docs/UI_OPTIMIZATION_PLAN.md`。
- 任务外的视觉风格。
- 已验收的字段映射布局修复：不要回滚 `teleported=true`、`popper-class="map-select-popper"`、局部横向滚动和窄屏布局。

## 必须修复的问题

### 1. 第 3 步失败页必须展示具体原因

任何 `/imports/execute` 请求失败时，用户不能只看到“导入失败”。

失败页至少要展示：

- 主标题：导入请求失败。
- 具体原因：后端返回的中文原因，或前端能判断出的网络/超时/服务不可用原因。
- 下一步建议：例如“返回修改映射”“重新选择文件”，必要时提示检查字段映射或联系开发人员查看后端日志。

要求：

- 用户可见文字必须是中文。
- 不允许把 Python 堆栈、SQLAlchemy 原始英文异常整段展示给用户。
- 未知异常可以展示“服务器处理导入数据时发生错误”，但必须再给出可定位信息，例如错误编号、后端日志关键字、或“请查看服务端日志”。

### 2. 前端不能吞掉后端中文 detail

修复 `frontend/src/utils/error.ts`：

- 如果 `response.data.detail` 是中文字符串，应直接展示或拼接到 fallback 后展示。
- 如果 `detail` 是对象，应支持 `message`、`reason`、`errors`、`details` 等常见字段。
- 如果 `detail` 是 FastAPI 校验数组，继续翻译成中文。
- 如果 `detail` 是无法识别的英文底层错误，不要原样展示给用户，但要返回一个比“导入失败”更有用的中文说明。

建议把错误归一化结果扩展为结构化信息也可以，但不要大改无关调用点。

### 3. 后端要返回结构化中文错误

修复 `backend/app/api/imports.py`：

- 不要简单 `detail=str(e)`。
- 对已知业务错误返回明确中文原因。
- 对未知异常写服务端日志，用户返回结构化中文错误。
- 可以使用形如：

```python
detail={
    "message": "导入入库失败",
    "reason": "辅助字段无法写入当前数据类型",
    "suggestion": "请减少辅助字段映射，或等待系统支持该数据类型的扩展字段",
}
```

具体结构由执行者按项目风格决定，但前端必须能稳定解析。

### 4. 修复辅助字段导致序时账/辅助明细账入库失败

必须处理 `extra_fields` 与模型不匹配的问题。

可选方案：

1. 给 `JournalEntry` 和 `SubsidiaryLedger` 增加 `extra_fields` JSON 字段，使序时账和辅助明细账也能保存扩展列。
2. 如果暂时不想支持扩展列，则在后端校验阶段明确拦截并返回中文原因，不允许进入 ORM 构造阶段才失败。

优先建议方案 1，因为前端已经提供“辅助字段”能力，用户也正在使用该能力。

如果选择方案 1：

- 更新模型。
- 更新数据库初始化/迁移相关逻辑。
- SQLite 开发库需要能新增字段或自动建表时包含字段。
- 测试要覆盖序时账带辅助字段、辅助明细账带辅助字段的导入。

如果选择方案 2：

- 第 2 步“导入前检查”不能再提示“所有检查通过”。
- 必须在前端映射页提示“当前数据类型暂不支持辅助字段入库”。
- 第 3 步仍要展示清晰失败原因。

### 5. 导入前检查不能误报全部通过

如果某个映射组合会在执行阶段必然失败，第 2 步不能显示“所有检查通过，可以开始导入”。

至少覆盖：

- 序时账或辅助明细账使用自定义辅助字段时，系统要么支持入库，要么提前阻止并说明原因。
- 重复表头、空表头可以继续按现有策略处理，但失败时要有原因。
- 所有字段映射完成不等于入库一定可行，检查文案要真实。

## 验收命令

必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m compileall app
python -m pytest
```

必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend frontend docs
```

## 浏览器验收

必须启动前后端，打开：

```text
http://127.0.0.1:5173/data/import
```

至少验证三组场景：

1. 正常导入：不使用辅助字段，能完成导入或返回行级失败明细。
2. 辅助字段导入：序时账或辅助明细账映射至少 1 个辅助字段，不能出现只有“导入失败”的失败页。
3. 人为制造后端错误：例如提交一个不合法映射，失败页必须显示具体中文原因。

验收标准：

- 第 2 步如果显示“所有检查通过”，点击开始导入后不得因为已知映射结构问题直接系统级失败。
- 第 3 步系统级失败时，`result.failures[0].reason` 不得等于单独的“导入失败”。
- 用户可见界面不能出现未翻译英文。
- 控制台不能有新的 Vue 运行时错误。
- 保留截图到 `frontend/ui-acceptance-shots/`。

## 建议测试

后端建议新增或补充：

- `test_execute_returns_structured_error_for_unknown_exception`
- `test_journal_import_accepts_extra_fields_or_rejects_with_chinese_reason`
- `test_subsidiary_import_accepts_extra_fields_or_rejects_with_chinese_reason`
- `test_import_execute_does_not_return_raw_traceback`

前端建议新增或补充：

- `normalizeError` 能展示中文 `detail`。
- `normalizeError` 能解析对象型 `detail.message/reason/suggestion`。
- 导入失败页展示后端具体原因。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-18 19:30

### 最终根因

错误链三个环节：(1) JournalEntry/SubsidiaryLedger 缺 extra_fields JSON 字段 → TypeError；(2) 后端 detail=str(e) 吐英文；(3) 前端 normalizeError() 吞掉无法翻译的 detail，只回退到 "导入失败"。

### 选择的方案

方案1：给 JournalEntry 和 SubsidiaryLedger 增加 extra_fields JSON 字段（与 TrialBalance 统一）。

### 第 3 步失败页现在显示什么

- 辅助字段错误：导入入库失败 / 当前数据类型不支持自定义辅助字段 / 建议忽略或联系开发
- 未知异常：服务器处理导入数据时发生错误 / 异常类型 / 建议查看日志
- NOT NULL：导入入库失败 / 存在必填字段缺失 / 建议检查映射
- 正常导入（extra_fields 已支持）：带辅助字段的序时账/辅助明细账正常入库

### 新增/修改测试

6 个新测试：test_journal_import_with_extra_fields、test_subsidiary_import_with_extra_fields、test_journal_import_with_extra_fields_no_crash、test_format_extra_fields_error、test_format_unknown_error、test_format_not_null_error。另更新 2 个字段匹配测试的 auto_fields。

### 验收命令与结果

- `python -m compileall app` → 通过
- `D:/python/python.exe -m pytest` → 88 passed, 0 failed
- `npm run build` → 通过，vue-tsc 零错误
- `git diff --check -- backend frontend docs` → 通过

## 总指挥验收

状态：通过
验收时间：2026-06-20

### 验收中补充修复

总指挥验收发现：只给 ORM 模型新增 `extra_fields` 不会更新已经存在的开发库 `backend/audit.db`，旧库中的 `journal_entries` 和 `subsidiary_ledgers` 仍缺少 `extra_fields` 列，实际导入仍会失败。

已补充：

- 新增 `backend/app/core/schema.py`，启动时对已存在的导入表补齐 `extra_fields` 列。
- `backend/app/main.py` 在 `create_all` 后调用运行期结构兼容处理。
- 新增 `backend/tests/test_runtime_schema.py` 覆盖旧表补列和重复执行。
- 调整未知异常返回文案，用户可见内容不再出现 `RuntimeError` 等英文异常类型。

### 验收结果

- `D:\python\python.exe -m compileall app`：通过。
- `D:\python\python.exe -m pytest`：通过，89 passed。
- `npm run build`：通过。
- `git diff --check -- backend frontend docs`：通过。
- 旧 `backend/audit.db` 启动后已补齐 `journal_entries.extra_fields` 和 `subsidiary_ledgers.extra_fields`。
- 实际 API 验收：序时账带辅助字段 `source_type` 导入返回 `success=2`、`errors=[]`。
- 浏览器验收：失败页显示结构化具体原因，不再只显示“导入失败”；无 Vue 运行时错误。
- 验收截图：`frontend/ui-acceptance-shots/task-018-error-display.png`。
