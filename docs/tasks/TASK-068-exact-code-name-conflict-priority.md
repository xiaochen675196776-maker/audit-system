# TASK-068：修复“代码命中但名称更精确”导致包装物/低值易耗品误入周转材料

> 交给其他 AI 执行时，请完整复制本文件。不要只看标题。  
> 目标是修复科目匹配逻辑，不要改数据查看 UI；UI 另见 TASK-069。

## 背景

用户反馈：包装物、低值易耗品为什么会入到周转材料下面。

经验证，标准库当前关系是：

```text
1411   周转材料       parent=None, is_leaf=False
141101 包装物         parent=1411 周转材料, is_leaf=True
141102 低值易耗品     parent=1411 周转材料, is_leaf=True
```

如果只是查询树里显示 `141101 包装物`、`141102 低值易耗品` 挂在 `1411 周转材料` 下面，这是标准科目层级，不是错误。

真正的问题是匹配器存在优先级缺陷：当客户科目代码等于父级标准科目代码，但客户科目名称等于更精确的标准明细科目时，系统会把父级 `code_match` 放到第一位且无 warning，导致自动确认可能写入父级。

已用当前代码复现：

```text
CLIENT 1411 包装物
  1411 周转材料 score=0.95 source=code_match warning=None
  141101 包装物 score=0.94 source=name_exact warning=None

CLIENT 1411 低值易耗品
  1411 周转材料 score=0.95 source=code_match warning=None
  141102 低值易耗品 score=0.94 source=name_exact warning=None
```

这不符合用户之前反复强调的原则：标准库代码不一定等于客户代码，不能只按代码匹配；名称语义明显更准确时，应优先按名称/语义匹配。

## 目标

修复后应满足：

```text
客户 1411 包装物       -> 安全首选 141101 包装物
客户 1411 低值易耗品   -> 安全首选 141102 低值易耗品
客户 141101 包装物     -> 安全首选 141101 包装物
客户 141102 低值易耗品 -> 安全首选 141102 低值易耗品
客户 1411 周转材料     -> 安全首选 1411 周转材料
```

并且：

- `1411 包装物 -> 1411 周转材料` 不得作为 warning=None 且 score>=0.9 的安全候选。
- 如果保留 `1411 周转材料` 候选，必须降级为 `code_match_conflict`，score < 0.9，warning 说明“代码相同但名称更像包装物/低值易耗品”。
- 不得破坏 TASK-064/065/066/067 已修好的真实文件全量匹配能力。

## 根因

位置：

```text
backend/app/services/client_account_mapping_service.py
```

当前 `recommend_mappings()` 大致顺序是：

1. company history
2. global history
3. code exact match
4. name exact match
5. semantic alias / name similarity / fallback

`_build_code_match_candidate()` 里虽有 `_check_code_match_name_conflict()`，但冲突检测依赖 `_detect_name_anchor(client_name)`。如果 `包装物`、`低值易耗品` 没有进入锚点识别，或者锚点检测没有把“标准库存在同名明细科目”作为冲突依据，那么 `1411 包装物` 会被错误判定为安全 code_match。

## 实施要求

### 1. 新增失败测试

修改：

```text
backend/tests/test_client_account_mapping_service.py
```

新增测试类或加到现有 `TestSemanticAccountMatching` / `TestSafeAutoRollup` 里。

必须覆盖以下用例：

```python
@pytest.mark.asyncio
async def test_exact_code_parent_name_exact_child_prefers_child(self, db):
    """客户代码命中父级标准科目，但名称精确命中子级时，应优先子级"""
    parent = _make_standard_account("1411", "周转材料")
    packaging = _make_standard_account("141101", "包装物", parent_id=parent.id)
    consumables = _make_standard_account("141102", "低值易耗品", parent_id=parent.id)
    parent.is_leaf = False
    packaging.is_leaf = True
    consumables.is_leaf = True
    db.add_all([parent, packaging, consumables])
    await db.flush()

    cases = [
        ("1411", "包装物", "141101"),
        ("1411", "低值易耗品", "141102"),
    ]

    for client_code, client_name, expected_code in cases:
        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            client_accounts=[{
                "client_account_code": client_code,
                "client_account_name": client_name,
            }],
        )
        candidates = results[0]["candidates"]

        safe = [
            c for c in candidates
            if c["warning"] is None and c["score"] >= 0.9
        ]
        assert safe, f"{client_code} {client_name} 应有安全候选，实际: {candidates}"
        assert safe[0]["standard_account_code"] == expected_code, (
            f"{client_code} {client_name} 应优先匹配 {expected_code}，实际安全候选: {safe}"
        )

        bad_safe_parent = [
            c for c in candidates
            if c["standard_account_code"] == "1411"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert not bad_safe_parent, f"父级 1411 周转材料不得作为安全候选: {bad_safe_parent}"
```

同时新增保底测试，避免把正常周转材料破坏掉：

```python
@pytest.mark.asyncio
async def test_exact_code_parent_name_same_still_matches_parent(self, db):
    """客户就是周转材料时，仍应匹配 1411 周转材料"""
    parent = _make_standard_account("1411", "周转材料")
    child = _make_standard_account("141101", "包装物", parent_id=parent.id)
    parent.is_leaf = False
    child.is_leaf = True
    db.add_all([parent, child])
    await db.flush()

    results = await recommend_mappings(
        db,
        data_type="trial_balance",
        client_accounts=[{
            "client_account_code": "1411",
            "client_account_name": "周转材料",
        }],
    )
    candidates = results[0]["candidates"]
    safe = [
        c for c in candidates
        if c["standard_account_code"] == "1411"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert safe, f"1411 周转材料仍应安全匹配父级，实际: {candidates}"
```

