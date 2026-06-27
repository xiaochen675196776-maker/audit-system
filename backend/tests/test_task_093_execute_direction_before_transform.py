from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORT_SERVICE = ROOT / "app" / "services" / "standard_trial_balance_import_service.py"


def test_execute_resolves_mapping_plan_before_transform_rows():
    source = IMPORT_SERVICE.read_text(encoding="utf-8")
    execute_source = source[source.index("async def execute_standard_import"):]

    resolve_index = execute_source.index("resolve_mapping_plan(")
    transform_index = execute_source.index("transform_rows(")

    assert resolve_index < transform_index
