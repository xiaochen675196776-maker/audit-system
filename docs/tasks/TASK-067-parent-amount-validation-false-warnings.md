# TASK-067：修复父级金额校验误报（递归末级 + 借贷净额）

状态：OPEN
负责人：worker
优先级：P0
提出时间：2026-06-24

## 背景

真实验收文件：

```text
D:\NAS\xiaochen\李辉辉项目组\SynologyDrive\汇达228股改审计\1.账套\aglq710-科目余额表 20251231.xlsx
```

`TASK-066` 后，科目匹配已经清零：

```text
参与匹配末级科目：201
安全匹配：201
未匹配：0
bad_safe：0
执行导入：成功
```

但是分析阶段仍生成：

```text
36 条 parent_amount_mismatch warning
```

用户反馈：原始科目余额表不应存在父子金额差异。复核后确认，这 36 条是系统校验算法误报，不是原始表真的不平。

## 已定位根因

当前父级金额校验在：

```text
backend/app/services/trial_balance_transform.py
```

函数：

```python
validate_parent_amounts(rows, hierarchy)
```

当前错误逻辑：

```python
children = [row_map[ci] for ci in child_indices if ci in row_map]
leaf_children = [c for c in children if hier_map.get(c.row_index, {}).get("is_leaf", True)]
```

问题有两个。

### 问题 1：只汇总“直接末级子级”，漏掉孙级/更深层末级

真实文件有很多层级是：

```text
父级
  子级 A
    孙级 A1
    孙级 A2
  子级 B
    孙级 B1
```

当前算法只看父级的直接子级中 `is_leaf=True` 的行。若直接子级本身是父级，就不会继续向下汇总它的孙级末级。

例如：

```text
2211 应付职工薪酬
```

当前算法只汇总直接末级子级 2 行，漏掉孙级后代 6 行：

```text
直接末级子级数：2
全部后代末级数：8
```

因此系统误报：

```text
期初贷方：父级 900,000.00，直接末级合计 0.00，差 900,000.00
本期借方：父级 17,476,714.06，直接末级合计 325,607.93，差 17,151,106.13
本期贷方：父级 19,044,484.43，直接末级合计 325,607.93，差 18,718,876.50
期末贷方：父级 2,467,770.37，直接末级合计 0.00，差 2,467,770.37
```

但如果递归汇总全部后代末级：

```text
期初贷方：父级 900,000.00，全部后代末级合计 900,000.00，差 0.00
本期借方：父级 17,476,714.06，全部后代末级合计 17,476,714.06，差 0.00
本期贷方：父级 19,044,484.43，全部后代末级合计 19,044,484.43，差 0.00
期末贷方：父级 2,467,770.37，全部后代末级合计 2,467,770.37，差 0.00
```

### 问题 2：期初/期末余额不能按借贷两列分别硬比，应按净额比较

对应父级：

```text
2221 应交税费
222101 应交税费_应交增值税
```

这两类科目下，子级明细可能同时存在借方余额和贷方余额。父级在余额表上通常显示净额，只落在借方或贷方其中一列。

当前算法把：

```text
父级期初借方
```

直接和：

```text
所有子级期初借方合计
```

比较，这是错的。

正确算法应把余额转成有符号净额：

```text
期初净额 = 期初借方 - 期初贷方
期末净额 = 期末借方 - 期末贷方
```

然后比较：

```text
父级期初净额 == 全部后代末级期初净额合计
父级期末净额 == 全部后代末级期末净额合计
```

真实文件复核：

```text
2221 应交税费
期初：后代末级借方 9,215,737.98 - 后代末级贷方 6,910,493.14 = 2,305,244.84
父级期初借方 = 2,305,244.84
差额 = 0.00

期末：后代末级借方 17,074,722.59 - 后代末级贷方 16,408,761.98 = 665,960.61
父级期末借方 = 665,960.61
差额 = 0.00
```

```text
222101 应交税费_应交增值税
期初：后代末级借方 9,215,737.98 - 后代末级贷方 6,880,197.21 = 2,335,540.77
父级期初借方 = 2,335,540.77
差额 = 0.00

期末：后代末级借方 17,074,722.59 - 后代末级贷方 15,715,014.65 = 1,359,707.94
父级期末借方 = 1,359,707.94
差额 = 0.00
```

## 当前误报概览

当前系统报出的差异都来自错误算法。

