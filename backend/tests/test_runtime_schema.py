"""运行期数据库结构兼容测试"""

from sqlalchemy import create_engine, inspect

from app.core.schema import ensure_runtime_schema


def test_ensure_runtime_schema_adds_extra_fields_to_existing_import_tables():
    """旧库已存在导入表时，应补齐新增的 extra_fields 列"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE journal_entries (id TEXT PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE subsidiary_ledgers (id TEXT PRIMARY KEY)")

        ensure_runtime_schema(conn)
        ensure_runtime_schema(conn)

        inspector = inspect(conn)
        journal_columns = {col["name"] for col in inspector.get_columns("journal_entries")}
        subsidiary_columns = {col["name"] for col in inspector.get_columns("subsidiary_ledgers")}

    assert "extra_fields" in journal_columns
    assert "extra_fields" in subsidiary_columns
