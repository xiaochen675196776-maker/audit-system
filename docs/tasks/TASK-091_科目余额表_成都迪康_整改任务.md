# TASK-091 整改任务书：科目余额表标准化导入（成都迪康 240930 联调诊断）

> 接手前请先读完本文件。本任务基于 **2026-06-26** 的一次端到端真实联调（项目路径 `D:\APP\Codex-项目\13、审计系统`，样本 `D:\APP\谷歌\文件下载\科目余额表-成都迪康-240930.xls`），由 Mavis 跑出结果并整理。

---

## 0. 一句话结论

成都迪康 240930 的 xls **能跑通**：`status=executed`，404 行原始快照全量落库，293 条标准余额表 entry 入库，0 错误。**但**：

- 中途撞了 **3 个真实代码 bug**（不修也能跑，但要绕弯；不改会埋雷）
- 入库结果里有 **176 条 `disabled_standard_account` 警告**（全量 entry 都带 warning）
- 抽查发现 **多条映射错配**（子科目被前缀兜底匹配到不相关的标准科目，账目数据会算错）

下面分两段：
- **§1 三个代码 bug**（必修，影响后续所有客户）
- **§2 映射质量与警告问题**（必修 + 建议，影响数据正确性）

---

## 1. 三个代码 bug

### 1.1 【必修】ORM `Mapped[uuid.UUID]` 在 service 直调路径下会崩

**位置**：
- `backend/app/models/standard_trial_balance_import_batch.py` (id)
- `backend/app/models/standard_trial_balance_entry.py` (id, batch_id, raw_row_id, standard_account_id)
- `backend/app/models/standard_trial_balance_raw_row.py` (id, batch_id, parent_raw_row_id, mapped_standard_account_id)
- `backend/app/services/standard_trial_balance_import_service.py` 多处 `set[uuid.UUID] = set()` 但塞了 `str`

**现象**：
直接调用 `analyze_standard_import(db, batch_id=<str>, ...)` 时，SQLAlchemy 在 bind 阶段抛：

```
AttributeError: 'str' object has no attribute 'hex'
File "sqlalchemy/sql/sqltypes.py", line 3734, in process
    value = value.hex
```

数据库里的 id 都是 32 字符 hex 字符串（看 `audit.db` 里 43 个 batch、200 个 standard_account、201 个 entry，全是 32 字符 hex），但 ORM model 写的是 `Mapped[uuid.UUID]`，SQLAlchemy 推断出 `Uuid(as_uuid=True)`，bind processor 期待 `UUID` 对象，对 `str` 调 `.hex` 直接挂。

**为什么 HTTP 路径下能跑**：Pydantic schema (`app/schemas/standard_trial_balance.py`) 在 HTTP 边界用 `uuid.UUID` 强转了 str，service 内部拿到的就是 UUID 对象。**但 service 函数被其它 service / 测试 / 脚本直接调用时，就没人帮忙转，会爆。**

**复现脚本**（已跑通）：

```python
# 用 uuid.UUID 强制转才能跑
batch_id_uuid = uuid.UUID(preview_result["batch_id"])
await analyze_standard_import(db, batch_id=batch_id_uuid, ...)
```

**修复方案**（任选一种，都可，**推荐方案 B**）：

**方案 A：在 service 函数入口加防御性转换**
在 `app/services/standard_trial_balance_import_service.py` 三个 service 函数（`preview_standard_import` 不用，它只 INSERT）的最前面加：

```python
if isinstance(batch_id, str):
    batch_id = uuid.UUID(batch_id)
```

并在 `execute_standard_import` 第 1085-1089 行的 `all_sa_ids` 填充处，把 `sid` 强制转 `uuid.UUID`：

```python
for cm in confirmed_mappings:
    sid = cm.get("standard_account_id")
    if sid:
        try:
            all_sa_ids.add(sid if isinstance(sid, uuid.UUID) else uuid.UUID(str(sid)))
        except (ValueError, TypeError):
            pass
```

**方案 B：把 ORM id 字段类型从 `Mapped[uuid.UUID]` 改成 `Mapped[str]`（推荐）**
理由：
- 数据库存的就是 32 字符 hex str
- alembic 迁移 `20260622_0002_add_standard_trial_balance_tables.py` 里写的是 `sa.Uuid()`，生成的 CHAR(32) 字符串
- 当前 Pydantic schema 全程对 `uuid.UUID` 强转是因为 ORM 这么写了，下游必须跟着转
- 改成 `String(32)` 后，service 内部可以直接用 str，schema 改成 `str` 也行（保留 Pydantic 强转兼容也行）

