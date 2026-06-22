"""运行期数据库结构兼容处理"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


EXTRA_FIELDS_TABLES = ("journal_entries", "subsidiary_ledgers")


def ensure_runtime_schema(conn: Connection) -> None:
    """补齐 create_all 不会修改的已存在表字段。"""
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    for table_name in EXTRA_FIELDS_TABLES:
        if table_name not in existing_tables:
            continue
        columns = {col["name"] for col in inspector.get_columns(table_name)}
        if "extra_fields" in columns:
            continue
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN extra_fields JSON"))
