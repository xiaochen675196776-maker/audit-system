from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGRESSION = ROOT / "tests" / "test_anchor_inheritance_regression.py"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "task_093_confirmations"


def test_real_regression_does_not_auto_pick_highest_or_auto_ignore_missing_candidates():
    source = REGRESSION.read_text(encoding="utf-8")

    assert "sorted_cands[0]" not in source
    assert "sorted(" not in source
    assert "auto ignored" not in source.lower()
    assert "ignored_unresolved_rows.append" not in source


def test_real_regression_uses_auditable_confirmation_fixtures():
    assert FIXTURE_DIR.exists()
    fixture_files = sorted(FIXTURE_DIR.glob("*.json"))
    assert len(fixture_files) >= 6
