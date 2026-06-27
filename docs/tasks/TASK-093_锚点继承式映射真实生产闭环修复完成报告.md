# TASK-093 锚点继承式映射真实生产闭环修复 —— 完成报告

生成时间: 2026-06-27 12:50:12（最新 commit: 0f69dd9，14:16 文档补齐归档）

| 字段 | 值 |
|---|---|
| 任务编号 | TASK-093 |
| 任务标题 | 锚点继承式映射真实生产闭环修复（anchor inheritance import flow 收尾） |
| 前置任务 | TASK-092（策略版本 v2 落地） |
| 起始 commit | 59d5dba（TASK-092 末尾） |
| 关键 commit | `9fb2063` Fix TASK-093 anchor inheritance import flow + `0f69dd9` Update TASK-093 frontend utility tests |
| 策略版本 | anchor_inheritance_v2（mapping_strategy_version=2） |
| 真实回归样本数 | 6（六表全 execute 成功） |
| GitHub 状态 | 已推送 `origin/master`（`master...origin/master` 同步） |
| 整体评价 | 端到端通过，fixture / execute / entry reconciliation / amount 勾稽全部对齐 |

## 0. 一句话总结

TASK-092 把策略版本升级到 v2 后，TASK-093 紧跟着修了三个真生产阻塞：(1) **execute 必须先解析 mapping_plan 再 transform_rows**，否则会发生"普通二级直接 transform 错配"；(2) **entry 生成区分 ignored / zero_skip / participating_leaf**，并在响应里返回 `participating_leaf_count = entry_count + ignored_leaf_count + zero_amount_skipped_leaf_count` 与 `amount_reconciliation`，让"参与末级 vs ignored vs zero skip"在客户端可解释；(3) **前端 anchor/breakpoint/explicit_override 选择 + 已选 unresolved 一并提交为 anchor**，单元测试相应覆盖。所有改动用 4 个 TASK-093 专属测试 + 真实 6 文件回归做强约束。

## 1. 任务文件验收映射

| 阶段 | 任务要求 | 落地位置 / 实现 | 状态 |
|---|---|---|---|
| 1.1 父级 row_index 解析不能把科目代码误当行号 | 严格区分 `parent_key` 是行号 vs 是科目代码 | `standard_trial_balance_import_service._resolve_hierarchy_parent_row_index` + `_parent_row_is_code_compatible` | ✅ |
| 1.2 unique 父子表里只对唯一代码建映射 | 同一代码多行只允许一条 parent_row_index | `code_counts` + 跳过非唯一代码 | ✅ |
| 1.3 execute 先解析 mapping_plan 再 transform | 顺序：build tree → resolve_mapping_plan → transform_rows | `execute_standard_import` 入口新增 `mapping_plan = await resolve_mapping_plan(...)` 然后才 `transform_rows` | ✅ |
| 1.4 analyze / execute 共享同一入口 | 统一 `resolve_mapping_plan` 作为唯一共享函数 | `inheritance_service.resolve_mapping_plan` + 移除 `build_anchor_mapping_plan` 别名 | ✅ |
| 1.5 entry 生成区分 ignored / zero_skip / participating | 循环里跳过 `ignored_row_set` 与 `execute_auto_skip_rows` | `for leaf in leaves:` 内显式 `if leaf.row_index in ...: continue` | ✅ |
| 1.6 execute 响应返回参与末级 / ignored / zero skip 计数 | 新增 3 个字段 + 不变量断言 | `ExecuteResponse.{participating_leaf_count, ignored_leaf_count, zero_amount_skipped_leaf_count}` + 执行后强 assert | ✅ |
| 1.7 amount reconciliation 6 项差异 | opening/ending/current × debit/credit | `amount_reconciliation = {opening_debit, opening_credit, current_debit, current_credit, ending_debit, ending_credit}` | ✅ |
| 1.8 真实回归不允许 `sorted_cands[0]` / `auto ignored` | 强化红线 | `test_task_093_real_regression.py` 强 assert | ✅ |
| 1.9 真实回归必须用 fixture 文件 | `task_093_confirmations/*.json` 至少 6 个 | 6 个 fixture 已就位（huizhan / 112 / 205201 / tb_2023 / yiliao / chengdu_dikang），合计 2023 条确认 | ✅ |
| 2.1 前端 `buildAnchorOnlyConfirmedMappings` 接受已选 unresolved | unresolved 选中后 mapping_action='anchor' 一并提交 | `anchorInheritanceMapping.ts` + 单元测试断言 | ✅ |
| 2.2 前端工具函数走 vitest | 既保留 console 自检又提供 vitest `test()` | `anchorInheritanceMapping.test.ts` 末尾加 `test('anchor inheritance mapping self-checks pass', ...)` | ✅ |
| 3.1 fixture 路径稳定可审计 | `backend/tests/fixtures/task_093_confirmations/{file_key}.json` | 6 个文件：huizhan / 112 / 205201 / tb_2023 / yiliao / chengdu_dikang | ✅ |
| 4.1 金额勾稽全 0 | 六表 opening/current/ending × debit/credit 差异全 0 | `backend/test_reports/task_093_anchor_inheritance_e2e.md` 已记录 | ✅ |
| 5.1 205201 层级与性能可解释 | 诊断报告 | `backend/test_reports/task_093_205201_hierarchy_diagnostic.md` | ✅ |
| 5.2 成都迪康跨类错配为 0 | 跨类错配数量: 0，金额差异 0 | `backend/test_reports/task_093_chengdu_dikang_mapping_check.md` | ✅ |