修改点：
- `app/models/standard_trial_balance_import_batch.py`：`id: Mapped[uuid.UUID]` → `id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)`
- 同理改 entry、raw_row、standard_account、client_account_mapping 的 id
- `alembic/versions/20260622_0002_add_standard_trial_balance_tables.py`：`sa.Uuid()` → `sa.String(32)`
- `app/schemas/standard_trial_balance.py`：所有 `id: uuid.UUID` 改成 `id: str`（或者保留 `uuid.UUID`，因为 SQLAlchemy 还是会从 CHAR(32) 出来 str，Pydantic 的 `uuid.UUID` 会校验 32 字符 hex）

**方案 C（兜底）**：保持现状，但把所有直接调 service 的地方（包括将来其它 service 和测试）统一用 `uuid.UUID(...)` 包一层。

**验收**：
- 直接用 `analyze_standard_import(db, batch_id="<32字符hex>", ...)` 跑通，不抛 `.hex` 错误
- 既有 43 个历史批次、`/api/v1/standard-trial-balance-imports/{batch_id}/...` HTTP 路径继续工作

---

### 1.2 【必修】col_id 命名规范在两个模块里不一致

**位置**：
- `backend/app/services/file_parser.py:887` → `f"col_{i + 1:03d}"`（1 基，补零）→ `col_001`、`col_002` ...
- `backend/app/services/standard_trial_balance_import_service.py:51-53` → `f"col_{col_index}"`（0 基，不补零）→ `col_0`、`col_1` ...
- `backend/app/services/column_matcher.py` 里有 `"col_001"` `"col_010"` 字面量

**现象**：
- `preview_standard_import` 返回的 columns 用 0 基 `col_0..col_8`
- `analyze_standard_import` 内部用 `col_id_to_index[col_0] = 0` 索引
- 但前端（按 docs `STANDARD_TRIAL_BALANCE_NORMALIZATION_DESIGN.md` 设计的字段映射）按 `file_parser.build_columns` 习惯会发 `col_001`
- 这次联调我们用 `col_001` 传 analyze，所有列读出来都是 None，导致 `mapping_recommendations = 0`

**修复方案**（**强制统一为 0 基**）：
- `app/services/standard_trial_balance_import_service.py:_build_column_id` 改成 `return f"col_{col_index:03d}"` 或保持 `col_0` 也行（0 基本身没问题，只要统一）
- `app/services/file_parser.py:build_columns` 改成 `f"col_{i:03d}"`（去掉 +1）
- `app/services/column_matcher.py` 全文检查 `col_001` `col_010` 改 `col_0` `col_9`
- `app/api/imports.py` Form 描述里的 `col_001` 改 `col_0`
- 前端如果有任何硬编码 `col_001` 也要同步改

**验证脚本**：在 audit.db 之外再起一个 fresh DB，跑完整 `preview → analyze` 流程，看返回的 `columns[].column_id` 和前端发的 `field_mappings[].column_id` 是否对得上。

---

### 1.3 【必修】`disabled_standard_account` 警告分类名实不符

**位置**：
- `backend/app/services/standard_trial_balance_import_service.py:894-905`（`category: "disabled_standard_account"`）
- `backend/app/services/client_account_mapping_service.py` 兜底候选构造（`code_prefix_parent` / `parent_inherited_crosswalk` / `code_category_anchor` / `name_anchor` 都带 warning）

**现象**：
所有"候选带 warning 但不是真停用"的情况都被塞进 `disabled_standard_account` 警告分类。**结果是：审计端看到 `disabled_standard_account` 176 条会去查"哪些科目被停用了"——查完发现一个没停用，纯属误报。**

**修复方案**：
- 在 `app/schemas/standard_trial_balance.py:546` 附近的 `WarningItem.category` 注释里加新分类 `fallback_candidate`（兜底候选）
- `app/services/standard_trial_balance_import_service.py:894-905` 改成按候选 `source` 区分：
  - `code_match_conflict` / `history_conflict` / 真正指向已停用 SA 的 → `disabled_standard_account`（保留原语义）
  - `code_prefix_parent` / `parent_inherited_crosswalk` / `code_category_anchor` / `name_anchor` → `fallback_candidate`（新分类）
- 前端警告中心按 category 分别展示，不要让审计员在 176 条假"停用"里翻

**验收**：
- 跑成都迪康的 analyze，warnings 不再全部叫 `disabled_standard_account`
- 真的指向停用标准科目的候选，分类仍然是 `disabled_standard_account`

---

## 2. 映射质量与警告问题

### 2.1 【必修】成都迪康子科目按代码前缀兜底，匹配到不相关的标准科目

**位置**：
- `app/services/client_account_mapping_service.py:_query_code_prefix_parent`（最大前缀匹配）
- `app/services/client_account_mapping_service.py:_build_code_prefix_parent_candidate` / `_build_parent_inherited_candidate`

