from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORT_SERVICE = ROOT / "app" / "services" / "standard_trial_balance_import_service.py"
INHERITANCE_SERVICE = ROOT / "app" / "services" / "account_mapping_inheritance_service.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_execute_has_no_independent_propagate_and_no_null_strong_signal():
    source = _source(IMPORT_SERVICE)

    assert "async def _propagate" not in source
    assert "strong_direct_signal=None" not in source


def test_analyze_and_execute_share_resolve_mapping_plan_entrypoint():
    inheritance_source = _source(INHERITANCE_SERVICE)
    import_source = _source(IMPORT_SERVICE)

    assert "async def resolve_mapping_plan(" in inheritance_source
    assert "resolve_mapping_plan(" in import_source
    assert "build_mapping_plan as build_anchor_mapping_plan" not in import_source
