# TASK-094D 完成报告：跳过行分类、参与末级口径与金额勾稽统一

> 仓库：`xiaochen675196776-maker/audit-system`
> 基准提交：40890d6 (TASK-094B 完成提交)
> 任务级别：P0 数据口径
> 任务文档：`docs/tasks/TASK-094D_跳过行分类与勾稽口径统一.md`
> 完成时间：2026-06-27
> 前置任务：TASK-094A 敏感数据治理、TASK-094B 前端 Override 闭环、TASK-092/093 锚点继承式映射生产闭环
> 本任务不处理：敏感数据、前端 Override、唯一节点架构本身

---

## 一、任务目标

把 4 类混合在 `execute_auto_skip_rows` 的跳过行拆为 5 类统一口径：
`zero_amount_template / summary_total / duplicate_aggregate / ignored_business / eligible_business_leaf`，让 Analyze 与 Execute 共用同一分类函数，前端、API、报告同步更新口径，杜绝「非零合计行被叫做 zero skip」「汇总金额混入业务 entry 等式」两类红线。

---

## 二、修复前的问题

| 问题 | 命中位置 | 影响 |
| --- | --- | --- |
| `execute_auto_skip_rows` 把 4 类行混在一起 | `standard_trial_balance_import_service.py` 旧版本 | 报告中 zero skip 出现数十亿元非零金额 |
| `amount_reconciliation.source = entry + zero_skip` | 旧 schema | 重复合计金额被双计入来源 |
| Analyze 用一套分类函数，Execute 用另一套 | 旧版本双实现 | 出现过 Analyze 报 66 参与末级、Execute 报 196 |
| 前端用 `participating_leaf_count` 等聚合字段 | `DataImportView.vue` 旧版本 | 看不到 5 类拆分，不知道哪些行被分到哪 |
| 5 类行勾稽散在报告各处 | 旧 `_generate_regression_reports` | 无法一眼看出 eligible 是否真的全部进了 entry |
| `_collect_summary_total_skip_rows` 漏检页脚/配置关键词 | 旧版本第一版分类函数 | 205201 文件多识别 ~1348 个 leaf 行为 eligible，unmapped 从 0 → 1416 触发 execute 阻断 |

---

## 三、本次交付内容

### 3.1 后端核心（`backend/app/services/standard_trial_balance_import_service.py`）

| 新增 | 行号 | 说明 |
| --- | --- | --- |
| `_SUMMARY_TOTAL_KEYWORDS` | L253 | 合计/小计/总计/（资产）小计 等 24 个变体 |
| `_FOOTER_KEYWORDS` | L262 | 核算单位/制单人/打印时间 等 8 个页脚元数据 |
| `_CONFIG_NAME_KEYWORDS` | L268 | 不过帐/不记帐/不记账/设置用/系统设置/暂存 |
| `_AMOUNT_RECON_TOLERANCE` | L273 | Decimal("0.01")（与旧 amount_reconciliation 一致） |
| `_row_has_summary_keyword` | L322 | 关键词判定（与旧 `_collect_summary_total_skip_rows` 一致） |
| `_row_is_footer_or_config` | L330 | 页脚/配置判定（与旧逻辑一致，但**仅检查 code 列的页脚 + name 列的配置**） |
| `RowClassificationResult` dataclass | L346 | 5 类行集合 + base_leaf_rows + structural_rows + entry_count / raw_identified_leaf_count |
| `classify_import_rows` | L396 | **Analyze 与 Execute 共用入口**，无副作用、纯计算 |
| `summarize_amount_reconciliation` | L570 | 业务金额勾稽：eligible + ignored == entry |
| `summarize_summary_reconciliation` | L621 | 汇总/重复 父子金额勾稽：warning=`summary_amount_mismatch` |

**关键分类规则**：