### 递归后差额为 0 的误报

这些父级只要递归汇总全部后代末级，差额就是 0：

```text
2211 应付职工薪酬
500101 生产成本_基本生产成本
50010102 生产成本_基本生产成本_直接人工
5101 制造费用
510101 制造费用_人工
530101 研发支出_费用化支出
53010101 研发支出_费用化支出_人工
53010112 研发支出_费用化支出_直接投入
6601 销售费用
660101 销售费用_人工
6602 管理费用
660201 管理费用_人工
```

### 递归 + 余额净额后差额为 0 的误报

这些还需要对期初/期末余额按借贷净额比较：

```text
2221 应交税费
222101 应交税费_应交增值税
```

## 目标

修复后，真实文件分析阶段应满足：

```text
parent_amount_mismatch warning 数量：0
unmatched：0
bad_safe：0
execute_standard_import 能执行成功
```

不允许简单屏蔽 warning。必须修复校验逻辑，让它真的按正确规则计算。

## 必改文件

```text
backend/app/services/trial_balance_transform.py
backend/tests/test_standard_trial_balance_import.py
```

不要改：

```text
科目匹配规则
标准科目库
前端 UI
金额解析字段映射
导入执行逻辑
```

## 实现要求

### 1. 父级校验必须递归汇总全部后代末级

在 `validate_parent_amounts()` 中，把“直接末级子级”改成“全部后代末级”。

建议新增内部函数：

```python
def _collect_descendant_leaf_indices(parent_row_idx: int) -> list[int]:
    leaf_indices: list[int] = []
    stack = list(parent_to_children.get(parent_row_idx, []))
    while stack:
        idx = stack.pop(0)
        h = hier_map.get(idx, {})
        if h.get("is_leaf", True):
            leaf_indices.append(idx)
        else:
            stack.extend(parent_to_children.get(idx, []))
    return leaf_indices
```

然后：

```python
leaf_children = [
    row_map[idx]
    for idx in _collect_descendant_leaf_indices(parent_row_idx)
    if idx in row_map
]
```

### 2. 期初/期末余额按净额比较

新增工具函数：

```python
def _signed_balance(debit: Decimal, credit: Decimal) -> Decimal:
    return debit - credit
```

对期初余额：

```python
parent_opening_net = _signed_balance(parent_row.opening_debit, parent_row.opening_credit)
child_opening_net = sum(
    _signed_balance(c.opening_debit, c.opening_credit)
    for c in leaf_children
)
```

对期末余额：

```python
parent_ending_net = _signed_balance(parent_row.ending_debit, parent_row.ending_credit)
child_ending_net = sum(
    _signed_balance(c.ending_debit, c.ending_credit)
    for c in leaf_children
)
```

只比较净额差异：

```python
abs(parent_opening_net - child_opening_net) > Decimal("0.01")
abs(parent_ending_net - child_ending_net) > Decimal("0.01")
```

warning 文案建议：

```text
行 X「科目」父级期初净额 A 与全部后代末级净额汇总 B 不一致（差 C）
行 X「科目」父级期末净额 A 与全部后代末级净额汇总 B 不一致（差 C）
```

### 3. 本期借贷发生额仍按借方/贷方分别比较

本期发生额不是余额净额，应继续分别比较：

```python
父级本期借方发生额 == 全部后代末级本期借方发生额合计
父级本期贷方发生额 == 全部后代末级本期贷方发生额合计
```

但子级范围必须改为全部后代末级，而不是直接末级。

### 4. 保留真实差异 warning

不能把校验直接关掉。仍需保留：

```text
如果父级净额或发生额与全部后代末级汇总确实不一致，应继续生成 parent_amount_mismatch warning。
```

## 必须新增/修改测试

在 `backend/tests/test_standard_trial_balance_import.py` 增加测试。

### 1. 多层级父级应递归汇总孙级末级，不应误报

构造数据：

```python
rows = [
    ["5001", "生产成本", "0", "0", "100", "100", "0", "0"],
    ["500101", "生产成本_基本生产成本", "0", "0", "100", "100", "0", "0"],
    ["50010101", "生产成本_基本生产成本_直接材料", "0", "0", "40", "40", "0", "0"],
    ["50010102", "生产成本_基本生产成本_直接人工", "0", "0", "60", "60", "0", "0"],
]
```

断言：

