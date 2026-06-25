# TASK-065：递延收益 / 生产成本 / 制造费用语义匹配补强

状态：OPEN
负责人：worker
优先级：P0
提出时间：2026-06-23

## 背景

真实验收文件：

```text
D:\NAS\xiaochen\李辉辉项目组\SynologyDrive\汇达228股改审计\1.账套\aglq710-科目余额表 20251231.xlsx
```

`TASK-064` 已补强了一批语义匹配，真实文件重新验收后，以下类型仍然没有自动匹配：

```text
240102     递延收益_与资产相关的递延收益
50010101   生产成本_基本生产成本_直接材料
5001010201 生产成本_基本生产成本_直接人工_工资及奖金
51010101   制造费用_人工_工资及奖金
5101010201 制造费用_人工_福利费_社会统筹
```

这些不应依赖手工确认。它们的客户明细科目虽然代码更长、名称更细，但经济含义清楚：

```text
递延收益_*                 -> 标准 2401 递延收益
生产成本_基本生产成本_*     -> 标准 5001 生产成本
制造费用_*                 -> 标准 5101 制造费用
```

注意：`生产成本_直接人工_工资及奖金` 和 `制造费用_人工_福利费_*` 不是要匹配到 `2211 应付职工薪酬`。这里的客户科目是成本/费用归集科目，不能因为名称里有“工资”“福利费”就归到负债类薪酬科目。

## 已定位根因

本任务不是 UI 问题，也不是标准库缺项。

### 1. 标准库有目标科目

当前 `backend/audit.db` 的标准科目表中存在：

```text
2401 递延收益
5001 生产成本
5002 农业生产成本
5101 制造费用
2211 应付职工薪酬
2703 长期应付职工薪酬
```

### 2. 服务实际只给了带 warning 的前缀候选

直接调用 `recommend_mappings()` 的现状：

```text
240102 递延收益_与资产相关的递延收益
  2401 递延收益 | code_prefix_parent | score=0.85 | warning=请确认是否汇总

50010101 生产成本_基本生产成本_直接材料
  5001 生产成本 | code_prefix_parent | score=0.85 | warning=请确认是否汇总
  6001 其中：主营业务收入 | code_category_anchor | score=0.86 | warning=请确认是否归入

5001010201 生产成本_基本生产成本_直接人工_工资及奖金
  5001 生产成本 | code_prefix_parent | score=0.85 | warning=请确认是否汇总
  6001 其中：主营业务收入 | code_category_anchor | score=0.86 | warning=请确认是否归入

51010101 制造费用_人工_工资及奖金
  5101 制造费用 | code_prefix_parent | score=0.85 | warning=请确认是否汇总

5101010201 制造费用_人工_福利费_社会统筹
  5101 制造费用 | code_prefix_parent | score=0.85 | warning=请确认是否汇总
```

前端自动选中逻辑只接受：

```text
candidate.warning is None
candidate.score >= 0.9
```

所以这些 0.85/0.86 且有 warning 的候选不会自动确认。

### 3. 语义别名组缺项

当前 `backend/app/services/client_account_mapping_service.py` 里的 `_SEMANTIC_ACCOUNT_GROUPS` 已有：

```text
prepayments
accumulated_depreciation
construction_in_progress
other_receivables
other_payables
tax_payable
advance_receipts
long_term_prepaid_expense
intangible_amortization
```

但缺少：

```text
deferred_income
production_cost
manufacturing_overhead
```

因此 `_detect_semantic_group()` 对上述 5 条返回空，无法生成 `semantic_alias` 安全候选。

### 4. 名称锚点也缺项

`_NAME_ANCHORS` 没有：

```text
递延收益
生产成本
制造费用
```

所以 `_is_safe_auto_rollup()` 不能把 `code_prefix_parent` 从 warning 候选升级为安全候选。

### 5. `5001` 类别锚点存在错误

当前 `_CODE_CATEGORY_ANCHORS` 里有：

```python
("5001", "主营业务收入"),
("5401", "主营业务成本"),
```

