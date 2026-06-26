"""pytest 会话钩子：所有测试结束后生成 anchor inheritance 报告。"""
import sys
import os

# 把 backend 加入 sys.path 以便导入 test_anchor_inheritance_regression
# 该 conftest.py 在 backend 根目录，python_path 已包含 backend
# 但 test_anchor_inheritance_regression 在 tests/ 子目录
# 引入时需要使用相对路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tests"))

try:
    from test_anchor_inheritance_regression import (
        REGRESSION_REPORT,
        _generate_regression_reports,
    )

    def pytest_sessionfinish(session, exitstatus):
        if REGRESSION_REPORT:
            paths = _generate_regression_reports()
            print(f"\n[Regression Report] Generated: {paths}")
except ImportError:
    pass
