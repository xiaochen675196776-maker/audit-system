# TASK-095B 完成报告

> 基准提交: `9a22671e40646a60390e766fc1233fbc547f57cb`
> 完成提交: 本报告所在提交
> 范围: NodeKey 级确认、Execute 节点级解析、原始行绑定、映射经验按节点去重、前端唯一节点提交、205201 专项报告

---

## 1. 完成结论

TASK-095B 已完成。标准科目余额表导入的确认、执行和经验保存主键已从原始 `row_index` 切换到稳定的 `node_key` 口径；旧 `confirmed_mappings` 仍兼容，但会先折叠到同一 `node_key`，同节点同目标去重，同节点不同目标阻断。

205201 真实文件闭环指标满足红线：98,456 行识别为 715 个唯一节点，新模式提交 714 个节点确认，行级确认 0，重复行提交 0，未解析节点 0，业务金额差异 0.00。

---

## 2. 关键实现

- `AnalyzeResponse` 新增 `unique_mapping_nodes` 和 `row_node_bindings`，并在旧行级 recommendation 上携带 `node_key` 等兼容元数据。
- 新增 `ConfirmedNodeMapping` 与 `ExecuteRequest.confirmed_node_mappings`，API 透传到执行服务。
- `node_key` 使用 `uak:v2:<sha256>`，输入包含 `customer_label`、标准化科目代码、标准化科目名称和标准化父级完整路径。
- Execute 阶段重建 `UniqueAccountGraph`，验证 node_key 版本，折叠新旧确认输入，再应用继承/覆盖规则并传播到所有绑定原始行。
- 原始行新增 `node_key`、`anchor_node_key` 字段；已解析行的 `mapping_source` 使用 `node_binding`。
- 映射经验按 `node_key` 去重，仅保存 anchor / breakpoint / explicit_override，不保存 inherited 或重复绑定行。
- 前端在后端返回唯一节点时提交 `confirmed_node_mappings`，并保持旧后端无唯一节点响应时的行级兼容路径。

---

## 3. 205201 专项指标

- `raw_row_count`: 98456
- `unique_node_count`: 715
- `confirmed_node_mapping_count`: 714
- `auto_confirmed_node_count`: 0
- `manual_confirmed_node_count`: 714
- `duplicate_row_submit_count`: 0
- `row_level_confirmed_mapping_count`: 0
- `mapping_experience_saved_count`: 713
- `entry_count`: 18917
- `unresolved_node_count`: 0
- `max_business_amount_difference`: 0.00

报告文件:

- `backend/test_reports/task_095b_205201_node_mapping.json`
- `backend/test_reports/task_095b_205201_node_mapping.md`

---

## 4. 验收命令

```bash
pytest backend/tests/test_task_095b_node_mapping_api.py backend/tests/test_task_095b_node_execute_resolution.py backend/tests/test_task_095b_mapping_experience_dedup.py backend/tests/test_task_094c_unique_account_graph.py backend/tests/test_task_094c_duplicate_row_binding.py backend/tests/test_task_095b_205201_report.py -q
npm test -- DataImportView.uniqueNodeMapping.spec.ts DataImportView.anchorInheritance.spec.ts
npm run build
python scripts/check_sensitive_fixture.py --strict --root .
```

验收结果:

- 后端任务相关回归: `29 passed`
- 前端行为测试: `2 passed`, `24 passed`
- 前端构建: 通过
- 敏感扫描: `files_scanned=304`, `hit_count=0`

---

## 5. 风险说明

本任务保留旧 `confirmed_mappings` 输入作为兼容入口，但新前端在存在 `unique_mapping_nodes` 时不再提交行级确认。205201 专项报告测试为验证节点级闭环，会根据唯一节点准备测试库内标准科目；这不改变生产标准科目维护规则。