这会导致客户 `50010101 生产成本_...` 被错误推荐到标准 `6001 其中：主营业务收入`。

当前标准库使用的是：

```text
5001 生产成本
5101 制造费用
6001 其中：主营业务收入
6401 其中：主营业务成本
```

因此 `5001 -> 主营业务收入` 是明确 bug，必须修正或移除。

## 目标

补强第二批语义匹配，使以下真实文件行能自动匹配：

```text
240102     递延收益_与资产相关的递延收益        -> 2401 递延收益
50010101   生产成本_基本生产成本_直接材料      -> 5001 生产成本
5001010201 生产成本_基本生产成本_直接人工_工资及奖金 -> 5001 生产成本
51010101   制造费用_人工_工资及奖金            -> 5101 制造费用
5101010201 制造费用_人工_福利费_社会统筹       -> 5101 制造费用
```

自动匹配候选必须满足：

```text
source = semantic_alias 或安全的 code_prefix_parent/name_anchor
score >= 0.9
warning = None
```

并且不得出现以下错配：

```text
生产成本_* 不得自动匹配 2211 应付职工薪酬
制造费用_* 不得自动匹配 2211 应付职工薪酬
生产成本_* 不得推荐 6001 主营业务收入
农业生产成本 不得被普通生产成本规则错误归入 5001（如本轮实现没有把握，至少不能新增这个错配）
```

## 必改文件

```text
backend/app/services/client_account_mapping_service.py
backend/tests/test_client_account_mapping_service.py
```

不要修改：

```text
frontend/src/views/DataImportView.vue
层级识别算法
金额拆分逻辑
第三步表格布局
导入入库逻辑
```

## 实现要求

### A. 新增语义别名组

在 `_SEMANTIC_ACCOUNT_GROUPS` 增加：

```python
"deferred_income": {
    "canonical": "递延收益",
    "client_aliases": ["递延收益", "与资产相关的递延收益", "与收益相关的递延收益"],
    "standard_aliases": ["递延收益"],
    "negative_aliases": [],
},
"production_cost": {
    "canonical": "生产成本",
    "client_aliases": ["生产成本", "基本生产成本", "直接材料", "直接人工", "直接动力", "委外加工费", "委外物资"],
    "standard_aliases": ["生产成本"],
    "negative_aliases": ["农业生产成本", "主营业务成本", "主营业务收入", "应付职工薪酬"],
},
"manufacturing_overhead": {
    "canonical": "制造费用",
    "client_aliases": ["制造费用"],
    "standard_aliases": ["制造费用"],
    "negative_aliases": ["应付职工薪酬", "管理费用", "销售费用", "研发费用"],
},
```

说明：

- `production_cost` 的 `client_aliases` 可以包含明细词，但必须结合根科目优先规则使用。
- 不要写死标准科目代码，例如不要写 `if name contains 生产成本 then 5001`。
- 标准目标仍从 `standard_accounts` 表里查启用科目。

### B. 调整语义识别优先级

修改 `_detect_semantic_group(client_name)`，不能只按 `_SEMANTIC_ACCOUNT_GROUPS` 的遍历顺序找任意别名。

必须先识别客户科目名称的根科目/首段：

```text
递延收益_与资产相关的递延收益 -> 根科目 递延收益 -> deferred_income
生产成本_基本生产成本_直接人工_工资及奖金 -> 根科目 生产成本 -> production_cost
制造费用_人工_福利费_社会统筹 -> 根科目 制造费用 -> manufacturing_overhead
```

建议实现：

```python
def _detect_semantic_group(client_name: str | None) -> str | None:
    if not client_name:
        return None
    tokens = _split_name_tokens(client_name)
    first = tokens[0] if tokens else str(client_name)
    first_norm = _normalize_name(first)

    root_priority = [
        ("deferred_income", ["递延收益"]),
        ("production_cost", ["生产成本"]),
        ("manufacturing_overhead", ["制造费用"]),
    ]
    for group_key, aliases in root_priority:
        for alias in aliases:
            if _normalize_name(alias) in first_norm:
                return group_key

    # 然后再走原有全名 alias 扫描，兼容 TASK-064 已有规则
```

