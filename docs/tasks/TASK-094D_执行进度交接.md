# TASK-094D 执行进度交接文档

> 仓库: `xiaochen675196776-maker/audit-system`
> 任务文档: `D:\APP\谷歌\文件下载\TASK-094D_跳过行分类与勾稽口径统一.md`
> 当前分支: `master`
> 前置任务: TASK-094A/B/C 已完成

---

## 一、已完成 ✅

### 1.1 后端核心实现 (`backend/app/services/standard_trial_balance_import_service.py`)

新增 dataclass 与函数（位于文件 250-560 行附近）：

```python
@dataclass
class RowClassificationResult:
    """5 类行集合 + structural_rows + base_leaf_rows"""
    eligible_business_leaf_rows: set[int]
    zero_amount_template_rows: set[int]
    summary_total_rows: set[int]
    duplicate_aggregate_rows: set[int]
    ignored_business_rows: set[int]
    base_leaf_rows: set[int]
    structural_rows: set[int]

def classify_import_rows(*, rows, period_configs, col_id_to_index,
                          code_col_id, name_col_id, hierarchy,
                          user_ignored_rows=set(), tolerance=None) -> RowClassificationResult:
    """TASK-094D：Analyze 与 Execute 共用入口"""

def summarize_amount_reconciliation(...) -> dict:
    """业务金额勾稽：total_business = entry + ignored"""

def summarize_summary_reconciliation(...) -> dict:
    """汇总/重复 父子金额勾稽"""
```

**关键设计要点**：
- `classify_import_rows` 同时检测「合计/小计/总计」关键词 **和** 页脚/配置关键词
  （`不过帐`/`不记帐`/`核算单位`/`制单人`等，旧逻辑放在 `_collect_summary_total_skip_rows`）
- duplicate_aggregate 检测：父级（is_summary=True）且无关键词 + 金额 ≈ 子级汇总
- 5 类 leaf 互斥分配：ignored > summary_total > zero > duplicate > eligible
- `structural_rows = 父级 ∪ summary_leaf ∪ duplicate_leaf` 用于 build_account_tree 排除

**Analyze 与 Execute 都改为调用同一函数**：
- Analyze (line ~1145): `classification = classify_import_rows(user_ignored_rows=set())`
- Execute (line ~2080): `execute_classification = classify_import_rows(user_ignored_rows=ignored_row_set)`

### 1.2 数量与金额勾稽重构

**5 类行集合恒等式校验**（Execute line ~2543）：
```python
raw_identified_leaf_count = (len(eligible) + len(zero) + len(summary)
                            + len(duplicate) + len(ignored))
# 校验：participating_leaf_count == raw_identified_leaf_count
# 校验：entry_count == len(eligible_business_leaf_rows)
```

**业务金额勾稽**（仅用真正业务末级）：
```python
business_amount_reconciliation[field] = {
    "source": str(eligible + ignored),
    "entry": str(entry_amount_totals[field]),
    "eligible": str(eligible_total),
    "ignored": str(ignored_total),
    "difference": str(diff),
    "ok": "true/false",
}
```

**汇总/重复父子金额勾稽**（与业务勾稽分离）：
```python
summary_amount_reconciliation[row_idx] = {
    "fields": {field: {"self", "children_sum", "difference", "ok"}},
    "mismatch_count": int,
    "warning": "summary_amount_mismatch" | None,
}
```

### 1.3 API 响应更新

**`backend/app/schemas/standard_trial_balance.py`**：
- `ExecuteResponse` 新增字段：`raw_identified_leaf_count`, `eligible_business_leaf_count`,
  `ignored_business_count`, `zero_template_count`, `summary_total_count`,
  `duplicate_aggregate_count`, `business_amount_reconciliation`,
  `summary_amount_reconciliation`, `classification`
- 旧字段标记 `deprecated`：`participating_leaf_count`, `ignored_leaf_count`,
  `zero_amount_skipped_leaf_count`, `amount_reconciliation`
- `AnalyzeResponse` 新增相同字段（与 Execute 同口径）

### 1.4 前端类型更新 (`frontend/src/types/index.ts`)

`StdAnalyzeResponse` 与 `StdExecuteResponse` 都新增：
- `raw_identified_leaf_count?`, `eligible_business_leaf_count?`,
  `ignored_business_count?`, `zero_template_count?`,
  `summary_total_count?`, `duplicate_aggregate_count?`
- `classification?` (5 类行集合 + base_leaf_rows + structural_rows)
- `business_amount_reconciliation?`, `summary_amount_reconciliation?`

### 1.5 回归测试改造 (`backend/tests/test_anchor_inheritance_regression.py`)

- `_amount_differences()` 改为 `_business_amount_reconciliation_diff()` 优先读取新字段
- `report_row` 新增 5 类计数字段
- 断言更新为：
  ```python
  # 5 类行集合勾稽
  assert raw_identified_leaf_count == eligible + ignored + zero + summary + duplicate
  # entry == eligible
  assert entry_count == eligible_business_leaf_count
  # 业务金额勾稽
  for field, diff in amount_differences.items():
      assert abs(diff) <= 0.01
  ```
- 报告生成（md/json）更新为新口径

### 1.6 entry reconciliation 测试更新 (`backend/tests/test_task_093_entry_reconciliation.py`)

