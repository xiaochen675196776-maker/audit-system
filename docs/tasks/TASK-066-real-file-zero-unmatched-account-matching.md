# TASK-066：真实科目余额表科目匹配清零（0 未匹配）

状态：OPEN
负责人：worker
优先级：P0
提出时间：2026-06-24

## 背景

真实验收文件：

```text
D:\NAS\xiaochen\李辉辉项目组\SynologyDrive\汇达228股改审计\1.账套\aglq710-科目余额表 20251231.xlsx
```

用户明确口径：这张科目余额表里的科目应该全部能够匹配上，不应该还剩未匹配项。

当前代码已经完成了 `TASK-064`、`TASK-065` 的一部分匹配增强，真实文件服务级验收结果如下：

```text
文件行数：289
参与匹配的末级科目：201
已安全匹配：176
未匹配：25
```

本任务目标是把真实文件第三步“层级与科目匹配”的未匹配数量降到：

```text
未匹配 0
```

不能通过自动忽略来凑数。必须让客户末级科目都有正确、安全的标准科目候选。

## 当前未匹配清单

### A. 研发支出费用化支出：23 条

这些全部是 `研发支出_费用化支出_*`，标准库有 `660201 减：研发费用`，应该自动匹配到该标准科目。

```text
5301010101     研发支出_费用化支出_人工_工资及奖金
<科目代码样例001>   研发支出_费用化支出_人工_福利费_社会统筹
<科目代码样例002>   研发支出_费用化支出_人工_福利费_住房公积金
<科目代码样例003>   研发支出_费用化支出_人工_福利费_膳食费
<科目代码样例004>   研发支出_费用化支出_人工_福利费_其他福利
5301010204     研发支出_费用化支出_办公费用_邮寄费
5301010206     研发支出_费用化支出_办公费用_市内交通费
5301010207     研发支出_费用化支出_办公费用_其他办公费
5301010301     研发支出_费用化支出_差旅费_国内
53010107       研发支出_费用化支出_租赁费
53010108       研发支出_费用化支出_折旧
5301010901     研发支出_费用化支出_摊销_软件
5301010902     研发支出_费用化支出_摊销_专利
5301010904     研发支出_费用化支出_摊销_其他
<科目代码样例005>   研发支出_费用化支出_直接投入_机物料_仓存机物料
5301011301     研发支出_费用化支出_专利费_申请
5301011302     研发支出_费用化支出_专利费_维护
53010115       研发支出_费用化支出_委托外部研发费
53010116       研发支出_费用化支出_检测费
53010117       研发支出_费用化支出_动力
53010118       研发支出_费用化支出_修理费
5301019802     研发支出_费用化支出_专项_测试化验加工费
5301019805     研发支出_费用化支出_专项_会议费
```

当前现象：

```text
候选：NONE
```

根因：

- `_NAME_ANCHORS` 有 `研发费用`，但没有 `研发支出`。
- `_SEMANTIC_ACCOUNT_GROUPS` 没有 `research_expense` / `development_expenditure`。
- `_CODE_CATEGORY_ANCHORS` 只有 `6604 -> 研发费用`，没有处理客户代码体系里的 `5301 研发支出`。
- 标准库有 `660201 减：研发费用`，但没有 `研发支出` 字面名称，因此普通名称包含/相似度找不到候选。

业务口径：

```text
研发支出_费用化支出_* -> 660201 减：研发费用
```

同时必须注意：

```text
研发支出_资本化支出_* 不得归到 660201 研发费用。
```

如果实现资本化支出规则，应归到：

```text
1704 开发支出
```

标准库当前存在：

```text
660201 减：研发费用
1704   开发支出
```

### B. 投资收益明细：1 条

```text
611101 投资收益_交易性金融资产收益
```

当前候选：

```text
1101 交易性金融资产 | name_similarity | 0.75 | warning=名称相似度仅 70%，建议人工确认
6111 加：投资收益   | code_prefix_parent | 0.85 | warning=请确认是否汇总到该标准科目
```

