# TASK-094C 接手 Prompt（直接复制给下一个 AI）

> 把下面 ````prompt ... ```` 标记之间的整块内容，原样粘贴给接手 AI 即可。
> 配合 `docs/HANDOFF_task_094c_unique_account_graph.md` 一起用效果最佳。

---

````prompt
你正在接手一个**已完成 90% 的 P0 后端架构任务**。原 session 因为 daemon 重启中断，留下了完整可工作的代码 + 23 个通过的测试，但**完整回归测试未跑**。你的核心职责是：验证无回归 + 收尾清理。

## 1. 任务一句话

把 205201 这类大文件（98k 原始行）压缩成 ~714 唯一节点 + ~187 anchor + ~634 inherited。核心思路：构建 `UniqueAccountGraph`，把"原始行 → 唯一节点"做去重折叠，analyze/execute 两阶段共用同一份图，confirm/anchor/inherit 都在节点级而不是行级判定。

性能目标：preview + analyze ≤ 120s。压缩比目标：唯一节点 ≈ 唯一路径，重复绑定 > 90%。

## 2. 已完成（不要重新做）

- ✅ `UniqueAccountNode` / `UniqueAccountGraph` 数据结构（dataclass）
- ✅ `build_unique_account_graph()` 函数
- ✅ analyze 阶段接入（node_key 注入 + 节点统计字段）
- ✅ execute 阶段 confirmed_mappings 折叠（行级 → 节点级）
- ✅ execute 阶段 `_recommend_anchor_exec`（折叠后查 DB）
- ✅ 3 个测试文件，共 23 个测试，**全部通过**

## 3. 你必须做的（按优先级）

### 🔴 P0：跑完整回归测试 —— 这是原作者**没来得及做**的

```powershell
Set-Location "D:\APP\Codex-项目\13、审计系统\backend"
& "D:\python\Scripts\pytest.exe" --tb=short -q --no-header 2>&1 | Tee-Object "$env:TEMP\pytest_full.log"
```

- 总数：**534 个测试**，预计 5–10 分钟
- 如果失败，重点看 `analyze` / `execute` / `inheritance` 相关模块
- pytest 路径必须是 `D:\python\Scripts\pytest.exe`（项目 venv 没装 pytest）

### 🟡 P1：清理

1. 在以下两个文件 grep `print(` 或 `pprint`，删除任何残留的调试输出：
   - `backend/app/services/account_mapping_inheritance_service.py`
   - `backend/app/services/standard_trial_balance_import_service.py`
   （原作者最后说"现在移除 DEBUG 打印并重新测试"，可能没全删干净）

2. 检查是否有临时调试脚本残留：`Get-ChildItem "D:\APP\Codex-项目\13、审计系统\backend" -Filter "*debug*" -Recurse`

### 🟢 P2：补强

3. `_recommend_anchor_exec` 和 analyze 阶段的 recommend 函数可能重复，**不要急着合并**（等你跑通 P0 后再说）

## 4. 关键代码锚点（先跳这里看）

### `backend/app/services/account_mapping_inheritance_service.py`（1881 行）
- **L386 `UniqueAccountNode`** — 节点 dataclass
- **L423 `UniqueAccountGraph`** — 节点图（nodes_by_key / row_to_node_key / children_by_key / root_keys）
- **L612 `build_unique_account_graph()`** — 构造函数，3 步走：标准化签名 → 按签名去重生成 node_key → 构造节点 + 父子关系 + 行绑定

### `backend/app/services/standard_trial_balance_import_service.py`（2486 行）
- **L59–62** import：`UniqueAccountGraph` / `UniqueAccountNode` / `build_unique_account_graph`
- **L1778** execute 阶段 `execute_node_by_key` —— 折叠 confirmed_mappings 的关键循环
- 搜 `node_key` 找 analyze 阶段注入点
- 搜 `_recommend_anchor_exec` 找 execute 阶段推荐函数

## 5. 测试文件位置