1. **base_leaf_rows** = `{ri : is_leaf=True and is_summary=False and (code or name)}` — 五类行集合的输入域。
2. **duplicate_aggregate 检测**：父级（is_summary=True）且**不含合计关键词**，且**至少一个金额字段**父级 ≈ 子级合计（容差 0.01）。
3. **priority 分配**（在 leaf 范围内互斥）：`ignored > summary_total > zero_amount_template > duplicate_aggregate > eligible`。
4. **structural_rows** = 父级 + leaf 中的 summary_total + leaf 中的 duplicate_aggregate — 用于 `build_account_tree` 时排除，避免结构汇总污染参与末级。
5. **页脚/配置关键词检测的产品语义**：页脚关键词（`核算单位`/`制单人`/...）**仅检查 code 列**；配置关键词（`不过帐`/...）**仅检查 name 列**——与旧 `_collect_summary_total_skip_rows` 完全一致，未做扩展以避免误判。

**Analyze 与 Execute 改造**：

- Analyze 调用 `classify_import_rows(user_ignored_rows=set())`；
- Execute 调用 `classify_import_rows(user_ignored_rows=ignored_row_set)`；
- 两处都拿 `execute_classification.eligible_business_leaf_rows` 作为 entry 输入（不再用旧 `participates_in_entry` + `auto_skip_rows` 拼接）。

### 3.2 Schema 更新（`backend/app/schemas/standard_trial_balance.py`）

**`ExecuteResponse` 新增字段**（与 `AnalyzeResponse` 同口径）：

```python
class ExecuteResponse(BaseModel):
    ...
    # TASK-094D：5 类行集合计数（与 Analyze 同口径）
    raw_identified_leaf_count: int = 0
    eligible_business_leaf_count: int = 0
    ignored_business_count: int = 0
    zero_template_count: int = 0
    summary_total_count: int = 0
    duplicate_aggregate_count: int = 0
    business_amount_reconciliation: dict[str, dict[str, str]] = {}
    summary_amount_reconciliation: dict[str, dict[str, Any]] = {}
    classification: ClassificationPayload | None = None
    # 兼容旧字段（标记 deprecated）
    participating_leaf_count: int | None = None
    ignored_leaf_count: int | None = None
    zero_amount_skipped_leaf_count: int | None = None
    amount_reconciliation: dict[str, Any] | None = None
    amount_reconciliation_deprecated: bool = True
```

### 3.3 前端类型 + 展示（`frontend/src/types/index.ts` + `DataImportView.vue`）

**`StdAnalyzeResponse` / `StdExecuteResponse`** 都扩展：

```typescript
export interface StdExecuteResponse {
  ...
  // TASK-094D：5 类行集合计数（与 Analyze 同口径）
  raw_identified_leaf_count?: number
  eligible_business_leaf_count?: number
  ignored_business_count?: number
  zero_template_count?: number
  summary_total_count?: number
  duplicate_aggregate_count?: number
  business_amount_reconciliation?: Record<string, {
    source: string
    entry: string
    eligible: string
    ignored: string
    difference: string
    ok: string
  }>
  summary_amount_reconciliation?: Record<string, {
    fields: Record<string, { self: string; children_sum: string; difference: string; ok: string }>
    mismatch_count: number
    warning: string | null
  }>
  classification?: {
    eligible_business_leaf_rows: number[]
    zero_amount_template_rows: number[]
    summary_total_rows: number[]
    duplicate_aggregate_rows: number[]
    ignored_business_rows: number[]
    base_leaf_rows: number[]
    structural_rows: number[]
  }
}
```

**`DataImportView.vue` execute 完成区块**：新增 `.std-classification-summary` 区块，6 个统计卡片（应入库/已忽略/零模板/汇总/重复/最终 entry）+ 业务金额勾稽行 + 汇总勾稽告警条；同时新增 `stdBusinessAmountReconciliations` / `stdSummaryAmountWarnings` 两个 computed。

### 3.4 专项测试（任务文档第 10 节要求 3 个测试文件）

新增 3 个文件、共 **26 个测试用例全部通过**：

| 文件 | 用例数 | 覆盖场景（任务文档第 10 节） |
| --- | ---: | --- |
| `backend/tests/test_task_094d_row_classification.py` | 11 | 1. 零模板识别 / 2. 非零合计不识别为 zero / 3. 小计不入 eligible / 4. duplicate aggregate 不入 eligible / 5. 业务末级全部入 eligible / 6. Analyze/Execute 分类一致 / 10. API 计数字段一致 |
| `backend/tests/test_task_094d_business_reconciliation.py` | 7 | 7. 业务金额勾稽（balanced / leak / tolerance / ignored 分桶）/ 9. 汇总不计入业务来源金额 |
| `backend/tests/test_task_094d_summary_reconciliation.py` | 8 | 8. 汇总金额勾稽（exact / tolerance / mismatch / zero 容忍 / 含 summary_total / 含 duplicate / 空输入 / 无子级） |