重点：

- 根科目优先于后面的明细词。
- `生产成本_..._工资及奖金` 不能因为“工资”进入薪酬负债类。
- `制造费用_..._福利费` 不能因为“福利费”进入薪酬负债类。
- 如果后续有人新增工资/福利费语义组，也必须保留这个根科目优先规则。

### C. 修正 `_CODE_CATEGORY_ANCHORS`

移除或改正下面这两个错误/过旧规则：

```python
("5001", "主营业务收入"),
("5401", "主营业务成本"),
```

建议改为当前标准库口径：

```python
("6001", "主营业务收入"),
("6401", "主营业务成本"),
```

并保留已有可用规则：

```python
("6601", "销售费用"),
("6602", "管理费用"),
("6603", "财务费用"),
("6604", "研发费用"),
```

修正后，`50010101 生产成本_...` 不应再出现 `6001 其中：主营业务收入` 候选。

## 必须新增测试

在 `backend/tests/test_client_account_mapping_service.py` 的 `TestSemanticAccountMatching` 后面继续新增测试。

### 1. 递延收益明细安全匹配递延收益

```python
@pytest.mark.asyncio
async def test_deferred_income_detail_matches_deferred_income(self, db):
    db.add(_make_standard_account("2401", "递延收益"))
    await db.flush()

    results = await recommend_mappings(
        db,
        data_type="trial_balance",
        client_accounts=[
            {
                "client_account_code": "240102",
                "client_account_name": "递延收益_与资产相关的递延收益",
            }
        ],
    )

    candidates = results[0]["candidates"]
    safe = [
        c for c in candidates
        if c["standard_account_code"] == "2401"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert safe, f"递延收益明细应安全匹配 2401，实际候选: {candidates}"
```

### 2. 生产成本明细安全匹配生产成本

```python
@pytest.mark.asyncio
async def test_production_cost_details_match_production_cost(self, db):
    standards = [
        _make_standard_account("5001", "生产成本"),
        _make_standard_account("5002", "农业生产成本"),
        _make_standard_account("6001", "其中：主营业务收入"),
        _make_standard_account("6401", "其中：主营业务成本"),
        _make_standard_account("2211", "应付职工薪酬"),
    ]
    db.add_all(standards)
    await db.flush()

    inputs = [
        ("50010101", "生产成本_基本生产成本_直接材料"),
        ("5001010201", "生产成本_基本生产成本_直接人工_工资及奖金"),
    ]
    for code, name in inputs:
        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            client_accounts=[{"client_account_code": code, "client_account_name": name}],
        )
        candidates = results[0]["candidates"]
        safe = [
            c for c in candidates
            if c["standard_account_code"] == "5001"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert safe, f"{code} {name} 应安全匹配 5001，实际候选: {candidates}"

        wrong_safe = [
            c for c in candidates
            if c["standard_account_code"] in {"2211", "6001", "6401"}
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert not wrong_safe, f"{code} 不得安全匹配薪酬/收入/主营成本，实际: {wrong_safe}"

        wrong_6001 = [c for c in candidates if c["standard_account_code"] == "6001"]
        assert not wrong_6001, f"{code} 不应再出现 6001 主营业务收入候选，实际: {wrong_6001}"
```

### 3. 制造费用人工/福利费安全匹配制造费用