标准库有：

```text
6111 加：投资收益
```

根因：

- `_NAME_ANCHORS` 没有 `投资收益`。
- 因此 `_is_safe_auto_rollup()` 不能把 `611101` 的前缀候选 `6111 加：投资收益` 升级为安全候选。
- 名称里同时包含 `交易性金融资产`，导致 `1101 交易性金融资产` 作为弱相似候选排在前面，容易误导。

业务口径：

```text
投资收益_交易性金融资产收益 -> 6111 加：投资收益
```

不得自动匹配：

```text
1101 交易性金融资产
```

### C. 其他收益：1 条

```text
6112 其他收益
```

当前候选：

```text
6117 加：其他收益 | name_similarity | 0.84 | warning=None
```

但前端自动选择条件是：

```text
warning is None
score >= 0.9
```

所以 `0.84` 不会自动确认。

标准库有：

```text
6117 加：其他收益
```

根因：

- `_NAME_ANCHORS` 没有 `其他收益`。
- `_SEMANTIC_ACCOUNT_GROUPS` 没有 `other_income`。
- `_query_name_exact_match()` 不剥离 `加：/减：/其中：` 显示前缀，所以客户 `其他收益` 不会和标准 `加：其他收益` 精确匹配。

业务口径：

```text
其他收益 -> 6117 加：其他收益
```

### D. 上轮验收遗留的危险候选：生产成本误配农业生产成本

真实文件中下面两条首选匹配已经对了：

```text
50010101   生产成本_基本生产成本_直接材料
5001010201 生产成本_基本生产成本_直接人工_工资及奖金
```

但当前仍同时出现错误安全候选：

```text
5002 农业生产成本 | name_anchor | 0.92 | warning=None
```

这是 P0 安全问题。即使首选候选是 `5001 生产成本`，也不能让 `5002 农业生产成本` 成为安全候选。

根因：

- `_query_name_anchor_match("生产成本")` 会返回标准 `5001 生产成本` 和包含它的 `5002 农业生产成本`。
- `_is_safe_auto_rollup()` 当前只判断 `anchor_norm in sa_canonical`，所以把 `农业生产成本` 也判断为安全。

安全规则必须改为：

```text
安全自动确认不能只靠“包含关系”。
默认必须 canonical 完全等价。
包含命中最多只能是 warning 候选，不能 warning=None。
```

## 目标

修复后，真实文件第三步应满足：

```text
参与匹配末级科目：201
未匹配：0
```

并满足以下安全断言：

```text
研发支出_费用化支出_* -> 660201 减：研发费用
投资收益_交易性金融资产收益 -> 6111 加：投资收益
其他收益 -> 6117 加：其他收益
生产成本_* 不得安全匹配 5002 农业生产成本
投资收益_* 不得安全匹配 1101 交易性金融资产
研发支出_费用化支出_* 不得安全匹配 2211 应付职工薪酬
研发支出_资本化支出_* 不得安全匹配 660201 研发费用
```

## 必改文件

```text
backend/app/services/client_account_mapping_service.py
backend/tests/test_client_account_mapping_service.py
```

不要改：

```text
frontend/src/views/DataImportView.vue
层级识别算法
金额拆分逻辑
导入入库逻辑
标准科目库数据
```

## 实现要求

### 1. 补充语义组

在 `_SEMANTIC_ACCOUNT_GROUPS` 增加：