**实测问题映射**（来自 `standard_trial_balance_entries` 表）：

| 客户科目代码 | 客户科目名称 | 实际映射到 | 应该映射到 | 错配原因 |
|---|---|---|---|---|
| 101207 | （其他货币资金明细） | 1001 库存现金 | 1012 其他货币资金 | `_query_code_prefix_parent` 截断找"1012"最长前缀没匹配，落到"10" 找不到，回退到 1001 |
| 112202 | 外部单位 | 112101 应收票据 | 112201 应收账款 | 标准科目缺 1121 父级，112202 找不到 1122 父级 |
| 11230202 | 待摊费用 | 1801 长期待摊费用 | 112402 减：坏账准备/预付款项 | 代码前缀 1123 在标准科目里没有 |
| 660102 | （管理费用明细） | 160101 固定资产 | 6602 管理费用 | 同上，66xx 父级匹配失败 |
| 660202 | （研发支出明细） | 160101 固定资产 | 660201 研发支出_费用化 | 同上 |
| 670201 | （营业外支出明细） | 112201 应收账款 | 6711 营业外支出 | 同上 |

**根因**：
1. **标准科目表只有 200 个一级/二级科目**，没有子科目明细（如 `10020101` 农行XX支行 这种客户子科目在标准表里没有对应）
2. `_query_code_prefix_parent` 用 `LIKE '1002%'` 找最长前缀，**但只匹配 `account_code` 字段，不是 `account_name`**
3. 当客户代码是 `11230202`、标准表里没有 `1123` 时，回退路径就是"匹配第一段"或者 fallback 到 name_similarity，质量崩塌

**修复方案**（**多管齐下**）：
- 短期：在 `_build_code_prefix_parent_candidate` 里，**当最长前缀匹配到的标准科目方向或类别与客户代码前缀不匹配时（比如匹配到的是 1001 库存现金但客户是 11230202 待摊费用），降级为 warning=不推荐匹配，不自动填到 candidates[0]**
- 中期：**扩充标准科目表**，加入常见子科目（100201、100202、1121、1122、1123、6601xx、6602xx、6603xx 等），让 `_query_code_prefix_parent` 能精确匹配
- 长期：**成都迪康这种大型药企的子科目应该用「公司历史映射经验」来匹配**，但 audit.db 里现在还没有 "成都迪康" 的历史 client_account_mapping（见 §2.3）

**验收**：
- 重跑成都迪康 analyze，101207 应该匹配到 1012 而不是 1001
- 112202 应该匹配到 112201 而不是 112101
- 176 条 `disabled_standard_account` 警告应该明显减少（缩减到 30-50 条甚至更少，剩余是真正需要人工确认的）

---

### 2.2 【必修】`auto_confirm_status` 全部是 `None`，所有兜底候选都没被自动确认

**现象**：
analyze 阶段 293 个 participating 行的 `auto_confirm_candidate` 全是 None（看 log `auto_confirm=None`），原因是兜底候选（code_prefix_parent、parent_inherited_crosswalk）都带 warning，**`pick_unique_auto_confirm_candidate` 的安全候选阈值要求 `score >= 0.9 + warning is None + auto_confirmable=True`**，所以兜底候选全被排除。

**后果**：
- 前端 293 行全部要人工点选映射（工作量巨大）
- 如果用户不点选直接点"确认"，**`execute_standard_import` 会用 candidates[0]（兜底）作为确认结果，176 条警告会被强行入库**

**修复方案**：
- 在 `app/services/client_account_mapping_service.py:pick_unique_auto_confirm_candidate` 里加一条规则：**当唯一候选是兜底候选时，不自动确认但提示"建议人工确认（兜底匹配）"**，前端可以根据 `auto_confirm_status == "fallback_only"` 展示"待确认但可一键放行"
- `execute_standard_import` 当 `confirmed_mappings` 不全时，**给出明确报错"未覆盖行号 X/Y/Z"，而不是 fallback 到 candidates[0]**（这样用户必须显式选映射）

**验收**：
- 重跑 analyze，auto_confirm 不再全是 None
- execute 阶段如果 confirmed_mappings 缺行，应明确报错而不是兜底

---

### 2.3 【建议】audit.db 里没有"成都迪康"的历史 client_account_mapping

**现状**：
```
select count(*) from client_account_mappings where customer_label='成都迪康' and is_active=1
→ 0
```

成都迪康是这次第一次导入，所以没有历史经验可用。但 audit.db 里 200 个标准科目已经准备好，下一批客户（汇达228、TASK-067-realfile 等）应该有。

