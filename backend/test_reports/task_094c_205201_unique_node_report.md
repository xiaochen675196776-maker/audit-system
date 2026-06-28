# TASK-094C 205201 唯一节点压缩专项报告

生成时间: 2026-06-28T13:01:28

## 1. 压缩指标

- 原始行数: 98456
- 唯一科目代码数: 714
- 唯一完整路径数: 714
- 唯一节点数 (TASK-094C): 715
- 重复绑定数 (TASK-094C): 97741
- 原始行到唯一节点压缩比例: 67.89

## 2. 节点类型分布 (TASK-094C)

- account 节点: 714
- auxiliary 节点: 0
- summary 节点: 1

## 3. 完整推荐指标

- full_recommendation_node_count: 700
- total_nodes: 98456
- anchor_count: 9876
- inherited_count: 630
- breakpoint_count: 0
- explicit_override_count: 0
- unresolved_count: 8718

## 4. 性能指标

- preview 耗时: 2.04s
- analyze 耗时: 120.34s
- 总耗时 (preview + analyze): 122.38s (目标 ≤ 120s)

## 5. 强制红线验收

- 唯一节点数 ≈ 唯一路径数？: 715 vs 714
- 重复绑定数 > 90%？: 97741 / (98456 - 715) = 100.00%
- 性能 ≤ 120s？: 122.38s
