# TASK-070：修复包装物/低值易耗品“带明细后缀”仍误入周转材料

> 交给其他 AI 执行时，请完整复制本文件。不要只看标题。  
> 本任务是 TASK-068 的补强验收缺口，只改科目匹配逻辑，不改 UI。

## 验收发现

TASK-068 已经修好精确名称场景：

```text
1411 包装物       -> SAFE_FIRST 141101 包装物
1411 低值易耗品   -> SAFE_FIRST 141102 低值易耗品
1411 周转材料     -> SAFE_FIRST 1411 周转材料
```

但真实账套经常会有明细后缀，例如：

```text
1411 包装物_纸箱
1411 低值易耗品_工具
```

当前代码仍然错误：

```text
CLIENT 1411 包装物_纸箱
SAFE_FIRST 1411 周转材料 code_match 0.95
CAND 1411 周转材料 code_match 0.95 warning=None
CAND 141101 包装物 name_similarity 0.77 warning=名称相似度仅 75%，建议人工确认

CLIENT 1411 低值易耗品_工具
SAFE_FIRST 1411 周转材料 code_match 0.95
CAND 1411 周转材料 code_match 0.95 warning=None
CAND 141102 低值易耗品 name_similarity 0.82 warning=名称相似度仅 83%，建议人工确认
```

这说明 TASK-068 只处理了 `name_exact`，没有处理“客户名称包含更精确标准子级名称”的场景。

## 目标

修复后必须满足：

```text
客户 1411 包装物_纸箱       -> 安全首选 141101 包装物
客户 1411 包装物-包装袋     -> 安全首选 141101 包装物
客户 1411 低值易耗品_工具   -> 安全首选 141102 低值易耗品
客户 1411 低值易耗品-办公椅 -> 安全首选 141102 低值易耗品
客户 1411 周转材料          -> 安全首选 1411 周转材料
```

并且：

- `1411 包装物_* -> 1411 周转材料` 不能是 `warning=None` 且 `score>=0.9` 的安全候选。
- `1411 低值易耗品_* -> 1411 周转材料` 不能是 `warning=None` 且 `score>=0.9` 的安全候选。
- 如果保留 `1411 周转材料` 候选，必须降级为 `code_match_conflict`，`score < 0.9`，并给 warning。
- 不要把标准库层级改掉：`141101/141102` 仍然属于 `1411` 子级。
- 不要改数据查看 UI。

## 根因

位置：

```text
backend/app/services/client_account_mapping_service.py
```

当前 TASK-068 逻辑大概率只在存在 `name_exact` 候选时触发：

```text
exact code: 1411 -> 周转材料
exact name: 包装物 -> 141101 包装物
```

但当客户名称为 `包装物_纸箱` 时，`141101 包装物` 只能作为 `name_similarity` 出现，且相似度 warning 非空；这时 `1411 周转材料` 仍保留为安全 `code_match`。

正确逻辑应是：

当客户名称的开头或分段锚点明确包含一个更精确的标准子级名称时，即使不是 `name_exact`，也应把该子级视为更强语义候选，并降级冲突的父级 code_match。

## 实施要求

### 1. 新增失败测试

修改：

```text
backend/tests/test_client_account_mapping_service.py
```

新增测试：

```python
@pytest.mark.asyncio
async def test_exact_code_parent_detail_name_prefix_prefers_child(self, db):
    """客户代码命中父级，但名称以更精确子级名称开头时，应优先子级"""
    parent = _make_standard_account("1411", "周转材料")
    packaging = _make_standard_account("141101", "包装物", parent_id=parent.id)
    consumables = _make_standard_account("141102", "低值易耗品", parent_id=parent.id)
    parent.is_leaf = False
    packaging.is_leaf = True
    consumables.is_leaf = True
    db.add_all([parent, packaging, consumables])
    await db.flush()

    cases = [
        ("1411", "包装物_纸箱", "141101"),
        ("1411", "包装物-包装袋", "141101"),
        ("1411", "低值易耗品_工具", "141102"),
        ("1411", "低值易耗品-办公椅", "141102"),
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
            f"{client_code} {client_name} 应安全首选 {expected_code}，实际安全候选: {safe}"
        )

        bad_parent = [
            c for c in candidates
            if c["standard_account_code"] == "1411"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert not bad_parent, f"父级 1411 周转材料不得作为安全候选: {bad_parent}"
```

同时保留 TASK-068 的测试：

```text
1411 包装物 -> 141101 包装物
1411 低值易耗品 -> 141102 低值易耗品
1411 周转材料 -> 1411 周转材料
```

### 2. 修复匹配器

推荐做法：

在 `client_account_mapping_service.py` 中新增一个“名称前缀/分段锚点命中标准科目”的逻辑。

判断规则：

