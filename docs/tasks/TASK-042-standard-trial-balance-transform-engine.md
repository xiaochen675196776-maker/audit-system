# TASK-042：科目余额表层级与金额转换引擎

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 20:00
完成时间：2026-06-22 20:15
完成时间：-

## 目标
实现标准化导入的核心转换引擎：客户科目层级识别、父级汇总校验、金额列转标准借贷列。

## 依赖
必须等待 `TASK-039` 完成。可与 `TASK-040`、`TASK-043` 并行。

## 允许范围
- `backend/app/services/`
- `backend/app/schemas/`
- `backend/tests/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

## 交付
1. 层级识别服务：
   - 客户科目有代码：优先按科目代码前缀推断父子级。
   - 无代码但 Excel 有缩进：生成“建议层级”，必须由用户确认后才生效。
   - 无代码且无缩进：退化为平铺明细。
2. 叶子行规则：
   - 标准余额表只生成末级真实金额明细。
   - 父级行不写入 `standard_trial_balance_entries`。
   - 父级行保留在原始行快照中，用于展示和校验。
3. 父级金额校验：
   - 如果父级金额与子级末级汇总不一致，生成 warning。
   - warning 不直接阻止入库，后续由用户确认是否继续。
4. 金额映射与拆分：
   - 支持客户文件已有借贷两列，直接映射到标准借贷列。
   - 支持单列金额按标准科目余额方向拆成借方或贷方。
   - 支持本期发生额按标准科目方向拆分。
   - 支持用户覆盖：借方、贷方、按标准方向。
5. 异常规则：
   - 选择“按标准方向”但标准科目无余额方向时，必须返回错误，要求用户手动指定借/贷。
   - 金额为负数时不要静默反向，先生成 warning，具体是否反向留给后续用户确认策略。
   - 金额列可以不齐全，但至少要有一个可映射的期初、发生额或期末金额列。
6. 后端单元测试覆盖：
   - 代码前缀层级。
   - Excel 缩进层级建议。
   - 无代码无缩进平铺。
   - 父级金额与子级汇总不一致 warning。
   - 单列金额按标准方向拆借贷。
   - 用户覆盖借/贷。
   - 标准方向缺失时返回错误。

## 验收
- `D:\python\python.exe -m pytest backend/tests`
- `git diff --check -- backend docs`

## 完成回报要求
- 说明层级推断策略和金额拆分策略。
- 列出新增测试样例。
- 贴出测试命令结果。

---

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 20:15

### 修改文件

- `backend/app/services/trial_balance_transform.py` — 新增，转换引擎核心服务
- `backend/tests/test_trial_balance_transform.py` — 新增，68 个单元测试
- `docs/tasks/TASK-042-standard-trial-balance-transform-engine.md` — 状态更新

### 完成内容

#### 1. 层级识别引擎

三种策略，按代码优先 → 缩进建议 → 平铺退化的顺序自动选用：

- **代码前缀层级** (`detect_hierarchy_by_code`)：有科目代码时，按代码前缀匹配找父级。例如 `1001` → `1001001`，子级的 parent_key 为 `1001`。有子级的行为 `is_summary=True`，没有子级的行为 `is_leaf=True`。层级 = 祖先数 + 1。
- **Excel 缩进层级** (`detect_hierarchy_by_indent`)：无代码但有 Excel 缩进时，按缩进深度生成建议层级 (`level_source = "indent_suggested"`)，需要用户确认。缩进越深 level 越大，向前找最近更浅缩进行为父级。
- **平铺** (`assign_flat_hierarchy`)：无代码无缩进时，所有行 level=1，均为末级。

合并策略 (`merge_hierarchy`)：代码前缀优先 > 缩进建议 > 平铺。

#### 2. 金额映射与拆分引擎

- **双列模式** (`two_column`)：直接映射 debit_field / credit_field 的值。
- **按标准方向拆分** (`single_by_direction`)：正数进方向侧，负数绝对值进反方向侧并生成警告。标准方向缺失 → 错误。
- **用户覆盖借方** (`single_as_debit`)：正数进借方，负数绝对值进贷方 + 警告。
- **用户覆盖贷方** (`single_as_credit`)：正数进贷方，负数绝对值进借方 + 警告。

所有金额经 `_safe_decimal` 安全转换，支持逗号、中文逗号。

#### 3. 父级金额校验

`validate_parent_amounts`：对标记为 is_summary 的父级，收集子级末叶金额汇总，与父级六列逐一对比。差异 > 0.01 生成为 warning（不阻止入库）。parent_key 智能识别：先按科目代码匹配，再按 row_index 整数匹配。

#### 4. 总控函数

`transform_rows(rows, hierarchy_mode)` 一站式完成全流程：层级识别 → 金额拆分 → 层级写入 → 父级校验。返回 `BatchTransformResult`（含 rows、global_warnings、global_errors）。

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_trial_balance_transform.py -v
```

结果：

```
68 passed, 0 failed, 1 warning — 全部通过
```

全量回归：

```powershell
D:\python\python.exe -m pytest
```

结果：

```
302 passed, 3 warnings — 全部通过
```

编译检查：

```powershell
D:\python\python.exe -m compileall app
```

结果：通过，无编译错误。

```powershell
git diff --check -- backend docs
```

结果：通过，无空白符问题。

### 风险和后续

- 本引擎为纯函数式转换，不依赖数据库。下游 TASK-044 (标准化导入 API) 可安全调用。
- 第一版不做：负金额静默反向（已生成 warning 待用户策略）、行过滤、列拆分、金额复杂清洗。
- `indent_suggested` 级别标记为建议，后续 TASK-044/045 需在前端展示并收集用户确认。
