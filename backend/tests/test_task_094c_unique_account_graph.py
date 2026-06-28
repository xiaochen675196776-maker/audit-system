"""TASK-094C：唯一科目节点图基础结构与算法测试。

覆盖：
1. node_key 同 code/name/parent 重复 → 同 key；
2. node_key 同 code 不同 parent_path → 不同 key（防误合并）；
3. node_key 同 name 不同 code → 不同 key；
4. node_key 同 code+name 不同父 → 不同 key；
5. node_key 同一 path 但 case/空白差异 → 同 key（标准化折叠）；
6. account 节点 vs auxiliary 节点 vs summary 节点分类正确；
7. 树状 children_by_key 关系正确；
8. representative_row_index 取最小 row_index；
9. row_to_node_key 绑定覆盖每条原始行；
10. 1000 行重复绑定到 1 节点 → 压缩比 ≈ 1000。
"""

from __future__ import annotations

from app.services.account_mapping_inheritance_service import (
    UniqueAccountGraph,
    UniqueAccountNode,
    build_account_tree,
    build_unique_account_graph,
    classify_node_type,
    compute_unique_node_key,
)


# ── 1. node_key 标准化 ────────────────────────────────


def test_node_key_same_code_name_parent_returns_same_key():
    k1 = compute_unique_node_key("1002", "银行存款", "\\资产类")
    k2 = compute_unique_node_key("1002", "银行存款", "\\资产类")
    assert k1 == k2
    assert k1.startswith("uak:")


def test_node_key_different_parent_returns_different_key():
    """同 code 不同父路径 → 不同 node_key（防误合并）。"""
    k1 = compute_unique_node_key("1122", "应收账款", "\\资产类")
    k2 = compute_unique_node_key("1122", "应收账款", "\\流动资产")
    assert k1 != k2


def test_node_key_different_code_returns_different_key():
    k1 = compute_unique_node_key("1002", "银行存款", "\\")
    k2 = compute_unique_node_key("1001", "库存现金", "\\")
    assert k1 != k2


def test_node_key_different_name_returns_different_key():
    k1 = compute_unique_node_key("1122", "应收账款", "\\")
    k2 = compute_unique_node_key("1122", "其他应收款", "\\")
    assert k1 != k2


def test_node_key_normalizes_whitespace_and_case():
    """标准化：去首尾空白、折叠内部空白、转大写。"""
    k1 = compute_unique_node_key(" 1002 ", " 银行  存款 ", "资产类")
    k2 = compute_unique_node_key("1002", "银行 存款", "资产类")
    assert k1 == k2
    k3 = compute_unique_node_key("1002", "BANK DEPOSIT", "ASSETS")
    k4 = compute_unique_node_key("1002", "bank deposit", "assets")
    assert k3 == k4


def test_node_key_empty_code_or_name_is_distinguished():
    """空 code vs 空 name 不能误合并到同一 key。"""
    k1 = compute_unique_node_key(None, "客户A", "\\资产类")
    k2 = compute_unique_node_key("1002", None, "\\资产类")
    assert k1 != k2


def test_node_key_handles_none_inputs():
    """全空输入仍返回稳定 key（不会抛错）。"""
    k = compute_unique_node_key(None, None, None)
    assert k.startswith("uak:")
    assert len(k) > 8


# ── 2. 节点类型分类 ────────────────────────────────


def test_classify_account_node():
    assert classify_node_type("1002", "银行存款", False) == "account"


def test_classify_auxiliary_node_bracketed_name():
    """含方括号的辅助核算明细 → auxiliary。"""
    assert classify_node_type(None, "[0010004] 茂名市化工有限公司", False) == "auxiliary"


def test_classify_auxiliary_node_customer_prefix():
    assert classify_node_type(None, "客户:黄林兰", False) == "auxiliary"
    assert classify_node_type(None, "供应商:某公司", False) == "auxiliary"
    assert classify_node_type(None, "部门:研发部", False) == "auxiliary"


def test_classify_summary_node_empty_code_and_name():
    assert classify_node_type(None, None, False) == "summary"


def test_classify_summary_node_empty_code_with_summary_flag():
    assert classify_node_type(None, "研发支出", True) == "summary"


# ── 3. 唯一节点图 ────────────────────────────────


def test_build_graph_merges_duplicate_rows():
    """同一 (code, name, parent) 重复 1000 行 → 1 个唯一节点。"""
    rows_meta = []
    for ri in range(1000):
        rows_meta.append({
            "row_index": ri,
            "client_account_code": "100201",
            "client_account_name": "工行账户",
            "level": 2,
            "parent_key": "1002",
            "parent_row_index": 0,
            "is_leaf": True,
            "is_summary": False,
            "ancestor_codes": ["1002"],
            "ancestor_names": ["银行存款"],
        })
    # 父级
    rows_meta.insert(0, {
        "row_index": 1000,
        "client_account_code": "1002",
        "client_account_name": "银行存款",
        "level": 1,
        "parent_key": None,
        "parent_row_index": None,
        "is_leaf": False,
        "is_summary": True,
        "ancestor_codes": [],
        "ancestor_names": [],
    })
    tree = build_account_tree(rows_meta)
    graph = build_unique_account_graph(tree, rows_meta=rows_meta)
    assert len(graph.nodes_by_key) == 2  # 1002 父级 + 100201 合并节点
    target_node = next(
        n for n in graph.nodes_by_key.values()
        if n.account_code == "100201"
    )
    assert len(target_node.source_row_indexes) == 1000
    assert target_node.representative_row_index == 0  # 最小 row_index
    # 行绑定数 = 总行数
    assert len(graph.row_to_node_key) == 1001