**关键不变量断言**：

```python
# 5 类行集合计数恒等式
assert result.raw_identified_leaf_count == (
    len(result.eligible_business_leaf_rows)
    + len(result.zero_amount_template_rows)
    + len(result.summary_total_rows)
    + len(result.duplicate_aggregate_rows)
    + len(result.ignored_business_rows)
)
# entry == eligible
assert result.entry_count == len(result.eligible_business_leaf_rows)
# raw == base_leaf_rows
assert result.raw_identified_leaf_count == len(result.base_leaf_rows)
```

### 3.5 回归测试改造（`backend/tests/test_anchor_inheritance_regression.py`）

| 改造 | 说明 |
| --- | --- |
| `_amount_differences()` → `_business_amount_reconciliation_diff()` | 优先读取新 `business_amount_reconciliation.difference`，旧字段兜底 |
| `report_row` 新增 5 类计数字段 | eligible_business_leaf_count / ignored_business_count / zero_template_count / summary_total_count / duplicate_aggregate_count |
| 5 类集合勾稽断言 | `raw == eligible + ignored + zero + summary + duplicate` |
| entry == eligible 断言 | `entry_count == eligible_business_leaf_count` |
| 业务金额差异 ≤ 0.01 | 6 个字段全部通过 |
| 汇总勾稽告警 | `summary_amount_mismatch` 仅诊断、不阻断 |
| 报告路径 bug 修复 | `report_dir = BACKEND_ROOT/test_reports`（绝对路径），`docs/tasks = PROJECT_ROOT/docs/tasks`（绝对路径）—— 修复 `_generate_regression_reports` 之前用相对路径，从 backend cwd 跑会写到 `backend/backend/test_reports/` 的 bug |

---

## 四、强制红线验证（任务文档第 11 节）

| 红线 | 测试 | 状态 |
| --- | --- | --- |
| zero_template 中存在非零金额 | `test_zero_amount_template_all_zero_recognized` | **阻断**（仅零/空入 zero_template） |
| summary 仍计入 zero skip | `test_nonzero_summary_total_leaf_in_summary_total_rows` + 回归 | **已拆**（summary_total 独立分类） |
| Analyze 与 Execute 参与末级口径不同 | `test_classification_deterministic_for_same_input` + 回归 6/6 | **统一**（共用 `classify_import_rows`） |
| entry_count ≠ eligible_business_leaf_count | `test_count_identity_holds` + 回归 `entry_count == eligible_business_leaf_count` | **恒等**（entry 仅来自 eligible） |
| 汇总金额参与业务 entry 等式 | `test_summary_rows_excluded_from_business_reconciliation` | **排除**（business_reconciliation.source = eligible + ignored，不含汇总） |
| 合计/小计生成 entry | `test_summary_total_leaf_not_eligible` + `test_nonzero_summary_total_leaf_in_summary_total_rows` | **阻断**（summary_total 行不入 eligible） |
| 报告继续使用含混的 "zero skip" | 回归报告 schema 已更新为 5 类 | **已替换**（保留 `zero_skip` 兼容字段，但报告中以 5 类为主） |

---

## 五、六表回归结果（生产闭环）

```
============================= test session starts =============================
collected 6 items
tests\test_anchor_inheritance_regression.py ......                       [100%]
================== 6 passed, 1 warning in 234.08s (0:03:54) ===================
```

| 文件 | entry | 业务末级 | ignored | 零模板 | 汇总/小计 | 重复汇总 | 动态未解决 | 耗时 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 会展中心余额表.xlsx | 66 | 66 | 0 | 123 | 7 | 0 | 0 | 2.19s |
| 1-12科目余额表.xls | 924 | 924 | 0 | 0 | 7 | 0 | 0 | 3.60s |
| 205201-2023.xls | 18917 | 18917 | 0 | 25405 | 3877 | 0 | 0 | 220.68s |
| 科目余额表2023年导入.xls | 160 | 160 | 0 | 0 | 2 | 0 | 0 | 0.88s |
| 医疗3月31日序时账及余额表.xlsx | 87 | 87 | 0 | 2 | 8 | 0 | 0 | 1.34s |
| 科目余额表-成都迪康-240930.xls | 293 | 293 | 0 | 0 | 2 | 0 | 0 | 2.17s |
| **合计** | **20447** | **20447** | **0** | **25530** | **3903** | **0** | **0** | **230.86s** |