```python
parent_amount_mismatch warning 数量 == 0
```

这个测试会覆盖“父级的直接子级是父级时，必须继续向下汇总孙级末级”。

### 2. 期初/期末余额应按借贷净额比较

构造数据：

```python
rows = [
    ["2221", "应交税费", "300", "0", "100", "100", "200", "0"],
    ["222101", "应交税费_应交增值税", "1000", "700", "60", "60", "900", "700"],
    ["222102", "应交税费_企业所得税", "0", "0", "40", "40", "0", "0"],
]
```

含义：

```text
期初子级净额 = 1000 - 700 = 300，等于父级期初借方 300
期末子级净额 = 900 - 700 = 200，等于父级期末借方 200
本期借方 = 60 + 40 = 100
本期贷方 = 60 + 40 = 100
```

断言：

```python
parent_amount_mismatch warning 数量 == 0
```

### 3. 真实差异仍应 warning

构造数据：

```python
rows = [
    ["1001", "库存现金", "100", "0", "0", "0", "100", "0"],
    ["100101", "库存现金_人民币", "90", "0", "0", "0", "90", "0"],
]
```

断言：

```python
parent_amount_mismatch warning 数量 >= 1
```

这个测试确保没有把校验整体关掉。

## 真实文件验收脚本

修复后运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
@'
import asyncio
import uuid
from collections import Counter
from pathlib import Path
from app.core.database import async_session_factory, engine
from app.services.standard_trial_balance_import_service import preview_standard_import, analyze_standard_import

engine.echo = False
file_path = list(Path(r"D:\NAS\xiaochen").rglob("aglq710-*20251231.xlsx"))[0]

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

async def main():
    async with async_session_factory() as db:
        preview = await preview_standard_import(
            db=db,
            file_path=str(file_path),
            file_name=file_path.name,
            fiscal_year=2025,
            period=12,
            customer_label="TASK-067-realfile-rollback",
            source_label="acceptance",
        )
        analyze = await analyze_standard_import(
            db=db,
            batch_id=uuid.UUID(preview["batch_id"]),
            file_path=str(file_path),
            field_mappings=field_mappings,
            fiscal_year=2025,
            period=12,
            customer_label="TASK-067-realfile-rollback",
            source_label="acceptance",
            hierarchy_mode="auto",
        )
        counts = Counter(w.get("category") for w in analyze.get("warnings", []))
        print("WARNING_COUNTS", dict(counts))
        for w in analyze.get("warnings", []):
            print("WARNING", w)
        await db.rollback()

asyncio.run(main())
'@ | D:\python\python.exe -
```

期望：

```text
WARNING_COUNTS {}
```

或至少：

```text
parent_amount_mismatch 不存在
```

## 自动化验证

必须执行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/ -q

cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 给弱模型的领取提示词

```text
你负责实现 docs/tasks/TASK-067-parent-amount-validation-false-warnings.md。

工作目录：
D:\APP\Codex-项目\13、审计系统

先读：
- docs/tasks/TASK-067-parent-amount-validation-false-warnings.md
- backend/app/services/trial_balance_transform.py
- backend/tests/test_standard_trial_balance_import.py

问题：
真实科目余额表没有父子金额差异，但系统误报 36 条 parent_amount_mismatch。根因不是数据问题，是 validate_parent_amounts 算法错：
1. 只汇总直接末级子级，漏掉孙级/更深层末级。
2. 期初/期末余额按借贷两列分别比较，应该按净额：借方 - 贷方。

必须改：
- validate_parent_amounts 要递归收集全部后代末级。
- 期初/期末用净额比较。
- 本期借方/本期贷方仍分别比较，但子级范围必须是全部后代末级。
- 不要关闭 warning；真实不一致仍要报 warning。

必须补测试：
- 多层父级递归汇总孙级末级，不误报。
- 应交税费这类借贷余额混合时，用净额比较，不误报。
- 人为制造真实差异时，仍然报 parent_amount_mismatch。

验收：
真实文件脚本输出 WARNING_COUNTS {}，或至少 parent_amount_mismatch 不存在。

运行：
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/ -q
npm run build
```

## 完成标准

- 真实文件不再出现 `parent_amount_mismatch`。
- 科目匹配仍保持 `unmatched = 0`。
- 真实不一致场景仍能产生 warning。
- 后端测试通过。
- 前端构建通过。
