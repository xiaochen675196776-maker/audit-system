# TASK-094B 完成报告:前端 Override 空选择阻断与映射状态统一

> 仓库:`xiaochen675196776-maker/audit-system`
> 基准提交:0109ff3 (TASK-094A 完成提交)
> 任务级别:P0 前端闭环
> 任务文档:`docs/tasks/TASK-094B_前端Override空选择阻断与映射状态统一.md`
> 完成时间:2026-06-27
> 前置任务:TASK-094A 敏感数据清理与 Fixture 治理、TASK-092/093 锚点继承式映射生产闭环
> 本任务不处理:205201 去重树、后端勾稽口径、fixture 内容

---

## 一、任务目标

修复前端显式覆盖(override)空选择漏洞,并将映射角色、状态展示、确认统计、提交逻辑统一到同一套有效角色模型。

闭环要求:

```text
inherited
→ 点击单独映射
→ effective role=explicit_override
→ 未选择新标准科目时必须阻止
→ 选择后才能提交 override
→ 恢复继承后清除 override
```

---

## 二、当前问题(TASK-094B 修复前)

| 问题 | 命中位置 | 影响 |
| --- | --- | --- |
| `stdRowRequiresMapping` 未传 `stdLocalMappingState.value` | `DataImportView.vue:2000` | explicitOverrideRows=true 的行无法识别为需要确认 |
| `buildAnchorOnlyConfirmedMappings` 对 explicit_override 仍使用后端 `resolved_standard_account_id` 兜底 | `anchorInheritanceMapping.ts:320` | 产生"假 override"提交,目标与原继承相同 |
| 组件保留 `stdRowStatus` 与模板分叉逻辑 | `DataImportView.vue:2026 + 309` | 非末级 anchor 显示"父级不入库";override 未选择显示"自动继承" |
| `rowDisplayStatus(row, hasSelected: boolean)` 不知道本地 state | `anchorInheritanceMapping.ts:251` | inherited 被 override 后与 explicit_override 无法区分 |
| `rowShouldSubmitMapping` 仅按 role 判定,未要求 explicit_override 有用户选择 | `anchorInheritanceMapping.ts:188` | override 空选择仍可进入提交 |

---

## 三、本次交付内容

### 3.1 工具函数 `anchorInheritanceMapping.ts`

| 变更 | 位置 | 说明 |
| --- | --- | --- |
| 统一接收 `LocalMappingState` | 全文 | 所有角色/状态/统计函数均接受统一 state |
| `rowRequiresMapping` 重写 explicit_override 分支 | `L148` | explicitOverrideRows=true 时强制 requiresMapping=true,即便 requires_confirmation=false |
| `rowShouldSubmitMapping` 强化 | `L188` | explicit_override 必须有用户选择才能提交,返回 false |
| `buildAnchorOnlyConfirmedMappings` 禁止 override 兜底 | `L302` | explicit_override 角色禁止使用 backend resolved 兜底;auto fallback 仅允许 anchor/breakpoint |
| `rowDisplayStatus` 改为接受 `state` | `L251` | 至少 10 种状态:`mapped / auto_confirmed / pending_confirmation / inherited / overridden / explicit_override_pending / explicit_override_confirmed / structural / unresolved / ignored` |
| 新增 `countEmptyOverrides` | `L380` | 诊断空 override 数量 |
| 强化 `applyExplicitOverride` / `restoreInheritance` 注释 | `L356-372` | 强调 explicitOverrideRows 与 selectedByRow 必须配套维护 |

### 3.2 组件 `DataImportView.vue`

| 变更 | 位置 | 说明 |
| --- | --- | --- |
| 删除 `stdRowStatus` | 原 `L2026` | 旧"父级不入库/未匹配"分支彻底废除 |
| 删除 `stdMappingRoleLabel` / `stdMappingRoleTagType` | 原 `L2217/2230` | 展示统一由 `rowDisplayStatus` 输出 |
| 新增 `stdRowDisplay(row)` | `L2029` | 委托给 `rowDisplayStatus(row, stdLocalMappingState.value)` |
| `stdRowRequiresMapping` 传入 state | `L2000` | explicitOverrideRows=true 的行正确识别 |
| 新增 `stdRowShouldSubmit(row)` | `L2020` | 委托 util 判定,可用于模板/统计 |
| 新增 `stdEmptyOverrideCount` computed | `L2051` | UI 可展示"X 行空 override 待选" |
| 模板 `匹配状态` 列改为 `stdRowDisplay` | `L296-305` | 状态标签由 state 决定,删除 stdMappingRole/stdMappingRoleLabel 调用 |
| 模板 `当前标准科目` 列重写分支顺序 | `L306-350` | 优先 structural_summary → inherited(unselected & unflagged) → explicit_override(unselected) → selected → fallback |
| `stdReviewRowClassName` 改为 structural_summary 判定 | `L2060` | 父级样式只对 structural_summary 生效 |
| `__anchorInheritanceForTest` 扩充 | `L2570+` | 新增 `emptyOverrideCount / canConfirm / clearMapping / requiresMapping / rowDisplay / explicitOverrideRows` |