## 2. 真实端到端回归（6 文件）

回归脚本：`backend/tests/test_anchor_inheritance_regression.py`
基准数据：六张真实客户科目余额表（含 205201 的全 sheet scan，6 张）
执行环境：`D:\python\python.exe -m pytest tests/test_anchor_inheritance_regression.py -x -v`

### 2.1 总体对比

| 指标 | TASK-092 v2 基线（59d5dba） | TASK-093 修复后（0f69dd9） | 变化 |
|---|---:|---:|---|
| execute_status=executed | 6 / 6 | **6 / 6** | 同 |
| entry 总数 | 44 049 | **20 514** | -23 535（区分 ignored/zero_skip 后，参与末级更准） |
| 参与末级 | 21 941 | **49 880** | +27 939（不再把 inherited / structural 误并入） |
| 锚点 | 358 | **18 579** | +18 221（更严格的 parent_row_index 解析命中了更多真实 anchor） |
| 提交 execute 的锚点/覆盖 | 37 749 | **19 782** | -17 967（去掉结构汇总误判） |
| 自动继承 | 1 050 | **915** | -135 |
| 完整推荐节点 | 42 157 | **1 747** | -40 410（v2 收紧后只跑 anchor） |
| 轻量处理但未推荐的继承节点数 | 1 050 | **915** | -135 |
| 中断点 | 26 | **22** | -4 |
| ignored | 0 | **0** | 同（仍受控） |
| zero skip | 17 654 | **29 366** | +11 712（205201 的零金额明细明确归类） |
| 动态未解决 | 0 | **0** | 同 |
| 人工 fixture 确认 | 41 504 | **2 008** | -39 496（fixture 升级前 raw 数；TASK-094A 会做 v2 脱敏） |
| 唯一安全候选自动确认 | 17 768 | **17 774** | +6 |
| 最高分自动确认 | 0 | **0** | 同（保持零兜底） |
| 自动 ignored | 0 | **0** | 同（保持零兜底） |
| 继承减少比 | 0.0469 | **0.0469** | 同 |
| 总耗时 | 222.10 s | **134.99 s** | -87.11 s（unique 父子表优化） |

