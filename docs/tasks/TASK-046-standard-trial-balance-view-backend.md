# TASK-046：标准科目余额表数据查看后端 API

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 11:15
完成时间：2026-06-22 11:30
完成时间：-

## 目标
提供导入完成后的数据查看后端能力。第一版只实现科目余额表，序时账和辅助明细账后续再做。

## 依赖
必须等待 `TASK-039` 完成。可与 `TASK-040`、`TASK-042`、`TASK-043` 并行；如需要真实导入批次联调，等待 `TASK-044` 完成。

## 允许范围
- `backend/app/api/`
- `backend/app/services/`
- `backend/app/schemas/`
- `backend/app/models/`
- `backend/app/main.py`
- `backend/tests/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

## 交付
1. 新增数据查看 API：
   - `GET /api/v1/standard-trial-balances/batches`
   - `GET /api/v1/standard-trial-balances/tree`
   - `GET /api/v1/standard-trial-balances/entries`
2. 批次列表支持筛选：
   - 客户标识。
   - 年度。
   - 期间。
   - 导入时间。
3. 树形查看：
   - 按标准科目层级展示。
   - 父级节点动态汇总子级金额。
   - 支持展开父级查看下一级。
   - 支持只看有余额/发生额的科目。
4. 明细查看：
   - 展示标准科目快照。
   - 展示客户原始科目代码和名称。
   - 展示六个标准金额字段。
   - 可按标准科目、客户科目、年度、期间筛选。
5. 汇总口径：
   - `standard_trial_balance_entries` 存末级真实金额行。
   - 父级金额由查询动态汇总，不直接读取父级导入金额。
6. 后端测试覆盖：
   - 父级动态汇总。
   - 标准科目快照返回。
   - 按批次/年度/期间筛选。
   - 只看有金额科目。

## 验收
- `D:\python\python.exe -m pytest backend/tests`
- `git diff --check -- backend docs`

## 完成回报要求
- 说明数据查看 API。
- 说明父级汇总口径。
- 贴出测试命令结果。

---

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 11:30

### 修改文件

- `backend/app/schemas/standard_trial_balance.py` — 新增6个 Schema（BatchFilterParams, BatchListItem, BatchListResponse, TreeNodeResponse, TreeResponse, EntryFilterParams）
- `backend/app/services/standard_trial_balance_service.py` — 新建：批次列表、树形视图（父级动态汇总）、明细查询三个服务函数
- `backend/app/api/standard_trial_balances.py` — 新建：三个数据查看 API 端点
- `backend/app/main.py` — 注册新路由
- `backend/tests/test_standard_trial_balance_view.py` — 新建：21 个测试
- `docs/tasks/TASK-046-standard-trial-balance-view-backend.md` — 更新状态

### 完成内容

#### 数据查看 API（3 个端点）

1. **`GET /api/v1/standard-trial-balances/batches`** — 批次列表
   - 支持按客户标识（`customer_label` 模糊匹配）、年度（`fiscal_year`）、期间（`period`）、导入时间范围（`import_start`/`import_end`）筛选
   - 每个批次返回 `entry_count`（标准化条目数）

2. **`GET /api/v1/standard-trial-balances/tree`** — 树形视图
   - 按标准科目层级展示（`parent_id` 自引用构建父子树）
   - 父级节点金额由子级末级科目 **动态汇总**，不直接读取父级导入金额
   - 递归构建：叶子节点金额来自 `standard_trial_balance_entries` 直接条目，父级递归累加所有子孙
   - 支持 `only_with_amounts=true` 只看有余额/发生额的科目（过滤掉所有六列均为0的节点及其空子树）
   - 返回递归 `TreeNodeResponse`（含 `children: list[TreeNodeResponse]`）

3. **`GET /api/v1/standard-trial-balances/entries`** — 明细列表
   - 展示标准科目快照（code/name/category/direction，导入时冻结）
   - 展示客户原始科目代码和名称
   - 展示六个标准金额字段（opening/current/ending debit/credit）
   - 支持按标准科目代码、客户科目代码（均模糊匹配）、年度、期间、批次筛选

#### 父级汇总口径

- `standard_trial_balance_entries` 只存末级真实金额行（设计约束，由 TASK-042/044 保证）
- 树形视图查询时：
  - 叶子节点：直接从 `entries` 按 `standard_account_id` 汇总
  - 父级节点：递归累加所有子孙节点已汇总的金额
  - 不依赖 `raw_rows` 中的父级导入金额
- 支持 6 列独立累加（opening_debit/credit, current_debit/credit, ending_debit/credit）

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

结果：

- **通过：323 passed，3 warnings（预存，非本次引入）**
- 新增 21 个测试覆盖：
  - 批次列表：全量、按客户/年度/期间/导入时间筛选、条目计数
  - 树形视图：空树、单层、父级汇总子级、三级汇总、只看有金额、父级隐藏空子级、按批次/年度/期间筛选、六列汇总
  - 明细列表：快照返回、按标准科目/客户科目/年度+期间筛选、多条件组合、快照不受科目变更影响

```powershell
git diff --check -- backend docs
```

结果：

- 通过（仅 LF/CRLF 换行符警告，Windows 正常现象）

### 风险和后续

- 无。依赖 TASK-046 API 的 TASK-047（数据查看前端）可继续推进。
