"""Bring an existing database up to date with models.py.

SQLAlchemy's create_all() only ever creates *missing tables*. It will not add a
column to a table that already exists, so adding a field to a model silently
leaves a deployed database one column short -- and every query touching that
column then fails at runtime. The local database can just be rebuilt; the one on
the server holds real scraped data and cannot.

This adds any column the models declare and the database lacks. Deliberately
additive only: nothing here drops, renames or retypes anything, so running it
against an already-current database is a no-op and running it twice is safe.

Anything beyond adding a column -- changing a type, adding a constraint -- is
not handled and would need a real migration tool. For a schema that only ever
grows, this is enough and has no dependencies.
"""

import logging

from sqlalchemy import inspect, text

from database import Base, engine
# Importing the models registers them on Base.metadata; without this the
# metadata is empty and the function below finds nothing to do.
import models  # noqa: F401

log = logging.getLogger(__name__)

# SQLAlchemy type -> SQLite column type. SQLite is loosely typed, so this only
# needs to be approximately right.
SQLITE_TYPES = {
    "INTEGER": "INTEGER",
    "VARCHAR": "VARCHAR",
    "TEXT": "TEXT",
    "FLOAT": "FLOAT",
    "BOOLEAN": "BOOLEAN",
}


def missing_columns() -> list[tuple[str, str, str]]:
    """(table, column, type) for every column the models have and the DB lacks."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    pending = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue  # create_all handles whole new tables
        have = {c["name"] for c in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name in have:
                continue
            type_name = str(column.type).split("(")[0].upper()
            pending.append((table_name, column.name, SQLITE_TYPES.get(type_name, "VARCHAR")))
    return pending


def run() -> int:
    """Apply the additions. Returns how many columns were added."""
    pending = missing_columns()
    if not pending:
        return 0

    with engine.begin() as connection:
        for table_name, column_name, column_type in pending:
            # A new column is always nullable: existing rows have no value for
            # it, so NOT NULL without a default would be rejected outright.
            connection.execute(
                text(f'ALTER TABLE {table_name} ADD COLUMN "{column_name}" {column_type}')
            )
            log.info("added column %s.%s (%s)", table_name, column_name, column_type)
    return len(pending)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pending = missing_columns()
    if not pending:
        print("Schema is already up to date.")
    else:
        print(f"Adding {len(pending)} column(s):")
        for table_name, column_name, column_type in pending:
            print(f"  {table_name}.{column_name} {column_type}")
        run()
        print("Done.")
