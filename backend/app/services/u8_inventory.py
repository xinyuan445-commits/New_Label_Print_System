"""Read current positive stock from the U8 test account."""

from __future__ import annotations

from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.u8_bills import (
    U8DatabaseMismatchError,
    database_name,
    get_connection_string,
    validate_database,
)

_BASE_SQL = (
    Path(__file__)
    .with_name("u8_sql")
    .joinpath("inventory_stock.sql")
    .read_text(encoding="utf-8")
    .strip()
)
_COLUMNS = (
    "source, stock_id, warehouse_code, warehouse_name, location_code, location_name, "
    "item_code, item_name, specification, unit, quantity, batch"
)


def _query(
    where: str, params: list[Any], *, limit: int | None
) -> tuple[list[dict[str, Any]], bool]:
    import pyodbc

    connection_string = get_connection_string()
    validate_database(connection_string)
    select = f"SELECT TOP ({limit + 1})" if limit is not None else "SELECT"
    sql = (
        f"SELECT {_COLUMNS} FROM ({_BASE_SQL}) stock WHERE {where} "  # noqa: S608
        "ORDER BY warehouse_code, location_code, item_code, batch, source, stock_id"
    )
    if limit is not None:
        sql = sql.replace("SELECT", select, 1)
    with closing(pyodbc.connect(connection_string, timeout=5)) as cn:
        cn.timeout = 20
        cursor = cn.cursor()
        if str(cursor.execute("SELECT DB_NAME()").fetchval()).casefold() != database_name():
            raise U8DatabaseMismatchError("U8 database does not match configuration")
        cursor.execute(sql, *params)
        columns = [entry[0] for entry in cursor.description]
        fetched = cursor.fetchall()
    rows = [
        {
            key: str(value) if isinstance(value, Decimal) else (value if value is not None else "")
            for key, value in zip(columns, row, strict=True)
        }
        for row in (fetched[:limit] if limit is not None else fetched)
    ]
    return rows, limit is not None and len(fetched) > limit


def search(
    *,
    warehouse: str = "",
    location: str = "",
    item: str = "",
    batch: str = "",
    limit: int = 300,
) -> tuple[list[dict[str, Any]], bool]:
    clauses = ["1=1"]
    params: list[Any] = []
    for value, fields in (
        (warehouse, ("warehouse_code", "warehouse_name")),
        (location, ("location_code", "location_name")),
        (item, ("item_code", "item_name")),
        (batch, ("batch",)),
    ):
        if value:
            clauses.append(
                "(" + " OR ".join(f"COALESCE({field}, '') LIKE ?" for field in fields) + ")"
            )
            params.extend([f"%{value}%"] * len(fields))
    return _query(" AND ".join(clauses), params, limit=limit)


def get_selected(keys: list[tuple[str, int]]) -> list[dict[str, Any]]:
    if not keys:
        return []
    clauses = ["(source = ? AND stock_id = ?)" for _ in keys]
    params: list[Any] = [value for source, stock_id in keys for value in (source, stock_id)]
    rows, _ = _query(" OR ".join(clauses), params, limit=None)
    return rows
