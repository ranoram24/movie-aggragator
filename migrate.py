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


def missing_indexes() -> list[tuple[str, str]]:
    """(table, index name) for every index the models declare and the DB lacks.

    create_all() builds indexes only alongside a table it is creating, so an
    index added to an existing model never reaches a deployed database -- the
    same gap this module already covers for columns.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    pending = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {ix["name"] for ix in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in have:
                pending.append((table.name, index.name))
    return pending


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
    """Apply the additions. Returns how many columns and indexes were added."""
    pending = missing_columns()

    if pending:
        with engine.begin() as connection:
            for table_name, column_name, column_type in pending:
                # A new column is always nullable: existing rows have no value
                # for it, so NOT NULL without a default would be rejected.
                connection.execute(
                    text(f'ALTER TABLE {table_name} ADD COLUMN "{column_name}" {column_type}')
                )
                log.info("added column %s.%s (%s)", table_name, column_name, column_type)

    # Indexes after columns, since an index may well be on a column just added.
    # Building one over a large table takes a moment, which is why this logs
    # before rather than after.
    indexes = missing_indexes()
    by_name = {
        index.name: index
        for table in Base.metadata.sorted_tables
        for index in table.indexes
    }
    for table_name, index_name in indexes:
        log.info("creating index %s on %s ...", index_name, table_name)
        by_name[index_name].create(bind=engine)
        log.info("created index %s", index_name)

    return len(pending) + len(indexes)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pending = missing_columns()
    indexes = missing_indexes()
    if not pending and not indexes:
        print("Schema is already up to date.")
    else:
        for table_name, column_name, column_type in pending:
            print(f"  column {table_name}.{column_name} {column_type}")
        for table_name, index_name in indexes:
            print(f"  index  {index_name} on {table_name}")
        run()
        print("Done.")