```python
"research_expense": {
    "canonical": "研发费用",
    "client_aliases": ["研发费用", "研发支出", "费用化支出", "研发支出费用化支出"],
    "standard_aliases": ["研发费用"],
    "negative_aliases": ["开发支出", "资本化支出", "油气开发支出", "应付职工薪酬"],
},
"development_expenditure": {
    "canonical": "开发支出",
    "client_aliases": ["开发支出", "研发支出资本化支出", "资本化支出"],
    "standard_aliases": ["开发支出"],
    "negative_aliases": ["研发费用", "费用化支出", "油气开发支出"],
},
"investment_income": {
    "canonical": "投资收益",
    "client_aliases": ["投资收益", "交易性金融资产收益"],
    "standard_aliases": ["投资收益"],
    "negative_aliases": ["交易性金融资产", "其他收益"],
},
"other_income": {
    "canonical": "其他收益",
    "client_aliases": ["其他收益"],
    "standard_aliases": ["其他收益"],
    "negative_aliases": ["其他综合收益", "其他应收款", "其他权益工具", "投资收益"],
},
```

注意：

- 不要写死 `5301010101 -> 660201`。
- 仍然必须从 `standard_accounts` 表查询启用标准科目。
- `research_expense` 不能把所有 `研发支出` 都归入研发费用，必须识别 `费用化支出`。
- `development_expenditure` 如果命中 `资本化支出`，应该优先匹配 `1704 开发支出`，不能匹配 `660201 研发费用`。

### 2. 调整 `_detect_semantic_group`

必须处理多段客户科目名称：

```text
研发支出_费用化支出_人工_工资及奖金
研发支出_资本化支出_人工_工资及奖金
投资收益_交易性金融资产收益
其他收益
```

建议逻辑：

```python
tokens = _split_name_tokens(client_name)
first = _normalize_name(tokens[0]) if tokens else ""
all_token_norms = [_normalize_name(t) for t in tokens]
full_norm = _normalize_name(client_name)

if first == _normalize_name("研发支出"):
    if _normalize_name("费用化支出") in all_token_norms or _normalize_name("费用化支出") in full_norm:
        return "research_expense"
    if _normalize_name("资本化支出") in all_token_norms or _normalize_name("资本化支出") in full_norm:
        return "development_expenditure"

if first == _normalize_name("投资收益"):
    return "investment_income"

if first == _normalize_name("其他收益"):
    return "other_income"
```

然后再走已有的 root priority 和 alias 扫描。

### 3. 补充名称锚点

`_NAME_ANCHORS` 增加：

```python
"投资收益", "其他收益"
```

是否增加 `研发支出` 要谨慎：

- 如果仅增加 `研发支出`，但不做语义分流，会导致标准库无同名科目，仍然无法正确匹配。
- 本任务应优先通过 `semantic_alias` 处理 `研发支出_费用化支出`。

### 4. 安全自动归入必须收紧

修改 `_is_safe_auto_rollup()`：

当前逻辑类似：

```python
return anchor_norm and anchor_norm in sa_canonical
```

必须改为更严格的安全判断：

```python
return bool(anchor_norm and anchor_norm == sa_canonical)
```

理由：

```text
生产成本 in 农业生产成本   # 不能安全
其他收益 in 其他综合收益   # 不能安全
投资收益 in 投资收益      # 可以安全
研发费用 == 研发费用      # 可以安全，因为 canonical 会剥离“减：”
```

包含关系仍可作为候选展示，但必须带 warning，不能 `warning=None`。

### 5. 保留已有正确匹配

不能破坏已经验收通过的样例：

```text
112301/112302 预付账款_* -> 112401 预付款项
160202/160203/160204 累计折旧_* -> 1602 减：固定资产-累计折旧
160403/160404/160405/160406 在建工程_* -> 160401 在建工程-原值
240102 递延收益_* -> 2401 递延收益
50010101/5001010201 生产成本_* -> 5001 生产成本
51010101/5101010201 制造费用_* -> 5101 制造费用
660401 研发费用 -> 660201 减：研发费用
10020108 银行存款_* -> 1002 银行存款
140501 库存商品 -> 1405 库存商品
```

## 必须新增测试

在 `backend/tests/test_client_account_mapping_service.py` 的 `TestSemanticAccountMatching` 中追加。

### 1. 研发支出费用化支出匹配研发费用