改为验证新字段：
- `raw_identified_leaf_count`, `eligible_business_leaf_rows` 等
- 旧字符串 `"participating_leaf_count == entry_count + ignored_leaf_count + zero_amount_skipped_leaf_count"` 已替换为：
  `"base_leaf_rows == eligible + zero + summary + duplicate + ignored"`

---

## 二、已完成但未验证（待回归跑通）

### 2.1 完整六表回归测试

`pytest tests/test_anchor_inheritance_regression.py` 验证：
- 5/6 通过（huizhan/112/tb_2023/yiliao/chengdu_dikang）
- 205201 文件 跑一次 ~3 分钟
- 整体跑 6 文件 ~15-20 分钟

**当前已知状态**：未跑通完整 6 文件，因 205201 调试过程中被打断

### 2.2 仍待新增的 TASK-094D 专项测试（任务文档第 10 节要求）

需要新增 `backend/tests/test_task_094d_*.py` 共 3 个：
- `test_task_094d_row_classification.py` — 分类函数单测
- `test_task_094d_business_reconciliation.py` — 业务金额勾稽
- `test_task_094d_summary_reconciliation.py` — 汇总金额勾稽

任务文档列出的 10 项覆盖场景待补：
1. 零模板识别
2. 非零合计行不识别为 zero
3. 小计行不生成 entry
4. duplicate aggregate 不生成 entry
5. 业务末级全部生成 entry
6. Analyze/Execute 分类一致
7. 业务金额勾稽
8. 汇总金额勾稽
9. 汇总不计入业务来源金额
10. API 计数字段一致

---

## 三、未完成 ❌

### 3.1 前端展示更新（任务文档第 8 节）

需要修改 `frontend/src/views/DataImportView.vue`，将"零金额模板/汇总/小计/重复汇总"分类展示。**当前仅更新了 TypeScript 类型，未修改 Vue 组件**。

### 3.2 完成报告生成（任务文档第 12 节）

- 六表回归报告 JSON/CSV/MD（更新 schema 已完成）
- 完成报告 markdown：`docs/tasks/TASK-094D_完成报告.md`（**未创建**）
- TASK-093 完成报告已更新含 094D 口径（**已修改**）
- commit + push（**未执行**）

### 3.3 删除已废弃函数（可选清理）

- `_collect_zero_amount_template_rows` 与 `_collect_summary_total_skip_rows` 在
  `standard_trial_balance_import_service.py` 中仍有引用（acceptance_task078 / 080 / 086
  脚本可能用到），建议保留但标记 deprecated

---

## 四、根因记录（避免重蹈覆辙）

### 4.1 旧 auto_skip_rows vs 新 classify_import_rows

旧 `_collect_summary_total_skip_rows` 检查三种关键词：
1. **合计/小计/总计** 关键词（24 个变体）
2. **页脚元数据** 关键词（`核算单位`/`制单人`/`打印时间`/...）
3. **配置科目/非过帐** 关键词（`不过帐`/`不记帐`/`不记账`/`设置用`/...）

**TASK-094D 第一版只检查第 1 类，导致 205201 文件多识别 ~1348 个 leaf 行为 eligible，
unmapped 从 0 → 1416 触发 execute 阻断。** 已修复（line ~522），三种关键词均检测。

### 4.2 容易踩的坑

- `participates_in_entry` 是基于 `execute_auto_skip_rows` 计算的，旧代码在 Execute 阶段
  **不过滤父级**（依赖后续 `& base_leaf_rows`），新代码已改为 leaf-only 计算避免歧义
- `structural_skipped_leaf_rows`（mapping_role == "structural_summary"）在树构建**之后**才确定，
  必须在 unmapped check **之前**对 5 类行集合做差集，否则重复扣减
- legacy `amount_reconciliation` 字段保留 `zero_skip = zero_amount_template_leaf_rows` 的口径，
  与新 `business_amount_reconciliation` 共存（用 `amount_reconciliation_deprecated: true` 标识）

---

## 五、关键文件位置速查

| 文件 | 关键改动 |
|---|---|
| `backend/app/services/standard_trial_balance_import_service.py` | 新增 `RowClassificationResult` (line ~319)、`classify_import_rows` (line ~368)、`summarize_amount_reconciliation` (line ~542)、`summarize_summary_reconciliation` (line ~589)、Analyze 与 Execute 改用同一分类函数 |
| `backend/app/schemas/standard_trial_balance.py` | `ExecuteResponse` / `AnalyzeResponse` 新增 5 类计数 + 新 reconciliation 字段 |
| `frontend/src/types/index.ts` | `StdAnalyzeResponse` / `StdExecuteResponse` 类型扩展 |
| `backend/tests/test_anchor_inheritance_regression.py` | 5 类计数验证 + `_business_amount_reconciliation_diff()` |
| `backend/tests/test_task_093_entry_reconciliation.py` | 验证新分类字段 + 新勾稽字符串 |

---

## 六、接手后的执行清单

1. 跑回归（建议先单文件）：
   ```bash
   cd backend
   pytest tests/test_anchor_inheritance_regression.py -k "205201"  # ~3min
   pytest tests/test_anchor_inheritance_regression.py             # ~18min
   ```
2. 新增 `tests/test_task_094d_*.py` 3 个测试文件（任务文档第 10 节）
3. 修改 `frontend/src/views/DataImportView.vue` 展示 5 类行（任务文档第 8 节）
4. 生成完成报告 `docs/tasks/TASK-094D_完成报告.md`
5. commit + push

---

> 交接时间: 2026-06-27
> 交接人: Mavis (MiniMax-M3)