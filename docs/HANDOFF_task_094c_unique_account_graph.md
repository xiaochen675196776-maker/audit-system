# TASK-094C 唯一节点图压缩 — 接手文档

> 文档生成时间：2026-06-27 18:20
> 接手人：另一位 AI / 工程师
> 原作者 session：`mvs_5943af96f33145e38d210983de9a0163`（因 daemon 重启中断）
> 工作区：`D:\APP\Codex-项目\13、审计系统`

---

## 1. 任务一句话总结

把 205201 这类大文件里 **98k 原始行（同一客户科目被不同父级展开）压缩成 ~714 唯一节点**，让 P0 提交量从 98k 降到 ~187 anchor + ~634 inherited（少量显式 + 大量继承），总耗时 ≤ 120s。

**核心思路**：构建 `UniqueAccountGraph` —— 把"原始行 → 唯一节点"做去重折叠，analyze/execute 两阶段共用同一份图，confirm/anchor/inherit 都在节点级而不是行级判定。

---

## 2. 当前进度

| 阶段 | 状态 |
|------|------|
| 数据结构 `UniqueAccountNode` / `UniqueAccountGraph` | ✅ 完成 |
| `build_unique_account_graph()` 函数 | ✅ 完成 |
| analyze 阶段接入（注入 node_key、节点统计） | ✅ 完成 |
| execute 阶段折叠 confirmed_mappings（行级 → 节点级） | ✅ 完成 |
| execute 阶段 `_recommend_anchor_exec`（折叠后查 SA） | ✅ 完成 |
| execute 响应加唯一节点统计字段 | ✅ 完成 |
| 三个测试文件 | ✅ 完成 |
| 094 系列 23 个测试 | ✅ 全部通过（110.21s） |
| **完整测试套件 534 个测试** | ⚠️ **未跑**（daemon 中断，未确认无回归） |
| 移除临时调试脚本 | ⚠️ 部分完成，可能残留 |
| 跑 fixture governance 094a 测试 | ⚠️ 未验证 |

---

## 3. 关键文件清单（必须先读）

### 核心代码
| 文件 | 行数 | 说明 |
|------|------|------|
| `backend/app/services/account_mapping_inheritance_service.py` | 1881 | `UniqueAccountNode`/`UniqueAccountGraph`/`build_unique_account_graph` 在 ~385–700 |
| `backend/app/services/standard_trial_balance_import_service.py` | 2486 | analyze/execute 阶段接入点，行号参考见 §4 |

### 测试
| 文件 | 状态 | 跑法 |
|------|------|------|
| `backend/tests/test_task_094c_unique_account_graph.py` | ✅ 通过 16/16 | 节点图基础 |
| `backend/tests/test_task_094c_duplicate_row_binding.py` | ✅ 通过 6/6 | 行绑定 |
| `backend/tests/test_task_094c_205201_compression.py` | ✅ 通过 1/1 | 205201 端到端 |
| `backend/tests/test_task_094a_fixture_governance.py` | ⚠️ 未验证 | fixture 管理 |

### 报告
| 文件 | 说明 |
|------|------|
| `backend/test_reports/task_094c_205201_unique_node_report.md` | 205201 实际压缩指标（必读） |
| `backend/test_reports/task_094c_205201_unique_node_report.json` | 同上，机器可读 |

---

## 4. 代码锚点（接手时直接跳这些行号）

### inheritance_service.py
- **L386 `UniqueAccountNode`** — 节点 dataclass，包含 `node_key`、`source_row_indexes`、`representative_row_index`、`node_type`（account/auxiliary/summary）、解析后字段（mapping_role/mapping_mode/anchor_node_key 等）
- **L423 `UniqueAccountGraph`** — 节点图：`nodes_by_key`、`row_to_node_key`、`children_by_key`、`root_keys`
- **L612 `build_unique_account_graph()`** — 构造函数，3 步走：
  1. 标准化 + 收集 `(account_code, account_name, full_path)` 签名
  2. 按签名去重，生成 `node_key`
  3. 构造/合并 `UniqueAccountNode`，建立父子关系
  4. 把原始行 index 通过 `row_to_node_key` 绑定

### standard_trial_balance_import_service.py
- **L59–60** import：`UniqueAccountGraph` / `UniqueAccountNode`
- **L62** import：`build_unique_account_graph`
- **L1778** execute 阶段 `execute_node_by_key` —— **折叠 confirmed_mappings 的关键循环**
- analyze 阶段：搜索 `node_key` 注入到 `mapping_recommendations` 的位置
- execute 阶段：搜索 `_recommend_anchor_exec` 定义，折叠后构造最小 recommend 函数查 DB

---

## 5. 测试命令

```powershell
# 工作目录必须切到 backend
Set-Location "D:\APP\Codex-项目\13、审计系统\backend"

# 094 系列（已通过，~110s）
& "D:\python\Scripts\pytest.exe" `
  tests/test_task_094c_unique_account_graph.py `
  tests/test_task_094c_duplicate_row_binding.py `
  tests/test_task_094c_205201_compression.py `
  -x --tb=short

# 完整套件（534 个测试，~5–10 分钟，注意后台跑 + 轮询日志）
& "D:\python\Scripts\pytest.exe" --tb=short -q --no-header

# pytest 路径注意：项目 venv 没装 pytest，用全局的
#   D:\python\Scripts\pytest.exe
#   Python: C:\Users\陈锐\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
```

