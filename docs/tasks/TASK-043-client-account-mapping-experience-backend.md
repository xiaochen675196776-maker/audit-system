# TASK-043：客户科目到标准科目的映射经验后端

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 22:00
完成时间：2026-06-22 22:15
完成时间：-

## 目标
实现客户科目映射到标准科目的经验库能力，为标准化导入提供“客户优先 + 全局候选”的科目匹配建议。

## 依赖
必须等待 `TASK-039` 完成。可与 `TASK-040`、`TASK-042` 并行。

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
1. 新增映射推荐服务：
   - 第一优先级：同一客户、同一客户科目代码/名称的历史确认映射。
   - 第二优先级：全局映射经验。
   - 第三优先级：标准科目代码或名称相似度候选。
2. 候选返回字段：
   - `standard_account_id`
   - `standard_account_code`
   - `standard_account_name`
   - `score`
   - `source`
   - `reason`
   - `warning`
3. 停用标准科目规则：
   - 如果历史映射指向停用标准科目，不自动套用。
   - 必须作为 warning candidate 返回，提示用户重新选择启用标准科目。
4. 新增确认保存能力：
   - 用户确认客户科目到标准科目后，写入或更新映射经验。
   - 保存标准科目代码和名称快照。
   - 更新 `usage_count` 和 `last_used_at`。
5. 冲突处理：
   - 同一客户科目已有不同标准科目映射时，不静默覆盖。
   - 返回冲突信息，要求上层显式确认覆盖。
6. 后端测试覆盖：
   - 客户历史映射优先。
   - 全局候选兜底。
   - 停用标准科目只作为警告候选。
   - 确认保存后下次推荐命中。
   - 冲突映射需要确认覆盖。

## 验收
- `D:\python\python.exe -m pytest backend/tests`
- `git diff --check -- backend docs`

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 22:15

### 修改文件

- `backend/app/services/client_account_mapping_service.py` — 新增
- `backend/app/api/client_account_mappings.py` — 新增
- `backend/app/schemas/standard_trial_balance.py` — 新增 7 个 Pydantic Schema
- `backend/app/main.py` — 注册 `/client-account-mappings` 路由
- `backend/tests/test_client_account_mapping_service.py` — 新增 16 个测试

### 完成内容

1. **映射推荐服务** `recommend_mappings()`：
   - 优先级 1：同一客户历史确认映射（`company_history`，score=1.0）
   - 优先级 2：全局映射经验（`global_history`，score=0.9）
   - 优先级 3a：标准科目代码精确匹配（`code_match`，score=0.95）
   - 优先级 3b：标准科目名称相似度候选（`name_similarity`，score 0.7-0.92）
   - 无 `customer_label` 时不查私有经验，仅查全局经验（隔离规则）

2. **候选返回字段**：
   - `standard_account_id`、`standard_account_code`、`standard_account_name`
   - `score`、`source`（company_history / global_history / code_match / name_similarity）
   - `reason`（中文说明匹配原因）
   - `warning`（停用标准科目或名称相似度不足时填充）

3. **停用标准科目处理**：
   - 历史映射指向 `is_active=False` 的标准科目时，仍返回候选
   - 但附带 `warning` 字段提示「该标准科目已停用，请重新选择」
   - 标准科目代码匹配只查 `is_active=True` 的科目

4. **确认保存能力** `save_mapping()`：
   - 写入或更新 `client_account_mappings` 记录
   - 保存 `standard_account_code_snapshot` 和 `standard_account_name_snapshot`
   - 同一映射重复确认：累加 `usage_count`，更新 `last_used_at`
   - 全新映射：创建新记录

5. **冲突处理**：
   - 同一客户科目已有不同标准科目映射时，不静默覆盖
   - 返回 `status=conflict` + `conflict_detail`（含现有映射信息和中文提示）
   - `allow_overwrite=True` 时：停用旧映射（`is_active=False`），创建新记录

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

结果：
- 234 passed（16 个新测试 + 218 个已有测试）
- 3 warnings（均为已有 Pydantic/Deprecation 警告，非本次引入）

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend docs
```

结果：
- 通过（仅 Windows LF/CRLF 提示，无尾随空白或冲突标记）

### 测试覆盖场景

| 场景 | 测试类/方法 | 状态 |
| --- | --- | --- |
| 客户历史映射优先 | `TestCustomerHistoryPriority` | ✅ |
| 全局候选兜底（历史/代码/名称） | `TestGlobalFallback` (3 tests) | ✅ |
| 停用标准科目只作为警告 | `TestDisabledStandardAccount` (2 tests) | ✅ |
| 确认保存后下次推荐命中 | `TestSaveThenRecommend` (2 tests) | ✅ |
| 冲突映射需确认覆盖 | `TestConflictMapping` (2 tests) | ✅ |
| 边界情况 | `TestEdgeCases` (6 tests) | ✅ |

### API 端点

- `POST /api/v1/client-account-mappings/recommend` — 批量推荐映射候选
- `POST /api/v1/client-account-mappings/confirm` — 确认保存映射经验

### 风险和后续

- 无阻塞项
- 名称相似度使用 Python `SequenceMatcher` 在应用层计算，标准科目数量极大（>10000）时可能需改用数据库层模糊搜索
- 全局映射经验第一版由 `save_mapping` 写入（`customer_label=None`），后续 TASK-044 接入时统一管理