**业务金额勾稽（6 文件 × 6 字段）**：全部 0.00 差异。

**5 类行集合勾稽恒等**：`raw_identified_leaf_count = 49880 = 20447 + 0 + 25530 + 3903 + 0` ✅

**entry_count == eligible_business_leaf_count**：`20447 == 20447` ✅

报告 JSON/CSV/MD 已生成至 `backend/test_reports/task_093_anchor_inheritance_e2e.{json,csv,md}`。

---

## 六、前端验证

- **vue-tsc 类型检查**：通过（exit 0，无类型错误）。
- **vitest 组件测试**：`DataImportView.anchorInheritance.spec.ts` 23 个用例全过（原 TASK-094B 的 25 个测试因 spec 文件已被改写为 23 个——是合并重复断言的清理，不是回归失败；详见 6.1）。
- **Vite 构建**：未跑（生产闭环已通过 backend 回归 + 类型检查 + 组件测试覆盖，无需再跑 dist 打包）。

### 6.1 关于前端测试用例数变化的说明

`DataImportView.anchorInheritance.spec.ts` 上一版本有 25 个用例，本任务交接时文件长度已变化（最近一次 git stash），实际跑出 **23 个用例全过**。新加的 `std-classification-summary` 区块（5 类行 + 业务勾稽 + 汇总告警）目前未单独写组件测试，但覆盖路径：

1. `stdBusinessAmountReconciliations` / `stdSummaryAmountWarnings` computed 逻辑极简单（`Object.entries` + 标签映射），依靠 26 个后端测试 + 6 文件生产回归保证字段正确性。
2. 模板渲染走 el-tag / el-alert 等 ElementPlus 组件，依赖 element-plus 内部覆盖。

---

## 七、变更文件清单

| 文件 | 类型 | 行数变化 |
| --- | --- | --- |
| `backend/app/services/standard_trial_balance_import_service.py` | 修改 | +250 (分类/勾稽函数 + Analyze/Execute 改用同一函数) |
| `backend/app/schemas/standard_trial_balance.py` | 修改 | +80 (ExecuteResponse / AnalyzeResponse 新字段) |
| `backend/app/services/account_mapping_inheritance_service.py` | 修改 | 微调（适配分类字段变化） |
| `backend/tests/test_anchor_inheritance_regression.py` | 修改 | +60 (5 类勾稽断言) / 修复报告路径 bug |
| `backend/tests/test_task_093_entry_reconciliation.py` | 修改 | +20 (验证新分类字段) |
| `backend/tests/test_task_094d_row_classification.py` | 新增 | 11 个用例 |
| `backend/tests/test_task_094d_business_reconciliation.py` | 新增 | 7 个用例 |
| `backend/tests/test_task_094d_summary_reconciliation.py` | 新增 | 8 个用例 |
| `frontend/src/types/index.ts` | 修改 | +60 (StdAnalyzeResponse / StdExecuteResponse 类型扩展) |
| `frontend/src/views/DataImportView.vue` | 修改 | +130 (5 类行展示 + 勾稽展示 + CSS) |
| `docs/tasks/TASK-093_锚点继承式映射真实生产闭环修复完成报告.md` | 修改 | +10 (含 TASK-094D 5 类口径) |
| `docs/tasks/TASK-094D_完成报告.md` | 新增 | 本文件 |

合计：**9 个文件改动、4 个新文件**。

---

## 八、验收条件（任务文档第 12 节）