**坑**：
- 项目 venv 没 pytest，必须用 `D:\python\Scripts\pytest.exe`
- 跑命令前要 `Set-Location` 到 `backend` 下，否则 conftest 找不到

---

## 6. 接手人待办清单（按优先级）

### 🔴 P0：验证无回归
1. **跑完整测试套件**（534 个）—— 这是原作者中断时**没来得及做的**
   ```powershell
   Set-Location "D:\APP\Codex-项目\13、审计系统\backend"
   & "D:\python\Scripts\pytest.exe" --tb=short -q --no-header 2>&1 | Tee-Object "$env:TEMP\pytest_full.log"
   ```
   - 如果有失败，重点看 analyze / execute / inheritance 相关模块
   - 已有报告 `task_094c_205201_unique_node_report.md` 显示压缩指标达成

### 🟡 P1：清理
2. 检查 `account_mapping_inheritance_service.py` / `standard_trial_balance_import_service.py` 里有没有残留的 `print(DEBUG ...)` 调试代码 —— 上次进度的最后一行说"现在移除 DEBUG 打印并重新测试"，可能没全删干净
3. 跑一次 `test_task_094a_fixture_governance.py` 确认 fixture 治理测试还在
4. 检查是否有临时调试脚本残留（grep `print` 或 `pprint` 在非测试文件）

### 🟢 P2：补强
5. 把 `_recommend_anchor_exec` 的实现和 analyze 阶段的 `_recommend_anchor` 合并去重（现在两套实现，并行存在）
6. 文档同步：在 `docs/STANDARD_TRIAL_BALANCE_NORMALIZATION_DESIGN.md` 加一节"唯一节点压缩"，引用本报告
7. 考虑把 094 系列三个测试合并 / 重构（现在 `094c_unique_account_graph.py` 有 16 个，可能需要拆分）

---

## 7. 已知的坑 & 边界

| 现象 | 原因 | 处理 |
|------|------|------|
| 父级（is_summary）会被自动跳过 | `_collect_zero_amount_template_rows` 之前的过滤把父级当模板行 | 已修复：从 `auto_skip_rows` 移除父级，让父级可成为 anchor |
| execute 阶段需要传 `recommend_anchor_fn` | 折叠后 anchor 解析需要查 DB | 已实现 `_recommend_anchor_exec` |
| 100201 是 inherited 行 | 折叠后所有重复行映射到代表行 | confirmed_mappings 只保存代表行的映射 |
| `row 0` 可能被标 ignored | 旧逻辑把根节点当模板行 | 已修复 `_collect_zero_amount_template_rows` |
| 缩进 bug 导致节点丢失 | analyze 阶段 `if not row_key:` 嵌套位置 | 已修复 |

---

## 8. 关键设计决策（为什么要这样做）

1. **为什么用 `node_key` 而不是 `account_code`？**
   同 account_code 可能出现在不同父级下，路径不同 → 节点必须包含父节点信息。`node_key = f"{parent_node_key}/{account_code}"` 形式。

2. **为什么 analyze 和 execute 共用同一份图？**
   避免重复构建 98k 行的折叠（耗时 ~80s）。两个阶段共用一份图后，execute 阶段只需做"折叠 + 写库"。

3. **为什么 confirmed_mappings 折叠到代表行？**
   同一节点的所有原始行映射应该一致。如果用户改了代表行的映射，所有重复行一起改。

4. **为什么 anchor 提交从 ~98k 降到 ~187？**
   因为唯一节点数只有 715，其中 ~187 是真 anchor（用户需要确认/审核的），~634 走 inheritance 继承（无需审核）。

---

## 9. 性能指标（已实测）

| 指标 | 数值 | 目标 |
|------|------|------|
| 原始行数 | 98,456 | — |
| 唯一节点数 | 715 | — |
| 重复绑定数 | 97,741 (>99%) | > 90% ✅ |
| 唯一节点 ≈ 唯一路径 | 715 vs 714 | ≈ ✅ |
| preview 耗时 | 1.79s | — |
| analyze 耗时 | 105.18s | — |
| 总耗时 | **106.97s** | ≤ 120s ✅ |

**结论**：核心压缩指标全部达成。剩下就是回归测试和清理。

---

## 10. 联系方式 / 上下文恢复

如果接手人跑通后想了解原作者的思考路径，参考：
- `backend/test_reports/task_093_205201_hierarchy_diagnostic.md` — 任务起源（205201 的层级问题诊断）
- `backend/test_reports/task_093_anchor_inheritance_e2e.md` — anchor 继承机制设计
- `backend/test_reports/task_094c_205201_unique_node_report.md` — 当前任务的实测报告

原作者的 session id：`mvs_5943af96f33145e38d210983de9a0163`（daemon 重启后已结束，无法恢复）
Scratchpad：空的（未留下任何笔记），所以这份文档就是唯一的恢复线索。

—— Mavis