```text
客户名称 canonical = 包装物纸箱
标准子级 canonical = 包装物
如果客户名称以标准子级 canonical 开头，或者客户名称分段第一段等于标准子级 canonical：
  认为该标准子级是强语义候选
```

分隔符应覆盖：

```text
_ - — – / \ | · ． 、 : ： ; ； , ， 空格 括号
```

建议实现函数：

```python
def _client_name_starts_with_standard_name(client_name: str | None, standard_name: str | None) -> bool:
    client_canonical = _canonical_name(client_name)
    standard_canonical = _canonical_name(standard_name)
    if not client_canonical or not standard_canonical:
        return False
    if client_canonical == standard_canonical:
        return True
    if client_canonical.startswith(standard_canonical):
        return True

    tokens = _split_name_tokens(client_name or "")
    if tokens:
        first_token = _canonical_name(tokens[0])
        return first_token == standard_canonical
    return False
```

然后在候选构造阶段增加一个候选来源，例如：

```text
source = "name_prefix"
score = 0.93
warning = None
reason = "客户科目名称以标准科目名称开头，按更精确标准科目匹配"
```

也可以不新增来源，复用 `name_anchor` 或增强 `name_similarity`，但必须满足：

- `141101 包装物` / `141102 低值易耗品` 进入安全候选；
- 排在冲突的 `1411 周转材料` 前；
- 父级 `1411 周转材料` 被降级为 `code_match_conflict`。

### 3. 降级冲突 code_match

扩展 TASK-068 的 `_resolve_exact_code_vs_exact_name_conflict()` 或新增类似函数，让它不只看 `name_exact`，也看 `name_prefix` 强候选：

```text
如果存在安全名称强候选，且它与 code_match 指向不同标准科目：
  code_match -> code_match_conflict
  score <= 0.75
  warning 说明客户名称更精确匹配 141101/141102，不应自动归入 1411 周转材料
```

注意：`1411 周转材料` 自己仍然必须安全匹配父级。

### 4. 不要扩大误匹配

不要把任意 `startswith` 都做成高分安全候选。至少要限制：

- 标准科目名称长度 >= 2；
- 标准科目必须 active；
- 客户名称第一段或开头明确命中标准名称；
- 如果标准名称是过于泛化的父级，例如“资产”“费用”“其他”，不要因为 startswith 自动安全匹配。

可以设置一个黑名单：

```python
_GENERIC_NAME_PREFIX_BLOCKLIST = {"资产", "负债", "权益", "收入", "成本", "费用", "其他", "减", "加"}
```

## 验收命令

必须全部通过：

```powershell
cd backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/ -q
```

最小脚本必须输出正确：

```powershell
cd backend
$env:PYTHONIOENCODING='utf-8'
@'
import asyncio
from app.core.database import async_session_factory, engine
from app.services.client_account_mapping_service import recommend_mappings

engine.echo = False

async def main():
    cases = [
        {"client_account_code": "1411", "client_account_name": "包装物_纸箱"},
        {"client_account_code": "1411", "client_account_name": "低值易耗品_工具"},
        {"client_account_code": "1411", "client_account_name": "周转材料"},
    ]
    async with async_session_factory() as db:
        results = await recommend_mappings(db, data_type="trial_balance", client_accounts=cases)
        for case, result in zip(cases, results):
            safe = [c for c in result["candidates"] if c.get("warning") is None and c.get("score", 0) >= 0.9]
            print(case["client_account_code"], case["client_account_name"], "SAFE_FIRST=", safe[0]["standard_account_code"], safe[0]["standard_account_name"])

asyncio.run(main())
'@ | D:\python\python.exe -
```

期望：

```text
1411 包装物_纸箱 SAFE_FIRST=141101 包装物
1411 低值易耗品_工具 SAFE_FIRST=141102 低值易耗品
1411 周转材料 SAFE_FIRST=1411 周转材料
```

## 给执行 AI 的提示词

你来领取并执行这个任务：

```text
D:/APP/Codex-项目/13、审计系统/docs/tasks/TASK-070-packaging-consumables-detail-name-conflict.md
```

请完整阅读任务文件后再动代码。只改科目匹配逻辑，不要改 UI。  
当前 TASK-068 只修好了 `1411 包装物` 精确名称，但 `1411 包装物_纸箱`、`1411 低值易耗品_工具` 仍然会安全首选父级 `1411 周转材料`。这是错误的。  
要求：当客户代码命中父级，但客户名称第一段或开头明确是更精确标准子级名称时，应安全首选子级；父级 code_match 必须降级为 `code_match_conflict`，不能作为 warning=None 且 score>=0.9 的候选。  
先写失败测试，再改 `backend/app/services/client_account_mapping_service.py`。验收必须跑 `test_client_account_mapping_service.py`、`test_standard_trial_balance_import.py`、全量后端测试，并运行任务文件中的最小脚本。