```python
@pytest.mark.asyncio
async def test_research_expenditure_expensed_details_match_research_expense(self, db):
    standards = [
        _make_standard_account("660201", "减：研发费用"),
        _make_standard_account("1704", "开发支出"),
        _make_standard_account("2211", "应付职工薪酬"),
    ]
    db.add_all(standards)
    await db.flush()

    inputs = [
        ("5301010101", "研发支出_费用化支出_人工_工资及奖金"),
        ("<科目代码样例001>", "研发支出_费用化支出_人工_福利费_社会统筹"),
        ("5301010204", "研发支出_费用化支出_办公费用_邮寄费"),
        ("53010108", "研发支出_费用化支出_折旧"),
        ("<科目代码样例005>", "研发支出_费用化支出_直接投入_机物料_仓存机物料"),
        ("5301019802", "研发支出_费用化支出_专项_测试化验加工费"),
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
            if c["standard_account_code"] == "660201"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert safe, f"{code} {name} 应安全匹配 660201，实际候选: {candidates}"

        wrong_safe = [
            c for c in candidates
            if c["standard_account_code"] in {"1704", "2211"}
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert not wrong_safe, f"{code} 不得安全匹配开发支出/应付职工薪酬，实际: {wrong_safe}"
```

### 2. 研发支出资本化支出不得匹配研发费用

```python
@pytest.mark.asyncio
async def test_research_expenditure_capitalized_matches_development_not_research_expense(self, db):
    standards = [
        _make_standard_account("660201", "减：研发费用"),
        _make_standard_account("1704", "开发支出"),
        _make_standard_account("1636", "油气开发支出"),
    ]
    db.add_all(standards)
    await db.flush()

    results = await recommend_mappings(
        db,
        data_type="trial_balance",
        client_accounts=[
            {
                "client_account_code": "5301020101",
                "client_account_name": "研发支出_资本化支出_人工_工资及奖金",
            }
        ],
    )
    candidates = results[0]["candidates"]

    safe_1704 = [
        c for c in candidates
        if c["standard_account_code"] == "1704"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert safe_1704, f"资本化研发支出应安全匹配 1704 开发支出，实际候选: {candidates}"

    wrong_safe = [
        c for c in candidates
        if c["standard_account_code"] in {"660201", "1636"}
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert not wrong_safe, f"资本化研发支出不得安全匹配研发费用/油气开发支出，实际: {wrong_safe}"
```

### 3. 投资收益明细匹配投资收益

```python
@pytest.mark.asyncio
async def test_investment_income_detail_matches_investment_income(self, db):
    standards = [
        _make_standard_account("6111", "加：投资收益"),
        _make_standard_account("1101", "交易性金融资产"),
    ]
    db.add_all(standards)
    await db.flush()

    results = await recommend_mappings(
        db,
        data_type="trial_balance",
        client_accounts=[
            {"client_account_code": "611101", "client_account_name": "投资收益_交易性金融资产收益"}
        ],
    )
    candidates = results[0]["candidates"]
    safe = [
        c for c in candidates
        if c["standard_account_code"] == "6111"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert safe, f"投资收益明细应安全匹配 6111，实际候选: {candidates}"

    wrong_safe = [
        c for c in candidates
        if c["standard_account_code"] == "1101"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert not wrong_safe, f"投资收益明细不得安全匹配交易性金融资产，实际: {wrong_safe}"
```

### 4. 其他收益匹配其他收益

```python
@pytest.mark.asyncio
async def test_other_income_matches_other_income(self, db):
    standards = [
        _make_standard_account("6117", "加：其他收益"),
        _make_standard_account("4301", "其他综合收益"),
        _make_standard_account("122101", "其他应收款"),
        _make_standard_account("4002", "其他权益工具"),
    ]
    db.add_all(standards)
    await db.flush()

    results = await recommend_mappings(
        db,
        data_type="trial_balance",
        client_accounts=[{"client_account_code": "6112", "client_account_name": "其他收益"}],
    )
    candidates = results[0]["candidates"]
    safe = [
        c for c in candidates
        if c["standard_account_code"] == "6117"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert safe, f"其他收益应安全匹配 6117，实际候选: {candidates}"

    wrong_safe = [
        c for c in candidates
        if c["standard_account_code"] in {"4301", "122101", "4002"}
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert not wrong_safe, f"其他收益不得安全匹配其他综合收益/其他应收款/其他权益工具，实际: {wrong_safe}"
```