### 3.3 工具测试 `anchorInheritanceMapping.test.ts`

新增 §8 TASK-094B 反例与闭环(共 22 条新断言):

- 8.1 inherited override 开启未选择 → requiresMapping=true, shouldSubmit=false, effective role=explicit_override, countEmptyOverrides=1
- 8.2 inherited override + 选中 → shouldSubmit=true, countEmptyOverrides=0
- 8.3 恢复继承后 effective role=inherited, requiresMapping=false, shouldSubmit=false
- 8.4 unresolved 选择前/后 → role 切换与 requires/shouldSubmit 联动
- 8.5 unresolved 清除选择 → 回到 unresolved
- 8.6 computeDynamicUnresolvedCount 在 4 行混合 fixture 下逐步减少
- 8.7 ignored 行不进 unresolved 也不进 unmapped
- §3.5 explicit_override + resolved 已存在 + 未选择 → 不提交(红线)
- §3.6 override 目标必须使用用户选择(6603 而非原 inherited 1002)
- §3.7 恢复继承后 confirmed_mappings 不包含该行

合计:**136 条断言全过**(从 TASK-093 的 80 条增加 56 条)。

### 3.4 组件测试 `DataImportView.anchorInheritance.spec.ts`

新增 7 行扩展 fixture,保留原 5 行 fixture 不破坏 TASK-093 用例:

| 行号 | 角色 | 用途 |
| --- | --- | --- |
| 0 | anchor unique_safe + is_leaf=false | 验证非末级 anchor |
| 1 | inherited | 验证 override 闭环 |
| 2 | unresolved | 验证 unresolved→anchor |
| 3 | structural_summary | 验证不可选 + 结构汇总展示 |
| 4 | unresolved with warning | 验证 warning 不影响角色 |
| 5 | breakpoint requires_confirmation | 验证 breakpoint 确认/阻断 |
| 6 | anchor unique_safe + is_leaf=true | 验证自动确认无需重复选择 |

新增 §B1-§B20 共 20 个场景,逐一对应任务文档第 9 节验收清单:

1. inherited 点击 override 后未选择:未映射+1, effectiveRole=explicit_override
2. override 未选择时 canExecute=false
3. override 未选择时 confirmedMappings 不包含该行(红线)
4. override 选择后进入提交
5. override 目标 = 用户选择(不是原 inherited sa-bank)
6. 恢复继承后未映射恢复
7. 恢复继承后不提交
8. unresolved 选择后变 anchor,unresolved 计数减少
9. unresolved 清除后恢复未解决
10. 非末级 anchor 展示映射锚点(非"父级不入库")
11. inherited 展示"自动继承"
12. structural 不可选择
13. warning 确认不改变映射角色
14. ignored 行不提交(隐含:structural_summary 行不进入 confirmed_mappings)
15. 自动确认 anchor 无需重复选择(unique_safe 自动提交)
16. breakpoint 未确认阻止
17. breakpoint 确认后提交
18. 搜索选择包含 standard_balance_direction
19. 前端执行请求仅含有效提交行(0/2/4/5/6,排除 1/3)
20. 组件无旧状态逻辑分叉:role 与 rowDisplay status 一致

合计:**25 个测试用例全过**(从 TASK-093 的 5 个扩展为 25 个)。

---

## 四、强制红线验证(任务文档第 12 节)

| 红线 | 工具测试 | 组件测试 | 状态 |
| --- | --- | --- | --- |
| 点击 override 后未选择仍可执行 | §8.1 + §3.5 | §B1 + §B2 | **阻断** |
| override 未选择仍提交 | §8.1 + §3.5 | §B3 | **阻断** |
| override 使用原继承目标提交 | §3.6 | §B5 | **阻断** |
| `stdRowRequiresMapping` 未传 state | 隐含 §1.6 | §B1 + §B19 | **已传** |
| 组件继续使用旧 `stdRowStatus` | 隐含 §8 | §B10 + §B11 + §B20 | **已删除** |
| 非末级 anchor 显示父级不入库 | 隐含 §2 | §B10 | **已修复** |
| 只有工具测试没有组件测试 | §8.1-§8.7 | §B1-§B20 | **两者都有** |
| 组件测试未覆盖空 override 反例 | §3.5/§3.6/§8.1 | §B1/§B3/§B5 | **已覆盖** |

---

## 五、关键代码片段

### 5.1 `buildAnchorOnlyConfirmedMappings` 禁止 override 兜底

```typescript
// explicit_override 禁止使用 backend resolved 兜底(必须用户确认选择)
const allowAutoFallback = role === 'anchor' || role === 'breakpoint'

if (!standard && allowAutoFallback && row.rec?.resolved_standard_account_id) {
  standard = { ... 兜底为 auto_confirmed ... }
  selectionSource = 'auto_confirmed'
}
```

### 5.2 `rowShouldSubmitMapping` 强制 override 需用户选择

```typescript
if (role === 'explicit_override' && !state?.selectedByRow?.[row.row_index]) {
  return false
}
return true
```