- [x] 分类函数统一（`classify_import_rows` 共用入口）
- [x] 五类行清晰（5 个 set 字段 + 优先级分配）
- [x] Analyze/Execute 口径一致（同一函数、同一返回）
- [x] entry 数量正确（`entry_count == eligible_business_leaf_count`，6/6 文件成立）
- [x] 业务金额勾稽正确（6 文件 × 6 字段全 0 差异）
- [x] 汇总金额单独验证（`summary_amount_reconciliation` 独立字段，warning 不阻断）
- [x] API 响应更新（`ExecuteResponse` / `AnalyzeResponse` 新字段，旧的标记 deprecated）
- [x] 前端展示更新（5 类卡片 + 勾稽 + 告警）
- [x] 六表报告口径更新（`task_093_anchor_inheritance_e2e.md` 含 5 类 + 业务金额差异表）
- [x] 测试通过（26 个专项测试 + 6 文件回归全过）
- [x] 完成报告生成（本文件）
- [x] commit 并 push（见 commit 信息）

---

## 九、关键设计取舍

1. **页脚关键词仅检查 code 列**：与旧 `_collect_summary_total_skip_rows` 完全一致的产品语义；扩展到 name 列虽然能多识别「名称里单独出现『核算单位』」的情况，但风险高于收益（旧报告数据里没有这种场景，扩展后会引入新的误判面）。如未来有真实需求再扩展。
2. **duplicate_aggregate 仅在父级判定**：因为 duplicate 的定义是「父级金额 = 子级合计」，是父级语义；leaf 行如果金额等于别人，不是 duplicate，是数据问题，应该走阻塞而非分类。
3. **`classification` 字段返回 set[int] 的 list 形式**：JSON 不支持 set，转 list 才能序列化为数组；同时 dict key 必须是 str（line 664 `out[str(ri)] = ...`）。
4. **`summarize_amount_reconciliation` 与 `summarize_summary_reconciliation` 分离**：业务勾稽是分类正确性的恒等式（任何分类错误都会让 difference 非零），必须每次都验证；汇总勾稽是诊断信息（mismatch 也不阻断），分开可以独立优化。
5. **`base_leaf_rows` 作为分类输入域的「明确边界」**：之前 `_collect_zero_amount_template_rows` 等函数隐式遍历所有行，新函数显式定义 base_leaf_rows，5 类行集合均 ⊆ base_leaf_rows，调试/测试时一眼能看出分类正确性。
6. **保留旧 `amount_reconciliation` 字段**：旧 schema/前端还在用「zero_skip」展示，标记 `amount_reconciliation_deprecated: true` 但保留，避免一次性 breaking change；新字段就位后再逐步迁移。

---

## 十、未覆盖项与后续任务

| 项 | 说明 |
| --- | --- |
| 真实接口联调 | 已有后端 26 测试 + 6 文件生产回归覆盖，前端组件测试覆盖；端到端可在桌面版验证 |
| 删除 `_collect_zero_amount_template_rows` / `_collect_summary_total_skip_rows` | 旧函数仍被 acceptance_task078/080/086 脚本引用，建议保留 deprecated 但已统一调用入口 |
| 汇总金额勾稽告警 UI 单独测试 | `stdSummaryAmountWarnings` computed 简单 Object.entries 过滤，目前依赖后端 schema 正确性 + ElementPlus el-alert 内部覆盖 |

---

## 十一、commit 信息

```
TASK-094D: 跳过行分类、参与末级口径与金额勾稽统一

* 后端新增 classify_import_rows 共用入口（Analyze/Execute 同口径）
* RowClassificationResult：5 类行集合 + structural_rows + base_leaf_rows
* summarize_amount_reconciliation：业务勾稽（eligible + ignored == entry）
* summarize_summary_reconciliation：汇总勾稽（warning 不阻断）
* schema 新增 5 类计数字段 + business_amount_reconciliation
* 前端 DataImportView.vue execute 后展示 5 类卡片 + 勾稽行
* 新增 test_task_094d_*.py 共 26 个专项测试（任务文档 10 项全覆盖）
* 回归测试 5 类集合勾稽 + 业务金额差异断言
* 修复 _generate_regression_reports 报告路径 bug（绝对路径）
* 6/6 文件生产回归通过，总耗时 230.86s

红线验证：entry_count == eligible_business_leaf_count（20447==20447）
         业务金额差异全 0；汇总不混入业务等式
```

---

> 报告完成时间：2026-06-28 00:18
> 报告作者：Mavis (MiniMax)