### 5. 生产成本不得安全匹配农业生产成本

```python
@pytest.mark.asyncio
async def test_production_cost_does_not_safe_match_agricultural_production_cost(self, db):
    standards = [
        _make_standard_account("5001", "生产成本"),
        _make_standard_account("5002", "农业生产成本"),
    ]
    db.add_all(standards)
    await db.flush()

    results = await recommend_mappings(
        db,
        data_type="trial_balance",
        client_accounts=[
            {"client_account_code": "50010101", "client_account_name": "生产成本_基本生产成本_直接材料"}
        ],
    )
    candidates = results[0]["candidates"]

    safe_5001 = [
        c for c in candidates
        if c["standard_account_code"] == "5001"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert safe_5001, f"生产成本应安全匹配 5001，实际候选: {candidates}"

    wrong_safe_5002 = [
        c for c in candidates
        if c["standard_account_code"] == "5002"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert not wrong_safe_5002, f"生产成本不得安全匹配 5002 农业生产成本，实际: {wrong_safe_5002}"
```

## 真实文件验收脚本

修复后用下面脚本跑真实文件。脚本只做预览/分析并回滚事务，不入库。

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
@'
import asyncio
import uuid
from pathlib import Path
from app.core.database import async_session_factory, engine
from app.services.standard_trial_balance_import_service import preview_standard_import, analyze_standard_import

engine.echo = False
file_path = list(Path(r'D:\NAS\xiaochen').rglob('aglq710-*20251231.xlsx'))[0]