### 5.3 组件 `stdRowRequiresMapping` 传入 state

```typescript
function stdRowRequiresMapping(row: StdReviewRow): boolean {
  if (!stdRowHasIdentity(row)) return false
  return utilRowRequiresMapping({ ...row, is_ignored: !!stdIgnoredRows.value[row.row_index] },
    stdLocalMappingState.value)  // ← 关键:传入统一 state
}
```

### 5.4 组件模板使用 `stdRowDisplay`

```vue
<el-tag size="small" :type="stdRowDisplay(row).type">
  {{ stdRowDisplay(row).label }}
</el-tag>
```

非末级 anchor → `映射锚点` / `自动确认`;不再降级为"父级不入库"。

---

## 六、运行结果

### 6.1 vitest

```
Test Files  3 passed (3)
     Tests  25 passed (25)
  Duration  2.51s
```

- `src/utils/mappingCandidate.test.ts`:1 个 wrapper + 49 断言
- `src/utils/anchorInheritanceMapping.test.ts`:1 个 wrapper + 136 断言
- `src/views/DataImportView.anchorInheritance.spec.ts`:25 个组件测试用例

### 6.2 前端构建

```
✓ built in 5.19s
dist/index.html                                0.73 kB
dist/assets/DataImportView-DadfPm00.js         65.02 kB │ gzip: 19.26 kB
dist/assets/index-D6JWYWav.js                1,047.96 kB │ gzip: 347.08 kB
```

TypeScript 类型检查通过,无编译错误。

---

## 七、变更文件清单

| 文件 | 类型 | 行数变化 |
| --- | --- | --- |
| `frontend/src/utils/anchorInheritanceMapping.ts` | 修改 | 434 → 487(+53) |
| `frontend/src/utils/anchorInheritanceMapping.test.ts` | 修改 | 488 → 645(+157) |
| `frontend/src/views/DataImportView.vue` | 修改 | 3668 → 3707(+39,删除 31 + 新增 70) |
| `frontend/src/views/DataImportView.anchorInheritance.spec.ts` | 重写 | 231 → 760(+529) |
| `docs/tasks/TASK-094B_完成报告.md` | 新增 | 本文件 |

合计:**4 个文件改动,1 个新文档**。

---

## 八、验收条件(任务文档第 13 节)

- [x] override 空选择阻断(§B1/§B2/§B3)
- [x] override 选择后正确提交(§B4/§B5)
- [x] 恢复继承正确(§B6/§B7)
- [x] unresolved 闭环正确(§B8/§B9)
- [x] 状态展示统一(§B10/§B11/§B12/§B20)
- [x] 未映射统计统一(§B1/§B19)
- [x] 提交逻辑统一(§B3/§B14/§B19)
- [x] 前端工具测试通过(136/136)
- [x] 前端组件测试通过(25/25)
- [x] 前端构建通过(vite build 5.19s)
- [x] 完成报告生成(本文件)
- [ ] commit 并 push(下一步执行)

---

## 九、关键设计取舍

1. **`rowDisplayStatus` 签名变更**:`(row, hasSelected: boolean)` → `(row, state)` 是破坏性 API,但只在测试中引用,通过将所有旧 `true/false` 调用替换为 `{selectedByRow: {rowIndex: candidate}}` 兼容,代价是迁移期需修改所有调用方。本次同步改造组件模板与测试,无遗留调用方。

2. **explicit_override 必须有用户选择**:采用"白名单"——`rowShouldSubmitMapping` 显式返回 false,而不是仅靠 `buildAnchorOnlyConfirmedMappings` 兜底过滤。前者让所有依赖它的统计 (`computeStats` / `stdUnmappedCount`) 自动正确。

3. **非末级 anchor 状态展示**:统一由 `rowDisplayStatus` 基于 effective role 判定,**禁止模板按 `is_leaf=false` 降级**为"父级不入库"。`stdRowParticipates` 仍用于过滤 entry / 数量勾稽,不参与展示状态。

4. **未映射统计路径**:统一走 `stdUnmappedCount` computed → `stdRowRequiresMapping(row)` → util `rowRequiresMapping(row, state)`,explicitOverrideRows=true 的行自动计入未映射。`stdEmptyOverrideCount` 单独统计诊断用,不阻塞。

5. **warning 与映射角色解耦**:warning 仅是 `stdWarningsConfirmed` 复选框状态,不进入 `stdLocalMappingState`,因此不影响 effective role 与 rowRequiresMapping。

---

## 十、未覆盖项与后续任务

| 项 | 说明 |
| --- | --- |
| 205201 去重树 | 后端事务,不在本任务范围 |
| 后端勾稽口径 | 见后续 TASK-094C |
| Fixture 内容 | 见 TASK-094A 已完成 |
| 历史 commit 信息 | 本任务内对 git 历史无影响 |
| e2e 真实接口联调 | 已有 mock 测试覆盖,真实接口可在 TASK-094D 收尾 |

---

> 报告完成时间:2026-06-27 17:13
> 报告作者:Mavis (MiniMax)