**建议**：
- 本次 execute 已经把 293 条映射经验 `created` 落库（看 execute 返回值 `mapping_saved_count: 293`）
- 后续成都迪康的 9 月、10 月、12 月导入，会自动用上这次的经验
- 但**这次入库的很多映射质量不高**（见 §2.1），下一批导入会继续传播错误
- 建议在 `execute_standard_import` 的 `save_mapping_experience` 阶段，**只保存 `code_match` / `name_exact` / `user_confirmed` 来源的映射，不保存兜底候选**（避免污染后续经验库）

---

### 2.4 【建议】审计端展示需要区分"被自动确认" vs "被兜底匹配" vs "人工指定"

**建议**：
- 前端在科目映射页，**对每行高亮 source**：
  - 🟢 `code_match` / `name_exact` / `company_history`：高置信
  - 🟡 `semantic_alias` / `name_prefix` / `code_prefix_parent`：中置信，建议看一眼
  - 🔴 `name_similarity` / `code_category_anchor` / `name_anchor`：低置信，必须人工选
- 当前前端不知道这一信息，因为 analyze 返回的 candidates 没有 `confidence_band` 字段

**修复**：在 `app/schemas/standard_trial_balance.py:ClientAccountMappingCandidate` 加 `confidence_band: Literal["high", "medium", "low"]` 字段，由 service 在 `recommend_mappings` 时按 source 标好。

---

## 3. 优先级与工期

| 序号 | 项目 | 类型 | 优先级 | 预估 |
|---|---|---|---|---|
| 1.1 | ORM UUID 类型 / service 防御性转换 | Bug | P0 必修 | 1h |
| 1.2 | col_id 命名统一 | Bug | P0 必修 | 30min |
| 1.3 | 警告分类实不符 | Bug | P0 必修 | 30min |
| 2.1 | 子科目兜底匹配质量 | 数据/逻辑 | P1 必修 | 4h（要扩标准科目） |
| 2.2 | auto_confirm 全 None / 兜底入库 | 逻辑 | P1 必修 | 1h |
| 2.3 | 经验库污染防护 | 建议 | P2 | 30min |
| 2.4 | confidence_band 字段 | 建议 | P2 | 1h |

P0 = 必修，否则其它客户的导入会持续遇到 P0 bug
P1 = 必修，否则数据正确性会有问题
P2 = 建议，提升体验

---

## 4. 验收用例（修完后必跑）

1. **P0 全过**：
   - 直接 `analyze_standard_import(db, batch_id=<32字符hex str>, ...)` 不报 `.hex` 错误
   - analyze 返回的 columns[].column_id 和前端发送的 field_mappings[].column_id 格式完全一致
   - 跑成都迪康 analyze，warnings 分类里 `disabled_standard_account` 不再占满 176 条

2. **P1 数据正确**：
   - 成都迪康 execute 后，101207 → 1012 其他货币资金
   - 112202 → 112201 应收账款
   - 660102 → 6602 管理费用
   - 660202 → 660201 研发费用

3. **P1 入库可控**：
   - confirmed_mappings 缺行时，execute 明确报错而不是 fallback
   - 兜底候选不进入 client_account_mappings 经验库

4. **回归**：
   - 历史 42 个已 executed 批次能正常查询
   - `/api/v1/standard-trial-balances/tree` 接口不报 UUID 错误

---

## 5. 附录：跑通时的实际数据

```
文件: D:\APP\谷歌\文件下载\科目余额表-成都迪康-240930.xls
sheet: Sheet, 409 行 × 9 列
表头结构（2 行合并后）:
  col_0  科目编号
  col_1  科目名称
  col_2  期初_方向
  col_3  期初_金额
  col_4  本期发生_借方
  col_5  本期发生_贷方
  col_6  余额_方向
  col_7  余额_金额
  col_8  一级科目_金额（实际是层级数字 1-4，不是金额）
数据行: 404
末行: '合计' 行（自动跳过）

字段映射：
  account_code       → col_0
  account_name       → col_1
  opening            → col_3 (single_by_source_direction, direction=col_2)
  current            → col_4 (two_column, debit=col_4, credit=col_5)
  ending             → col_7 (single_by_source_direction, direction=col_6)

执行结果：
  batch_id           = 8dd1d945-cd77-4401-8e66-bf53b6bde1ee
  status             = executed
  errors             = 0
  warnings           = 176 (全部 disabled_standard_account 分类)
  raw_row_count      = 404
  entry_count        = 293
  mapping_saved_count = 293
  debug_timings      = {load_rows: 0.01, build_and_transform: 0.01, raw_row_insert: 0.02, entry_insert: 0.02, save_mapping: 0.61}
```

---

> 任务下达：Mavis，2026-06-26 21:50（Asia/Shanghai）
> 文件路径：D:\APP\Codex-项目\13、审计系统\docs\tasks\TASK-091_科目余额表_成都迪康_整改任务.md
> 接手人：另一位 AI