| 文件 | 状态 | 说明 |
|------|------|------|
| `backend/tests/test_task_094c_unique_account_graph.py` | ✅ 16/16 通过 | 节点图基础 |
| `backend/tests/test_task_094c_duplicate_row_binding.py` | ✅ 6/6 通过 | 行绑定 |
| `backend/tests/test_task_094c_205201_compression.py` | ✅ 1/1 通过 | 205201 端到端 |
| `backend/tests/test_task_094a_fixture_governance.py` | ⚠️ 未验证 | 你需要跑一下 |

094 系列跑法（已通过版本，~110s）：
```powershell
Set-Location "D:\APP\Codex-项目\13、审计系统\backend"
& "D:\python\Scripts\pytest.exe" `
  tests/test_task_094c_unique_account_graph.py `
  tests/test_task_094c_duplicate_row_binding.py `
  tests/test_task_094c_205201_compression.py `
  -x --tb=short
```

## 6. 已知的坑（不要重新踩）

| 现象 | 已修复方式 |
|------|-----------|
| 父级（is_summary）被自动跳过 | 从 `auto_skip_rows` 移除父级 |
| execute 需要传 `recommend_anchor_fn` | 已实现 `_recommend_anchor_exec` |
| 100201 是 inherited 行 | confirmed_mappings 只保存代表行的映射 |
| `row 0` 被标 ignored | 修复 `_collect_zero_amount_template_rows` |
| 缩进 bug 导致节点丢失 | 已修复 `if not row_key:` 嵌套位置 |

## 7. 验证标准（你的"完成"定义）

- [ ] 完整 534 个测试全部通过
- [ ] 没有 `print(DEBUG` 或临时调试脚本残留
- [ ] 在 `backend/test_reports/task_094c_full_regression.md` 写一份回归报告（pass/fail 数量、耗时、是否有 skip）
- [ ] 如果有失败，要么修，要么明确记录"已知失败 + 不阻塞 094C 主任务"

## 8. 性能基线（不要变差）

| 指标 | 数值 | 目标 |
|------|------|------|
| preview + analyze 耗时 | 106.97s | ≤ 120s |
| 唯一节点数 | 715 | ≈ 唯一路径数（714） |
| 重复绑定率 | 100.00% | > 90% |
| anchor 提交量 | 187 | — |
| inherited 量 | 634 | — |

实测报告：`backend/test_reports/task_094c_205201_unique_node_report.md`

## 9. 上下文恢复（如果 prompt 不够）

完整设计决策和扩展阅读：
- `docs/HANDOFF_task_094c_unique_account_graph.md`（人看的版本）
- `backend/test_reports/task_094c_205201_unique_node_report.md`（实测报告）
- `backend/test_reports/task_093_anchor_inheritance_e2e.md`（anchor 继承机制）
- `backend/test_reports/task_093_205201_hierarchy_diagnostic.md`（任务起源）

原作者 scratchpad 是空的，没有更多笔记了。**这份 prompt 就是你唯一的恢复线索**。

## 10. 完成后的回报格式

回复给我时，按这个格式：
```
TASK-094C 接手完成
- 回归测试：X / 534 通过（耗时 Ys）
- 残留调试代码：已清理 / 残留 N 处
- 094a fixture 测试：通过 / 失败
- 性能基线：未变差 / 已变差（说明）
- 已知问题：...（如有）
```

不要扩展任务范围，**只做收尾**。如果你觉得需要重构/合并，那是 P2 之后的事，跑通 P0 再说。
````

---

## 给接手 AI 的小贴士

1. **先跑 P0 回归，再做任何改动** —— 你不知道还有谁会同时改这个文件
2. **保留现有报告不动** —— `task_094c_205201_unique_node_report.md` 是原作者的产出，直接覆盖会丢失历史
3. **如果遇到 Pydantic 警告**（`class-based config is deprecated`）—— 无关，忽略
4. **如果完整套件里有 skip** —— 看是不是 fixture 缺失，那是历史问题，不是 094C 引入的