```python
@pytest.mark.asyncio
async def test_manufacturing_overhead_details_match_overhead(self, db):
    standards = [
        _make_standard_account("5101", "制造费用"),
        _make_standard_account("2211", "应付职工薪酬"),
        _make_standard_account("6602", "减：管理费用"),
    ]
    db.add_all(standards)
    await db.flush()

    inputs = [
        ("51010101", "制造费用_人工_工资及奖金"),
        ("5101010201", "制造费用_人工_福利费_社会统筹"),
    ]
    for code, name in inputs:
        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            client_accounts=[{"client_account_code": code, "client_account_name": name}],
        )
        candidates = results[0]["candidates"]
        safe = [
            c for c in candidates
            if c["standard_account_code"] == "5101"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert safe, f"{code} {name} 应安全匹配 5101，实际候选: {candidates}"

        wrong_safe = [
            c for c in candidates
            if c["standard_account_code"] in {"2211", "6602"}
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert not wrong_safe, f"{code} 不得安全匹配薪酬/管理费用，实际: {wrong_safe}"
```

### 4. 研发费用旧回归不能坏

已有真实验收依赖 `660401 研发费用 -> 660201 减：研发费用`。修正 `_CODE_CATEGORY_ANCHORS` 时不能破坏它。

如现有测试没有覆盖，请补：

```python
@pytest.mark.asyncio
async def test_research_expense_code_category_anchor_still_works(self, db):
    db.add(_make_standard_account("660201", "减：研发费用"))
    await db.flush()

    results = await recommend_mappings(
        db,
        data_type="trial_balance",
        client_accounts=[{"client_account_code": "660401", "client_account_name": "研发费用"}],
    )
    candidates = results[0]["candidates"]
    safe = [
        c for c in candidates
        if c["standard_account_code"] == "660201"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert safe, f"660401 研发费用仍应安全匹配 660201，实际候选: {candidates}"
```

## 本地复现命令

可以先用下面脚本复现修复前问题：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
@'
import asyncio
from app.core.database import async_session_factory
from app.services.client_account_mapping_service import recommend_mappings

inputs = [
    {"client_account_code": "240102", "client_account_name": "递延收益_与资产相关的递延收益"},
    {"client_account_code": "50010101", "client_account_name": "生产成本_基本生产成本_直接材料"},
    {"client_account_code": "5001010201", "client_account_name": "生产成本_基本生产成本_直接人工_工资及奖金"},
    {"client_account_code": "51010101", "client_account_name": "制造费用_人工_工资及奖金"},
    {"client_account_code": "5101010201", "client_account_name": "制造费用_人工_福利费_社会统筹"},
]

async def main():
    async with async_session_factory() as db:
        results = await recommend_mappings(db, "trial_balance", inputs, customer_label="debug")
        for item in results:
            print("\n", item["client_account_code"], item["client_account_name"])
            for c in item["candidates"]:
                print(" ", c["standard_account_code"], c["standard_account_name"], c["source"], c["score"], c["warning"])

asyncio.run(main())
'@ | D:\python\python.exe -
```

修复后期望：

```text
240102 有 2401 递延收益 的安全候选，warning=None, score>=0.9
50010101 有 5001 生产成本 的安全候选，warning=None, score>=0.9，且没有 6001 候选
5001010201 有 5001 生产成本 的安全候选，warning=None, score>=0.9，且没有 6001/2211 安全候选
51010101 有 5101 制造费用 的安全候选，warning=None, score>=0.9，且没有 2211 安全候选
5101010201 有 5101 制造费用 的安全候选，warning=None, score>=0.9，且没有 2211 安全候选
```

## 自动化验收

必须执行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/ -q

cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 真实文件验收

启动服务：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18000

cd D:\APP\Codex-项目\13、审计系统\frontend
$env:VITE_API_TARGET='http://127.0.0.1:18000'
npm run dev -- --host 127.0.0.1 --port 5177
```

浏览器验收：

1. 打开 `http://127.0.0.1:5177/data/import`。
2. 上传真实文件。
3. 客户标识可填 `Huida 228 QA TASK-065`，年度 `2025`，期间 `12`。
4. 字段映射页应先自动映射 8 个关键字段。
5. 进入“层级与科目匹配”。
6. 验证以下行已自动匹配：

```text
240102     -> 2401 递延收益
50010101   -> 5001 生产成本
5001010201 -> 5001 生产成本
51010101   -> 5101 制造费用
5101010201 -> 5101 制造费用
```