运行单测，确认新增测试先失败：

```powershell
cd backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
```

预期：第一个新增测试失败，表现为安全首选仍是 `1411 周转材料`。

### 2. 修复候选优先级

推荐方案：

在 `recommend_mappings()` 构造完 code exact 和 name exact 候选后，做一次候选重排/降级：

- 如果存在 `name_exact` 候选，且其 `standard_account_code` 不等于客户代码精确命中的 `code_match` 候选；
- 且 `name_exact.standard_account_name` 与客户名称规范化后完全相同；
- 则 `name_exact` 应排到 `code_match` 前面；
- 同时原 `code_match` 如果名称不等价，应降级为 `code_match_conflict` 或至少 warning 非空、score < 0.9。

不要简单把所有 `name_exact` 都排到所有 `code_match` 前面，否则可能破坏“代码名称一致”的安全场景。

可实现为一个小函数，例如：

```python
def _resolve_exact_code_vs_exact_name_conflict(entry: dict, client_name: str) -> None:
    ...
```

逻辑建议：

```python
code_candidates = [c for c in entry["candidates"] if c["source"] == "code_match"]
name_candidates = [c for c in entry["candidates"] if c["source"] == "name_exact"]
if not code_candidates or not name_candidates:
    return

best_name = name_candidates[0]
for code_candidate in code_candidates:
    if code_candidate["standard_account_id"] == best_name["standard_account_id"]:
        continue
    # 客户名称和 name_exact 候选完全等价，但和 code_match 标准名称不等价
    # 此时 code_match 不应安全自动确认
    code_candidate["source"] = "code_match_conflict"
    code_candidate["score"] = min(float(code_candidate.get("score", 0.75)), 0.75)
    code_candidate["warning"] = (
        f"代码相同但名称不一致：客户科目名称「{client_name}」"
        f"更精确匹配标准科目「{best_name['standard_account_code']} {best_name['standard_account_name']}」，"
        f"不应自动归入「{code_candidate['standard_account_code']} {code_candidate['standard_account_name']}」，请人工确认"
    )
```

重排时保证：

```python
entry["candidates"].sort(key=_candidate_priority)
```

或者只把 `name_exact` 插到冲突 code 之前。不要破坏已有优先级：

```text
company_history > global_history > 安全 code_match/name_exact > semantic_alias/name_anchor > fallback warning 候选
```

关键是：当 exact code 和 exact name 指向不同标准科目时，名称精确命中应优先于代码命中，代码命中降级。

### 3. 补强锚点或同名检测

如果当前 `_detect_name_anchor()` 没有覆盖以下词，补充：

```text
包装物
低值易耗品
周转材料
```

但不要只靠词表。更稳的是：当客户名称存在标准科目名称精确命中时，用 name_exact 作为冲突判断依据。这样未来“客户代码冲突但名称精确”的场景也能被覆盖。

### 4. 不要改标准库层级

不要把 `141101 包装物`、`141102 低值易耗品` 从 `1411 周转材料` 下移出去。

这个层级本身是标准库设计：

```text
1411 周转材料
  141101 包装物
  141102 低值易耗品
```

本任务只处理“客户科目写入哪个标准科目”的匹配问题。

## 验收命令

必须全部通过：

```powershell
cd backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/ -q
```

还要跑一个最小脚本，输出必须符合下面结果：

```powershell
cd backend
$env:PYTHONIOENCODING='utf-8'
@'
import asyncio
from app.core.database import async_session_factory
from app.services.client_account_mapping_service import recommend_mappings

async def main():
    cases = [
        {"client_account_code": "1411", "client_account_name": "包装物"},
        {"client_account_code": "1411", "client_account_name": "低值易耗品"},
        {"client_account_code": "1411", "client_account_name": "周转材料"},
    ]
    async with async_session_factory() as db:
        results = await recommend_mappings(db, data_type="trial_balance", client_accounts=cases)
        for case, result in zip(cases, results):
            safe = [c for c in result["candidates"] if c.get("warning") is None and c.get("score", 0) >= 0.9]
            print(case, "SAFE_FIRST=", safe[0]["standard_account_code"], safe[0]["standard_account_name"])

asyncio.run(main())
'@ | D:\python\python.exe -
```

期望：

```text
1411 包装物 SAFE_FIRST=141101 包装物
1411 低值易耗品 SAFE_FIRST=141102 低值易耗品
1411 周转材料 SAFE_FIRST=1411 周转材料
```

## 给执行 AI 的提示词

你是执行 TASK-068 的代码代理。请只修复科目匹配，不要改 UI。  
当前缺陷：客户科目 `1411 包装物`、`1411 低值易耗品` 会因为代码精确命中优先，被安全匹配到标准父级 `1411 周转材料`，但标准库里有更精确的 `141101 包装物`、`141102 低值易耗品`。  
要求：当 exact code 和 exact name 指向不同标准科目时，名称精确命中优先；原代码命中必须降级为 warning 候选，不能作为 score>=0.9 且 warning=None 的自动候选。  
先写失败测试，再改 `backend/app/services/client_account_mapping_service.py`，最后跑 `test_client_account_mapping_service.py`、`test_standard_trial_balance_import.py` 和全量后端测试。不要改标准库层级，不要动数据查看 UI。