def test_build_graph_different_parents_do_not_merge():
    """同 code 同 name 但不同父路径 → 拆分为多个节点。"""
    rows_meta = [
        {"row_index": 0, "client_account_code": "1122", "client_account_name": "应收账款", "level": 1, "parent_key": None, "parent_row_index": None, "is_leaf": False, "is_summary": True, "ancestor_codes": [], "ancestor_names": []},
        {"row_index": 1, "client_account_code": "112201", "client_account_name": "应收账款", "level": 2, "parent_key": "1122", "parent_row_index": 0, "is_leaf": True, "is_summary": False, "ancestor_codes": ["1122"], "ancestor_names": ["应收账款"]},
        {"row_index": 2, "client_account_code": "122101", "client_account_name": "其他应收账款", "level": 1, "parent_key": None, "parent_row_index": None, "is_leaf": False, "is_summary": True, "ancestor_codes": [], "ancestor_names": []},
        {"row_index": 3, "client_account_code": "112201", "client_account_name": "应收账款", "level": 2, "parent_key": "122101", "parent_row_index": 2, "is_leaf": True, "is_summary": False, "ancestor_codes": ["122101"], "ancestor_names": ["其他应收账款"]},
    ]
    tree = build_account_tree(rows_meta)
    graph = build_unique_account_graph(tree, rows_meta=rows_meta)
    # 4 个原始行 → 4 个唯一节点（不合并）
    assert len(graph.nodes_by_key) == 4
    # 行 → 节点一一对应
    assert len(graph.row_to_node_key) == 4


def test_build_graph_children_by_key_relations():
    """父子关系通过 children_by_key 正确建立。"""
    rows_meta = [
        {"row_index": 0, "client_account_code": "1002", "client_account_name": "银行存款", "level": 1, "parent_key": None, "parent_row_index": None, "is_leaf": False, "is_summary": True, "ancestor_codes": [], "ancestor_names": []},
        {"row_index": 1, "client_account_code": "100201", "client_account_name": "工行", "level": 2, "parent_key": "1002", "parent_row_index": 0, "is_leaf": True, "is_summary": False, "ancestor_codes": ["1002"], "ancestor_names": ["银行存款"]},
        {"row_index": 2, "client_account_code": "100202", "client_account_name": "建行", "level": 2, "parent_key": "1002", "parent_row_index": 0, "is_leaf": True, "is_summary": False, "ancestor_codes": ["1002"], "ancestor_names": ["银行存款"]},
    ]
    tree = build_account_tree(rows_meta)
    graph = build_unique_account_graph(tree, rows_meta=rows_meta)
    parent = next(
        n for n in graph.nodes_by_key.values() if n.account_code == "1002"
    )
    children = graph.children_by_key.get(parent.node_key, [])
    assert len(children) == 2
    children_codes = sorted(
        graph.nodes_by_key[c].account_code for c in children
    )
    assert children_codes == ["100201", "100202"]


def test_build_graph_auxiliary_nodes_classified():
    """辅助核算行识别为 auxiliary，并绑定到上级 account 节点。"""
    rows_meta = [
        {"row_index": 0, "client_account_code": "1122", "client_account_name": "应收账款", "level": 1, "parent_key": None, "parent_row_index": None, "is_leaf": False, "is_summary": True, "ancestor_codes": [], "ancestor_names": []},
        {"row_index": 1, "client_account_code": "112201", "client_account_name": "应收账款-子科目", "level": 2, "parent_key": "1122", "parent_row_index": 0, "is_leaf": True, "is_summary": False, "ancestor_codes": ["1122"], "ancestor_names": ["应收账款"]},
        {"row_index": 2, "client_account_code": None, "client_account_name": "[0001] 客户A", "level": 3, "parent_key": "112201", "parent_row_index": 1, "is_leaf": True, "is_summary": False, "ancestor_codes": ["1122", "112201"], "ancestor_names": ["应收账款", "应收账款-子科目"]},
    ]
    tree = build_account_tree(rows_meta)
    graph = build_unique_account_graph(tree, rows_meta=rows_meta)
    aux = next(
        n for n in graph.nodes_by_key.values() if n.node_type == "auxiliary"
    )
    assert aux.account_code is None
    assert aux.account_name == "[0001] 客户A"
    # 辅助节点父节点是 112201（account）
    parent_key = aux.parent_node_key
    assert parent_key is not None
    parent_node = graph.nodes_by_key[parent_key]
    assert parent_node.account_code == "112201"