7. 验证 `50010101` 和 `5001010201` 不再推荐 `6001 主营业务收入`。
8. 验证 `生产成本_*`、`制造费用_*` 没有自动匹配到 `2211 应付职工薪酬`。
9. 记录修复后真实文件第三步的统计：

```text
全部：
已匹配：
未匹配：
已忽略：
有警告：
```

修复前本轮基线：

```text
全部 289
未匹配 64
已匹配 137
已忽略 0
有警告 115
```

完成后未匹配数量至少应低于 64，且上述 5 个样例必须已匹配。

## 给弱模型的领取提示词

```text
你负责实现 docs/tasks/TASK-065-deferred-production-overhead-matching.md。

工作目录：
D:\APP\Codex-项目\13、审计系统

先阅读：
- docs/tasks/TASK-065-deferred-production-overhead-matching.md
- backend/app/services/client_account_mapping_service.py
- backend/tests/test_client_account_mapping_service.py

这次只做科目匹配规则，不做 UI。

问题根因：
1. 标准库里有 2401 递延收益、5001 生产成本、5101 制造费用，但当前语义组没有 deferred_income / production_cost / manufacturing_overhead。
2. _NAME_ANCHORS 也没有 递延收益 / 生产成本 / 制造费用，所以 code_prefix_parent 只能给 warning 候选，前端不会自动确认。
3. _CODE_CATEGORY_ANCHORS 里把 5001 错误映射成 主营业务收入，导致 50010101 生产成本 被错误推荐到 6001 主营业务收入。

必须做到：
- 240102 递延收益_与资产相关的递延收益 自动匹配 2401 递延收益。
- 50010101 生产成本_基本生产成本_直接材料 自动匹配 5001 生产成本。
- 5001010201 生产成本_基本生产成本_直接人工_工资及奖金 自动匹配 5001 生产成本。
- 51010101 制造费用_人工_工资及奖金 自动匹配 5101 制造费用。
- 5101010201 制造费用_人工_福利费_社会统筹 自动匹配 5101 制造费用。
- 生产成本/制造费用里的 工资、福利费 不得自动匹配 2211 应付职工薪酬。
- 生产成本不得再出现 6001 主营业务收入候选。

实现顺序：
1. 先在 backend/tests/test_client_account_mapping_service.py 的 TestSemanticAccountMatching 后追加失败测试。
2. 运行：
   cd D:\APP\Codex-项目\13、审计系统\backend
   D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
   预期新增测试失败。
3. 修改 backend/app/services/client_account_mapping_service.py：
   - 增加 deferred_income / production_cost / manufacturing_overhead 语义组。
   - 修改 _detect_semantic_group，先按科目名称首段/根科目识别，再走全名 alias 扫描。
   - 修正 _CODE_CATEGORY_ANCHORS，去掉 5001 -> 主营业务收入，改用 6001 -> 主营业务收入、6401 -> 主营业务成本。
4. 重新运行全部测试和前端构建：
   D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
   D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
   D:\python\python.exe -m pytest tests/ -q
   npm run build
5. 用真实文件跑浏览器验收，记录修复后“全部/已匹配/未匹配/已忽略/有警告”数量。

不要做：
- 不要硬编码 if code == 50010101 then 5001。
- 不要把生产成本/制造费用的工资福利费匹配到应付职工薪酬。
- 不要改 UI、金额列、层级识别、导入入库逻辑。
- 不要为了降低未匹配数量自动忽略行。

交付时汇报：
- 改了哪些文件。
- 新增了哪些语义组。
- 上述 5 个样例是否都自动匹配。
- 生产成本是否还出现 6001 候选。
- 真实文件未匹配数量从 64 降到多少。
- 全部测试和 npm build 是否通过。
```

## 完成标准

- 新增测试先失败后通过。
- 后端全量测试通过。
- 前端构建通过。
- 真实文件验收中上述 5 条自动匹配。
- 不新增薪酬/收入错配。
- `660401 研发费用 -> 660201 减：研发费用` 等 TASK-064 已通过样例不能回退。