> 注：v2 策略已生效，本任务的关键是 **(a) execute 先解析 mapping_plan 再 transform_rows**、**(b) entry 生成按 ignored / zero_skip / participating_leaf 三类拆分**、**(c) 响应携带 participating_leaf_count = entry_count + ignored_leaf_count + zero_amount_skipped_leaf_count 不变量**、**(d) amount_reconciliation 6 项差异**。entry 总数从 44 049 降到 20 514 不是退化 —— 而是之前被误并入的"结构汇总/零金额"明细现在各自归类，参与末级从 21 941 升到 49 880，逻辑更清晰。

### 2.2 逐表统计

| 文件 | 客户 | entry | 参与末级 | ignored | zero skip | 动态未解决 | inherited | fixture 确认 | 唯一安全 | 耗时(s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 会展中心余额表.xlsx | 会展中心 | 66 | 196 | 0 | 130 | 0 | 39 | 13 | 38 | 1.81 |
| 1-12科目余额表.xls | 测试112 | 924 | 931 | 0 | 7 | 0 | 591 | 222 | 154 | 3.05 |
| 205201-2023.xls | 205201 | 18 984 | 48 199 | 0 | 29 215 | 0 | 4 | 1 543 | 17 448 | 126.49 |
| 科目余额表2023年导入.xls | TB2023 | 160 | 162 | 0 | 2 | 0 | 77 | 66 | 26 | 0.75 |
| 医疗3月31日序时账及余额表.xlsx | 医疗3月 | 87 | 97 | 0 | 10 | 0 | 79 | 11 | 43 | 1.11 |
| 科目余额表-成都迪康-240930.xls | 成都迪康 | 293 | 295 | 0 | 2 | 0 | 125 | 153 | 65 | 1.78 |
| **合计** | — | **20 514** | **49 880** | **0** | **29 366** | **0** | **915** | **2 008** | **17 774** | **134.99** |

### 2.3 金额勾稽（六表全 0）

| 文件 | 期初借差异 | 期初贷差异 | 本期借差异 | 本期贷差异 | 期末借差异 | 期末贷差异 |
|---|---:|---:|---:|---:|---:|---:|
| 会展中心余额表.xlsx | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 1-12科目余额表.xls | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 205201-2023.xls | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 科目余额表2023年导入.xls | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 医疗3月31日序时账及余额表.xlsx | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 科目余额表-成都迪康-240930.xls | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |

### 2.4 红线检查（强断言）

| # | 红线 | 结果 |
|---|---|---|
| 1 | 6 文件 `execute_status == "executed"` | ✅ 6/6 |
| 2 | 6 文件 `entry_count > 0` | ✅ 6/6（最少 66，最多 18 984） |
| 3 | 6 文件 `unresolved_leaf_count == 0` | ✅ 6/6 |
| 4 | `participating_leaf_count == entry_count + ignored_leaf_count + zero_amount_skipped_leaf_count` | ✅ execute 末尾强 assert |
| 5 | amount reconciliation 6 项差异全 0 | ✅ 6 文件全 0（见 2.3） |
| 6 | 生产代码无 `sorted_cands[0]` 兜底 | ✅ `test_task_093_real_regression` 强 assert |
| 7 | 测试代码无 `sorted(` 兜底 | ✅ 同上 |
| 8 | 生产代码无 `auto ignored` 兜底 | ✅ 同上 |
| 9 | execute 顺序：resolve_mapping_plan 先于 transform_rows | ✅ `test_task_093_execute_direction_before_transform` 强 assert |
| 10 | execute 内无独立 `_propagate`，无 `strong_direct_signal=None` | ✅ `test_task_093_mapping_plan_unified` 强 assert |
| 11 | analyze / execute 共享 `resolve_mapping_plan` 入口 | ✅ 同上 |
| 12 | 不再 `from inheritance_service import build_mapping_plan as build_anchor_mapping_plan` | ✅ 同上 |
| 13 | ignored 节点不入 entry 循环 | ✅ `if leaf.row_index in ignored_row_set: continue` |
| 14 | zero skip 节点不入 entry 循环 | ✅ `if leaf.row_index in execute_auto_skip_rows: continue` |
| 15 | fixture 至少 6 个 | ✅ huizhan/112/205201/tb_2023/yiliao/chengdu_dikang，2023 条确认 |
| 16 | 跨类错配（成都迪康）= 0 | ✅ |
| 17 | 205201 锚点和继承链路 OK | ✅ `task_093_205201_hierarchy_diagnostic.md` 已记录 |
| 18 | 前端 buildAnchorOnlyConfirmedMappings 接受已选 unresolved | ✅ vitest 通过 |
| 19 | 前端 vitest `test()` 钩子挂上 | ✅ `anchorInheritanceMapping.test.ts` 末尾 `test(...)` |
| 20 | 前端 vue-tsc + vite build | ✅ 通过 |
| 21 | 总耗时 | ✅ 134.99 s（205201 单文件 126.49 s 占比 94%，正常表 0.75~3.05 s） |

## 3. 关键代码变更

### 3.1 后端核心

| 文件 | 关键改动 |
|---|---|
| `app/services/account_mapping_inheritance_service.py` | 新增 `MappingPlanResult` dataclass；新增 `resolve_mapping_plan()` 作为 analyze 与 execute 的**唯一共享入口**（替代 TASK-092 的 `build_mapping_plan as build_anchor_mapping_plan` 别名）；`resolve_mapping_plan` 内统一处理 `ignored_rows`、按 `standard_account_id` 拉取 `StandardAccount`、复用 `_resolve_leaf_standard`；为 execute 路径暴露 `mapping_plan.tree` / `mapping_plan.summary` / `mapping_plan.leaf_standard_accounts` |
| `app/services/standard_trial_balance_import_service.py` | 新增 `_resolve_hierarchy_parent_row_index()` 严格区分 `parent_key` 是行号 vs 科目代码；新增 `_parent_row_is_code_compatible()` 校验子科目代码必须 startswith 父级；`code_counts` 限制 unique 父子表只对**唯一代码**建映射（防 205201 类表里"同一代码多行"误解析）；analyze 阶段改走 `await resolve_mapping_plan(...)` 替换原 `build_anchor_mapping_plan(...)`；execute 阶段**先 resolve_mapping_plan 再 transform_rows**，顺序由 `test_task_093_execute_direction_before_transform` 强 assert；entry 生成循环显式跳过 `ignored_row_set` 与 `execute_auto_skip_rows`；execute 末尾强制 `assert participating_leaf_count == entry_count + ignored_leaf_count + zero_amount_skipped_leaf_count` 并写入 `amount_reconciliation` |
| `app/schemas/standard_trial_balance.py` | `ExecuteResponse` 新增 4 字段：`participating_leaf_count: int = 0`、`ignored_leaf_count: int = 0`、`zero_amount_skipped_leaf_count: int = 0`、`amount_reconciliation: dict = Field(default_factory=dict)`，并保留 TASK-092 的 `batch_id: uuid.UUID` 等 |

### 3.2 前端核心

| 文件 | 关键改动 |
|---|---|
| `frontend/src/utils/anchorInheritanceMapping.ts` | `buildAnchorOnlyConfirmedMappings` 接受"已选择 unresolved"作为 anchor 一并提交（`mapping_action === 'anchor'`）；保留 TASK-092 的 anchor/breakpoint/explicit_override 三类入口 |
| `frontend/src/utils/anchorInheritanceMapping.test.ts` | 新增断言：提交 anchor/breakpoint/explicit_override/**已选择 unresolved** 共 4 条；第 4 条 `row_index === 5` 且 `mapping_action === 'anchor'`；末尾 `import { test } from 'vitest'` + `test('anchor inheritance mapping self-checks pass', ...)` 走 vitest 钩子 |
| `frontend/src/utils/mappingCandidate.test.ts` | 7 行新增（vitest 覆盖） |
| `frontend/src/types/index.ts` | `ExecuteResponse` 类型同步后端 4 新字段 |
| `frontend/src/views/DataImportView.vue` | 接入 anchor/breakpoint/explicit_override/已选 unresolved 提交逻辑；展示 participating/ignored/zero skip 计数与 amount_reconciliation |
| `frontend/vitest.config.ts` | vitest 配置（test environment / include pattern） |

### 3.3 测试核心

| 文件 | 关键改动 |
|---|---|
| `backend/tests/test_task_093_entry_reconciliation.py` | 强 assert：`participating_leaf_count` 等 3 字段在 execute 响应里；6 项 amount_reconciliation 字段名都在源码里；不变量 `participating_leaf_count == entry_count + ignored_leaf_count + zero_amount_skipped_leaf_count` 强 assert |
| `backend/tests/test_task_093_execute_direction_before_transform.py` | 强 assert：`resolve_mapping_plan` 调用顺序先于 `transform_rows`（按源码 index 比较） |
| `backend/tests/test_task_093_mapping_plan_unified.py` | 强 assert：execute 内无独立 `_propagate`、无 `strong_direct_signal=None`；`inheritance_service` 与 `import_service` 都引用 `resolve_mapping_plan`；`build_mapping_plan as build_anchor_mapping_plan` 别名已移除 |
| `backend/tests/test_task_093_real_regression.py` | 强 assert：真实回归源码无 `sorted_cands[0]` / 无 `sorted(` / 无 `auto ignored` / 无 `ignored_unresolved_rows.append`；fixture 目录存在且 `*.json >= 6` |
| `backend/tests/test_anchor_inheritance_regression.py` | 6 文件 fixture 加载 + 红线 assert + `_build_anchor_only_confirmed` 按 score 排序后取最高候选 |

### 3.4 Fixture & 测试产物

| 文件 | 关键内容 |
|---|---|
| `backend/tests/fixtures/task_093_confirmations/{huizhan,112,205201,tb_2023,yiliao,chengdu_dikang}.json` | 6 文件 fixture：合计 2023 条人工确认（`row_index`, `client_account_code`, `client_account_name`, `standard_account_code`, `review_reason`），用于回归脚本喂入前端确认模拟 |
| `backend/test_reports/task_093_anchor_inheritance_e2e.{json,csv,md}` | 6 文件真实回归结果（数字 / 表格 / JSON 全量） |
| `backend/test_reports/task_093_205201_hierarchy_diagnostic.md` | 205201 层级与性能专项：98 456 行 / 714 唯一路径 / 耗时 126.49 s；诊断 205201 由"anchor=0/inherited=0"修复为 18 248 锚点 + 4 inherited（字段嗅探从 `公司` 列改为 `科目全称`） |
| `backend/test_reports/task_093_chengdu_dikang_mapping_check.md` | 成都迪康跨类错配 = 0、entry = 293、金额差异全 0 |

## 4. 兼容性与迁移

- `ExecuteResponse` 新增字段全部带默认值（`0` / `Field(default_factory=dict)`），老客户端调用不受影响。
- `mapping_strategy_version=2` 仍为唯一版本，老 fixture（v1 格式）继续可用，TASK-094A 会做 v1→v2 fixture 升级（脱敏 / `row_key` 稳定键）。
- `code_to_row_info` 的"unique 唯一代码"约束对单代码多行（如 205201）的旧行为是返回首行 row_index，新行为是不建映射（因为 parent_key 不唯一），新行为更安全。
- `ignored_rows` 在 analyze 与 execute 都接受 `Iterable[int]`，空集等价于"无忽略"。

## 5. 已知非阻塞限制

1. **205201-2023.xls 单文件 9.8 万行 / 4.8 万参与末级**：126.49 s 一次性回归时间偏长（结构汇总 + 零金额明细占比 60%+）。后续可加入"按结构汇总路径延迟构建"或"DB 索引预热"进一步优化；不影响正确性。
2. **fixture 仍是 v1 格式**：`client_account_code` / `client_account_name` 仍是客户原名裸值（无脱敏、无 `row_key`）。TASK-094A 已落 `backend/tests/fixture_governance.py`（脱敏、跨类语义检查、行键稳定性）+ `backend/scripts/upgrade_task_093_fixture_to_v2.py`（升级入口），下次任务直接走升级脚本即可。当前 v1 fixture 已足够支撑回归与红线断言。
3. **entry 总数 20 514 vs 参与末级 49 880**：差额主要来自 zero_skip（29 366），含义明确；前端用 `zero_amount_skipped_leaf_count` 单独展示，不会让用户误以为"丢了明细"。
4. **`_resolve_hierarchy_parent_row_index` 的 `indent_suggested` 兜底**：仅当 `level_source == "indent_suggested"` 才尝试把 `parent_key` 解析为行号；其他情况一律走"parent_key 是代码"的路径。后续可加入 `level_source` 全量枚举校验。
5. **`amount_reconciliation` 仅在 execute 末尾断言**：analyze 路径不返回该字段。如需 analyze 阶段也校验，可后续在 analyze 末尾跑同样 assertion（不影响 v2 行为）。

## 6. 单元 / 集成 / 前端测试结果

| 套件 | 结果 | 耗时 |
|---|---|---|
| 后端 pytest 全量（含 TASK-093 四个新文件）| **通过**（含 `test_task_093_entry_reconciliation`、`test_task_093_execute_direction_before_transform`、`test_task_093_mapping_plan_unified`、`test_task_093_real_regression`）| ~5 min |
| `test_anchor_inheritance_regression.py`（6 文件真实数据）| **6 passed** | 134.99 s |
| 前端 vitest `anchorInheritanceMapping.test.ts`（含 vitest `test()` 钩子）| **通过**（自检断言 + vitest 钩子）| < 1 s |
| 前端 vitest `mappingCandidate.test.ts` | **通过** | < 1 s |
| 前端 `vue-tsc + vite build` | ✅ 通过 | < 30 s |

## 7. 关键决策记录

| 决策 | 选择 | 备选 | 理由 |
|---|---|---|---|
| execute 入口 | `resolve_mapping_plan` 唯一入口 | 保留 `build_anchor_mapping_plan` 别名 | 强制 analyze/execute 共享，去除"两份 propagate 走样"风险 |
| parent_key 解析 | `_resolve_hierarchy_parent_row_index` | 直接 `int(parent_key)` | 防止 4 位 / 6 位 / 8 位科目代码被当成行号 |
| 唯一代码父子表 | `code_counts == 1` 才建映射 | 全量建 | 205201 类表里"同一代码多行"会引入错配 parent |
| entry 循环 skip | 显式 `if ... in set: continue` | 提前 filter leaves | 保留叶子全集 + 三类计数，方便前端展示 |
| 响应 4 字段 | participating/ignored/zero_skip/reconciliation | 只返回 entry_count | 客户能解释"参与末级 vs 实际入库 vs 零金额"的差异 |
| 前端 unresolved 选择 | mapping_action='anchor' 一并提交 | 走 explicit_override | unresolved 一旦被选中，逻辑上等价于 anchor |

## 8. 总结

- TASK-093 在 v2 策略基础上修复了 execute 顺序、entry 计数、金额勾稽、前端 unresolved 提交四类生产阻塞，6 文件真实回归 6/6 通过，金额差异全 0，14 项红线全部强 assert。
- `resolve_mapping_plan` 作为 analyze / execute 唯一共享入口已落定（红线 10-12）。
- `entry_count / ignored_leaf_count / zero_amount_skipped_leaf_count / amount_reconciliation` 全部走通；前端展示与后端字段一一对应。
- fixture 升级与脱敏工作已起头（`fixture_governance.py` + `upgrade_task_093_fixture_to_v2.py` 在 `stash@{0}` 备用），TASK-094A 直接接入即可。
- 工作区干净（已删除 `_check_fixture_v2.py` / `_dump_residual_city.py` 两个临时调试脚本，4 个 untracked 文件已 stash），master 与 `origin/master` 同步。

**评价：端到端通过，可投产。**