field_mappings = [
    {"column_id": "col_0", "field_name": "account_code"},
    {"column_id": "col_1", "field_name": "account_name"},
    {"column_id": "col_2", "field_name": "opening_debit", "period_type": "opening", "split_mode": "two_column", "debit_column_id": "col_2", "credit_column_id": "col_3"},
    {"column_id": "col_3", "field_name": "opening_credit", "period_type": "opening", "split_mode": "two_column", "debit_column_id": "col_2", "credit_column_id": "col_3"},
    {"column_id": "col_4", "field_name": "current_debit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
    {"column_id": "col_5", "field_name": "current_credit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
    {"column_id": "col_6", "field_name": "ending_debit", "period_type": "ending", "split_mode": "two_column", "debit_column_id": "col_6", "credit_column_id": "col_7"},
    {"column_id": "col_7", "field_name": "ending_credit", "period_type": "ending", "split_mode": "two_column", "debit_column_id": "col_6", "credit_column_id": "col_7"},
]

def best_safe(rec):
    for c in rec.get("candidates", []):
        if c.get("warning") is None and c.get("score", 0) >= 0.9:
            return c
    return None

async def main():
    async with async_session_factory() as db:
        preview = await preview_standard_import(
            db=db,
            file_path=str(file_path),
            file_name=file_path.name,
            fiscal_year=2025,
            period=12,
            customer_label="TASK-066-realfile-rollback",
            source_label="acceptance",
        )
        analyze = await analyze_standard_import(
            db=db,
            batch_id=uuid.UUID(preview["batch_id"]),
            file_path=str(file_path),
            field_mappings=field_mappings,
            fiscal_year=2025,
            period=12,
            customer_label="TASK-066-realfile-rollback",
            source_label="acceptance",
            hierarchy_mode="auto",
        )
        recs = analyze["mapping_recommendations"]
        hierarchy_by_row = {h["row_index"]: h for h in analyze["hierarchy"]}
        participating = [
            r for r in recs
            if hierarchy_by_row.get(r.get("row_index"), {}).get("is_leaf", True)
            and (r.get("client_account_code") or r.get("client_account_name"))
        ]
        unmatched = [r for r in participating if not best_safe(r)]
        print({
            "all_recs": len(recs),
            "participating_leaf": len(participating),
            "safe_matched": len(participating) - len(unmatched),
            "unmatched": len(unmatched),
        })
        for r in unmatched:
            print("UNMATCHED", r.get("row_index"), r.get("client_account_code"), r.get("client_account_name"), r.get("candidates", []))

        bad_safe = []
        for r in participating:
            code = str(r.get("client_account_code") or "")
            name = str(r.get("client_account_name") or "")
            for c in r.get("candidates", []):
                if c.get("warning") is None and c.get("score", 0) >= 0.9:
                    if c.get("standard_account_code") == "5002" and name.startswith("生产成本"):
                        bad_safe.append((code, name, c))
                    if c.get("standard_account_code") == "1101" and name.startswith("投资收益"):
                        bad_safe.append((code, name, c))
                    if c.get("standard_account_code") == "2211" and name.startswith("研发支出"):
                        bad_safe.append((code, name, c))
        print("bad_safe", bad_safe)
        await db.rollback()

asyncio.run(main())
'@ | D:\python\python.exe -
```

期望输出：

```text
unmatched: 0
bad_safe []
```

## 自动化验证

必须执行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/ -q

cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 给弱模型的领取提示词

```text
你负责实现 docs/tasks/TASK-066-real-file-zero-unmatched-account-matching.md。

工作目录：
D:\APP\Codex-项目\13、审计系统

先读：
- docs/tasks/TASK-066-real-file-zero-unmatched-account-matching.md
- backend/app/services/client_account_mapping_service.py
- backend/tests/test_client_account_mapping_service.py

任务目标：
用户提供的真实科目余额表应该全部能匹配。当前真实文件参与匹配末级科目 201 个，安全匹配 176 个，未匹配 25 个。你要把未匹配降到 0，不能用自动忽略凑数。

必须解决四类问题：
1. 23 条 研发支出_费用化支出_* 自动匹配 660201 减：研发费用。
2. 611101 投资收益_交易性金融资产收益 自动匹配 6111 加：投资收益，不能匹配 1101 交易性金融资产。
3. 6112 其他收益 自动匹配 6117 加：其他收益。
4. 生产成本_* 不得再出现 5002 农业生产成本 的安全候选。

实现重点：
- 增加 research_expense / development_expenditure / investment_income / other_income 语义组。
- _detect_semantic_group 要能识别 研发支出_费用化支出 和 研发支出_资本化支出，费用化归研发费用，资本化归开发支出。
- _is_safe_auto_rollup 不能再用 anchor in standard_name 判安全，必须默认用 canonical 完全等价；包含关系只能 warning，不能 warning=None。
- 不要硬编码单个科目代码映射。
- 不要改 UI、层级识别、金额拆分、导入入库逻辑。

先写失败测试，再改实现：
- 研发支出费用化支出 -> 660201
- 研发支出资本化支出 -> 1704，且不得 -> 660201
- 投资收益明细 -> 6111，且不得 -> 1101
- 其他收益 -> 6117，且不得 -> 4301/122101/4002
- 生产成本 -> 5001，且不得安全 -> 5002

验收命令：
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/ -q

cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build

真实文件验收：
运行任务文件里的“真实文件验收脚本”，必须输出 unmatched: 0，bad_safe []。

交付时汇报：
- 修改了哪些文件。
- 新增了哪些语义组。
- 真实文件参与匹配末级科目多少、未匹配多少。
- 是否仍有 bad_safe 候选。
- 测试和 npm build 是否通过。
```

## 完成标准

- 新增测试先失败后通过。
- 真实文件服务级验收 `unmatched: 0`。
- 真实文件服务级验收 `bad_safe []`。
- 后端全量测试通过。
- 前端构建通过。
- 没有 UI 回退。
