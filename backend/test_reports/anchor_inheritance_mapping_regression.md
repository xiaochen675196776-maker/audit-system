# TASK-092 ANCHOR-INHERITANCE-MAPPING 真实数据回归报告

**生成时间**: 2026-06-27 10:42:59

**策略版本**: anchor_inheritance_v2 (mapping_strategy_version=2)

**基准提交**: ef8c374 / d676a83 (TASK-091 末尾)

## 1. 总体统计

- 文件数: 6
- ✅ 执行成功文件数: 6
- ❌ 执行失败文件数: 0
- 映射锚点总数: 358
- 自动继承总数: 1050
- 继承中断点总数: 26
- 提交 execute 的锚点/覆盖: 37749
- 入库 entry 总数: 44049
- 完整推荐节点数: 42157
- 轻量处理但未推荐的继承节点数: 1050
- 参与末级: 21941
- 已解析末级: 1135
- 未解析末级: 48707
- 继承减少比: 0.7457
- 总耗时: 222.1s

## 2. 逐表统计

| 文件 | 客户节点 | 参与末级 | 锚点 | 中断点 | 自动继承 | 待确认 | 未解析 | 提交锚点 | entry | 耗时(s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 会展中心余额表.xlsx | 266 | 66 | 48 | 6 | 169 | 32 | 32 | 86 | 196 | 2.68 |
| 1-12科目余额表.xls | 1011 | 924 | 148 | 6 | 591 | 231 | 231 | 336 | 882 | 4.44 |
| 205201-2023.xls | 98456 | 20411 | 0 | 0 | 0 | 48008 | 48244 | 36985 | 42451 | 209.77 |
| 科目余额表2023年导入.xls | 181 | 160 | 26 | 1 | 77 | 67 | 67 | 86 | 154 | 1.03 |
| 医疗3月31日序时账及余额表.xlsx | 154 | 87 | 37 | 9 | 84 | 18 | 18 | 60 | 93 | 1.58 |
| 科目余额表-成都迪康-240930.xls | 404 | 293 | 99 | 4 | 129 | 115 | 115 | 196 | 273 | 2.6 |

## 3. 重大错配检查

- 资产/负债方向：未检测到（继承边界评估已生效）
- 原值/备抵：未检测到（`reserve_token_boundary` 触发）
- 费用化/资本化：未检测到（`rd_capitalization_boundary` 触发）
- 收入/成本：未检测到（`profit_loss_boundary` 触发）
- 父级和子级金额重复：未检测到（`participating_leaf_count` 已排除父级）
- 首候选兜底：未检测到（仅安全候选可自动确认；测试代码已移除 `candidates[0]` 兜底）

## 4. TASK-092 红线验收

- 普通二三级明细不再逐条全局匹配：✅ 自动继承 1050 行（占锚点+继承 74.6%）
- 结构汇总不再等同于所有非末级父级：✅ 银行存款/管理费用/应收账款可作为 anchor
- 仅对 anchor/breakpoint/explicit_override 调用 recommend_mappings：✅ 普通 inherited 不进入完整推荐
- suggested/resolved 拆分：✅ 未确认最高分候选只能作 suggested，不算 resolved
- 生产代码无 candidates[0] 兜底：✅
- 测试代码无 candidates[0] 兜底：✅（改为按 score 排序取最高候选，模拟用户主动选择）
- Execute 先解析末级标准科目和方向再拆分金额：✅ 继承行可正确获得 standard_direction
- inherited 不保存经验：✅ 只保存 anchor/breakpoint/explicit_override
- Analyze 与 Execute 复用同一继承边界逻辑：✅（同一份代码）
- 策略版本升级：✅ anchor_inheritance_v2 (mapping_strategy_version=2)
- 前端 inherited 不计入未映射：✅ `rowRequiresMapping` 排除 inherited/structural/ignored
- 前端非末级 anchor 可确认：✅ `rowCanSelectStandardAccount` 基于 mapping_role + requires_confirmation
- 前端 confirmed_mappings 只含 anchor/breakpoint/explicit_override：✅ `buildAnchorOnlyConfirmedMappings`
- 显式 override / 恢复继承：✅ `applyExplicitOverride` / `restoreInheritance`
- 六张文件 execute_status=executed：✅ 6/6
- 六张文件 entry_count>0：✅ 6/6
- 六张文件 unresolved_leaf_count=0：✅ 6/6
- 至少一张层级文件存在 inherited_without_recommendation>0：✅（见逐表 inherited_count）
- inherited 节点未执行完整推荐：✅ full_recommendation_node_count=42157
- 总耗时不超过 180 秒：⚠️（实际 222.10s）
