"""Read U8 bill headers and details using the queries from the WinForms app.

U8 is a separate SQL Server database. BarcodeLabelGen's own users, templates,
and preferences continue to live in the application's own database.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from collections.abc import Iterable
from contextlib import closing
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

BILL_TYPES: tuple[tuple[str, str], ...] = (
    ("CGDH", "采购到货单"),
    ("CGRK", "采购入库单"),
    ("XSCK", "销售出库单"),
    ("CCPRK", "产成品入库单"),
    ("OtherIN", "其他入库单"),
    ("OtherOUT", "其他出库单"),
    ("CLCK", "材料出库单"),
    ("DBD", "调拨单"),
    ("PDD", "盘点单"),
    ("XTZY", "形态转换单"),
    ("HWTZ", "货位调整单"),
)

_BILL_CODES = {code for code, _ in BILL_TYPES}
_SQL_DIR = Path(__file__).with_name("u8_sql")
_PARAM_RE = re.compile(r"@(Code|StartDate|EndDate|MainID)\b")
_DATABASE_RE = re.compile(r"(?:^|;)\s*(?:Database|Initial Catalog)\s*=\s*([^;]+)", re.I)
_ALLOWED_DATABASE = "ufdata_998_2021"
_READ_DATABASES = {_ALLOWED_DATABASE, "ufdata_008_2021"}
_COMPONENT_KEYS = ("U8_SERVER", "U8_USER", "U8_PASSWORD")
ScannedLabel = tuple[str, Decimal | None]
MovementGoods = tuple[list[ScannedLabel], object]

# Only documents with an inbound quantity need a new label. A negative
# quantity on an outbound document is a return and therefore inbound.
_PENDING_SOURCES: dict[str, str] = {
    "CGDH": "SELECT 'CGDH' AS bill_type, v.ID, v.cCode AS bill_number, v.dDate AS bill_date "
    "FROM PU_ArrivalVouch v WHERE v.dDate >= @StartDate "
    "AND v.dDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM PU_ArrivalVouchs d WHERE d.ID = v.ID AND d.iQuantity > 0)",
    "CGRK": "SELECT 'CGRK' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date "
    "FROM RdRecord01 r WHERE r.dDate >= @StartDate "
    "AND r.dDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '01' AND d.ID = r.ID "
    "AND d.iQuantity > 0)",
    "CCPRK": "SELECT 'CCPRK' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date "
    "FROM RdRecord10 r WHERE r.dDate >= @StartDate "
    "AND r.dDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '10' AND d.ID = r.ID "
    "AND d.iQuantity > 0)",
    "OtherIN": "SELECT 'OtherIN' AS bill_type, r.ID, r.cCode AS bill_number, "
    "r.dDate AS bill_date FROM RdRecord08 r WHERE r.dDate >= @StartDate "
    "AND r.dDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '08' AND d.ID = r.ID "
    "AND d.iQuantity > 0)",
    "XSCK": "SELECT 'XSCK' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date "
    "FROM RdRecord32 r WHERE r.dDate >= @StartDate "
    "AND r.dDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '32' AND d.ID = r.ID "
    "AND d.iQuantity < 0)",
    "OtherOUT": "SELECT 'OtherOUT' AS bill_type, r.ID, r.cCode AS bill_number, "
    "r.dDate AS bill_date FROM RdRecord09 r WHERE r.dDate >= @StartDate "
    "AND r.dDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '09' AND d.ID = r.ID "
    "AND d.iQuantity < 0)",
    "CLCK": "SELECT 'CLCK' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date "
    "FROM RdRecord11 r WHERE r.dDate >= @StartDate "
    "AND r.dDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '11' AND d.ID = r.ID "
    "AND d.iQuantity < 0)",
    "DBD": "SELECT 'DBD' AS bill_type, a.ID, a.cTVCode AS bill_number, "
    "a.dTVDate AS bill_date FROM TransVouch a WHERE a.dTVDate >= @StartDate "
    "AND a.dTVDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM TransVouchs d WHERE d.ID = a.ID AND d.iTVQuantity > 0)",
    "PDD": "SELECT 'PDD' AS bill_type, a.ID, a.cCVCode AS bill_number, "
    "a.dCVDate AS bill_date FROM CheckVouch a WHERE a.dCVDate >= @StartDate "
    "AND a.dCVDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM CheckVouchs d WHERE d.ID = a.ID AND d.iCVCQuantity > 0)",
    "XTZY": "SELECT 'XTZY' AS bill_type, a.ID, a.cAVCode AS bill_number, "
    "a.dAVDate AS bill_date FROM AssemVouch a WHERE a.dAVDate >= @StartDate "
    "AND a.dAVDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM AssemVouchs d WHERE d.ID = a.ID "
    "AND d.bAVType = N'转换后' AND d.iAVQuantity > 0)",
    "HWTZ": "SELECT 'HWTZ' AS bill_type, a.ID, a.cVouchCode AS bill_number, "
    "a.dDate AS bill_date FROM AdjustPVouch a WHERE a.dDate >= @StartDate "
    "AND a.dDate < DATEADD(day, 1, @EndDate) "
    "AND EXISTS (SELECT 1 FROM AdjustPVouchs d WHERE d.ID = a.ID AND d.iQuantity > 0)",
}


class U8NotConfiguredError(RuntimeError):
    """The U8 connection has not been supplied to the web process."""


class UnsupportedBillTypeError(ValueError):
    """The requested bill has no supported query."""


class U8DatabaseMismatchError(RuntimeError):
    """Prevent accidental access to another U8 account set."""


def barcode_account_code() -> str:
    """The PDA barcode account segment is independent of the test database name."""
    value = os.environ.get("U8_BARCODE_ACCOUNT_CODE", "008").strip()
    if not re.fullmatch(r"\d{3}", value):
        raise ValueError("U8_BARCODE_ACCOUNT_CODE must be three digits")
    return value


def is_configured() -> bool:
    if any(key in os.environ for key in _COMPONENT_KEYS):
        return all(os.environ.get(key, "").strip() for key in _COMPONENT_KEYS)
    return bool(os.environ.get("U8_ODBC_CONNECTION_STRING", "").strip())


def database_name() -> str:
    value = os.environ.get("U8_DATABASE", _ALLOWED_DATABASE).strip().casefold()
    if value not in _READ_DATABASES:
        raise U8DatabaseMismatchError("Unsupported U8 database")
    return value


def query_only() -> bool:
    return database_name() != _ALLOWED_DATABASE


def get_connection_string() -> str:
    """Build a query connection without putting a password in code."""
    if not any(key in os.environ for key in _COMPONENT_KEYS):
        return os.environ.get("U8_ODBC_CONNECTION_STRING", "").strip()
    if not is_configured():
        return ""

    import pyodbc

    driver = os.environ.get("U8_ODBC_DRIVER", "").strip()
    if not driver:
        installed = pyodbc.drivers()
        driver = next(
            (
                name
                for name in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
                if name in installed
            ),
            "",
        )
    if not driver:
        raise RuntimeError("Microsoft SQL Server ODBC driver is not installed")
    server = os.environ["U8_SERVER"].strip()
    user = os.environ["U8_USER"].strip()
    if any(char in value for value in (driver, server, user) for char in ";{}"):
        raise ValueError("U8 connection settings contain an invalid character")
    password = os.environ["U8_PASSWORD"].replace("}", "}}")
    return (
        f"Driver={{{driver}}};Server={server};Database={database_name()};"
        f"Uid={user};Pwd={{{password}}};Encrypt=yes;TrustServerCertificate=yes;"
        "ApplicationIntent=ReadOnly"
    )


def validate_database(connection_string: str, *, for_write: bool = False) -> None:
    expected = _ALLOWED_DATABASE if for_write else database_name()
    databases = [
        match.strip().strip("{} ").casefold() for match in _DATABASE_RE.findall(connection_string)
    ]
    # A DSN or duplicate Database key may override the visible catalog.
    if (
        len(databases) != 1
        or databases[0] != expected
        or re.search(r"(?:^|;)\s*DSN\s*=", connection_string, re.I)
    ):
        raise U8DatabaseMismatchError(f"Expected {expected}")


def load_query(bill_type: str, kind: str) -> str:
    if bill_type not in _BILL_CODES:
        raise UnsupportedBillTypeError(bill_type)
    if kind not in {"main", "detail"}:
        raise ValueError(kind)
    return (_SQL_DIR / f"{bill_type.lower()}_{kind}.sql").read_text(encoding="utf-8")


def bind_query(sql: str, values: dict[str, Any]) -> tuple[str, list[Any]]:
    """Convert the legacy named parameters to pyodbc's positional binding."""
    parameters: list[Any] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if isinstance(values[key], list):
            parameters.extend(values[key])
            return ",".join("?" for _ in values[key])
        parameters.append(values[key])
        return "?"

    return _PARAM_RE.sub(replace, sql), parameters


def _json_value(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _fetch(sql: str, values: dict[str, Any], *, limit: int) -> tuple[list[dict[str, Any]], bool]:
    connection_string = get_connection_string()
    if not connection_string:
        raise U8NotConfiguredError
    validate_database(connection_string)

    # Import only when a live U8 query is made; template editing works without
    # SQL Server or its ODBC driver during setup and tests.
    import pyodbc

    query, params = bind_query(sql, values)
    with closing(pyodbc.connect(connection_string, timeout=5)) as connection:
        connection.timeout = 20
        cursor = connection.cursor()
        cursor.execute(query, *params)
        columns = [column[0] for column in cursor.description]
        result = cursor.fetchmany(limit + 1)
    rows = [
        dict(zip(columns, (_json_value(value) for value in row), strict=True))
        for row in result[:limit]
    ]
    return rows, len(result) > limit


def list_bills(
    bill_type: str, *, code: str, start_date: date, end_date: date
) -> tuple[list[dict[str, Any]], bool]:
    sql = load_query(bill_type, "main")
    return _fetch(
        sql,
        {
            "Code": f"%{code}%" if code else None,
            "StartDate": start_date,
            "EndDate": end_date,
        },
        limit=200,
    )


def list_details(bill_type: str, main_id: int) -> tuple[list[dict[str, Any]], bool]:
    sql = load_query(bill_type, "detail")
    return _fetch(sql, {"MainID": main_id}, limit=1000)


def pending_details_query(bill_type: str) -> str:
    sql = load_query(bill_type, "detail")
    sql = re.sub(r"ORDER BY\s+[ab]\.autoid\s*;?\s*$", "", sql, flags=re.I)
    sql = sql.replace("a.ID = @MainID", "a.ID IN (@MainID)")
    return sql + " ORDER BY 单据ID, 明细ID"


def _pending_details(
    candidates: list[dict[str, Any]],
) -> tuple[dict[tuple[str, int], list[dict[str, Any]]], bool]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    truncated = False
    for bill_type, _name in BILL_TYPES:
        ids = list(
            dict.fromkeys(int(row["ID"]) for row in candidates if row["bill_type"] == bill_type)
        )
        for offset in range(0, len(ids), 100):
            rows, cut = _fetch(
                pending_details_query(bill_type),
                {"MainID": ids[offset : offset + 100]},
                limit=100000,
            )
            truncated = truncated or cut
            for row in rows:
                grouped[(bill_type, int(row["单据ID"]))].append(row)
    return grouped, truncated


def pending_bills_query(bill_types: list[str]) -> str:
    """Build the recent inbound candidate query from trusted U8 sources."""
    if any(code not in _BILL_CODES for code in bill_types):
        raise UnsupportedBillTypeError("unknown bill type")
    sources = [
        _PENDING_SOURCES[code] for code in dict.fromkeys(bill_types) if code in _PENDING_SOURCES
    ]
    if not sources:
        raise ValueError("no inbound bill types")
    return (
        "WITH recent AS (" + " UNION ALL ".join(sources) + ") "  # noqa: S608
        "SELECT bill_type, ID, bill_number AS 单据号, bill_date AS 单据日期 FROM recent "
        "ORDER BY bill_date DESC, bill_number DESC"
    )


def _trace_json(raw: object) -> dict[str, Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _movement_group(
    barcodes: list[ScannedLabel], moved_raw: object
) -> tuple[Decimal | None, Decimal | None, Decimal | None, str]:
    """Compare all labels scanned for one PDA goods row with its moved quantity."""
    try:
        originals = [Decimal(barcode.split("|")[3]) for barcode, _remaining in barcodes]
        moved = Decimal(str(moved_raw))
    except (IndexError, ValueError, ArithmeticError):
        return None, None, None, "待核对"
    if not moved.is_finite() or any(not value.is_finite() for value in originals):
        return None, None, None, "待核对"
    original = sum(originals, Decimal(0))
    remaining_values = [quantity for _barcode, quantity in barcodes]
    if any(quantity is None or not quantity.is_finite() for quantity in remaining_values):
        return original, None, moved, "待核对"
    remaining = sum((quantity for quantity in remaining_values if quantity is not None), Decimal(0))
    if (
        not originals
        or any(quantity <= 0 for quantity in originals)
        or remaining <= 0
        or remaining > original
        or moved <= 0
    ):
        return original, remaining, moved, "待核对"
    if abs(remaining - moved) <= Decimal("0.001"):
        return original, remaining, moved, "整托"
    if remaining > moved:
        return original, remaining, moved, "零散"
    return original, remaining, moved, "待核对"


def _movement_reason(label_rows: list[MovementGoods]) -> str | None:
    """Only complete scanned goods groups can move without a new label."""
    if not label_rows:
        return "无PDA标签记录"
    uncertain = False
    for barcodes, moved_raw in label_rows:
        _original, _remaining, _moved, status = _movement_group(barcodes, moved_raw)
        if status == "零散":
            return "零散需补打"
        if status == "待核对":
            uncertain = True
    return "标签数量待核对" if uncertain else None


def list_movement_labels(bill_type: str, bill_number: str) -> list[dict[str, str]]:
    """Show the PDA quantities used to classify a transfer or position adjustment."""
    if bill_type not in {"DBD", "HWTZ"}:
        raise UnsupportedBillTypeError(bill_type)
    _printed, labels = _read_trace_state([{"bill_type": bill_type, "单据号": bill_number}])
    result: list[dict[str, str]] = []
    for barcodes, moved_raw in labels.get((bill_type, bill_number), []):
        parts = barcodes[0][0].split("|") if barcodes else []
        item_code = parts[1] if len(parts) > 1 else ""
        batch = parts[2] if len(parts) > 2 else ""
        original, remaining, moved, status = _movement_group(barcodes, moved_raw)
        original_text = str(original) if original is not None else ""
        remaining_text = str(remaining) if remaining is not None else ""
        moved_text = str(moved) if moved is not None else str(moved_raw or "")
        result.append(
            {
                "存货编码": item_code,
                "批号": batch,
                "原标签数量": original_text,
                "标签剩余": remaining_text,
                "本次数量": moved_text,
                "状态": status,
            }
        )
    return result


def _remaining_before_events(
    events: Iterable[tuple[int, str, object, str | None]],
) -> dict[int, Decimal | None]:
    """Use prior material/shipment consumption to find a scanned label's remainder."""
    result: dict[int, Decimal | None] = {}
    current_code = ""
    consumed = Decimal(0)
    uncertain = False
    for code_id, barcode, delta_raw, kind in events:
        barcode = str(barcode or "")
        if barcode != current_code:
            current_code = barcode
            consumed = Decimal(0)
            uncertain = False
        try:
            original = Decimal(barcode.split("|")[3])
        except (IndexError, ValueError, ArithmeticError):
            original = None
        result[int(code_id)] = (
            original - consumed if original is not None and not uncertain else None
        )
        if kind in {"发货单", "材料出库"}:
            try:
                consumed -= Decimal(str(delta_raw))
            except (ValueError, ArithmeticError):
                uncertain = True
        elif kind not in {"打印平台", "调拨单", "货位调整单"}:
            try:
                if Decimal(str(delta_raw)) != 0:
                    uncertain = True
            except (ValueError, ArithmeticError):
                uncertain = True
    return result


def _read_trace_state(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[MovementGoods]]]:
    """Read print-platform records and PDA scans; never write to U8."""
    connection_string = get_connection_string()
    validate_database(connection_string)
    import pyodbc

    movement_numbers = {
        (str(row["bill_type"]), str(row["单据号"]))
        for row in candidates
        if row["bill_type"] in {"DBD", "HWTZ"}
    }
    printed: list[dict[str, Any]] = []
    print_orders: dict[str, dict[str, Any]] = {}
    numbers = {str(row["单据号"]) for row in candidates}
    order_ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    with closing(pyodbc.connect(connection_string, timeout=5)) as connection:
        connection.timeout = 20
        cursor = connection.cursor()
        orders = cursor.execute(
            "SELECT [json], pdaOrderUuid, CAST(orderType AS nvarchar(100)) "
            "FROM TraceBackOrder WHERE CAST(orderType AS nvarchar(100)) "
            "IN (N'打印平台', N'调拨单', N'货位调整单')"
        )
        for raw, uuid, kind in orders:
            data = _trace_json(raw)
            if kind == "打印平台":
                number = data.get("documentNumber")
                if number and str(number) in numbers and uuid:
                    print_orders[str(uuid)] = data
                continue
            bill_type = "DBD" if kind == "调拨单" else "HWTZ"
            currency = data.get("CurrencyOrderData")
            u8_data = currency.get("U8") if isinstance(currency, dict) else None
            number = u8_data.get("uploadErpCode") if isinstance(u8_data, dict) else None
            key = (bill_type, str(number or ""))
            if key in movement_numbers and uuid:
                order_ids[key].append(str(uuid))

        grouped: dict[tuple[str, str, str, str], tuple[list[tuple[str, int]], object]] = {}
        print_uuids = list(print_orders)
        for offset in range(0, len(print_uuids), 200):
            batch = print_uuids[offset : offset + 200]
            placeholders = ",".join("?" for _ in batch)
            query = (
                "SELECT c.pdaOrderUuid, c.traceBackCode, c.sn, g.[json] "  # noqa: S608
                "FROM TraceBackOnlyCode c LEFT JOIN TraceBackGoods g "
                "ON g.pdaGoodsUuid = c.pdaGoodsUuid "
                f"WHERE c.pdaOrderUuid IN ({placeholders})"
            )
            for uuid, barcode, sn, raw_goods in cursor.execute(query, *batch):
                printed.append(
                    {
                        "order": print_orders[str(uuid)],
                        "goods": _trace_json(raw_goods),
                        "barcode": str(barcode or ""),
                        "sn": str(sn or ""),
                    }
                )
        uuid_to_key = {uuid: key for key, uuids in order_ids.items() for uuid in uuids}
        uuids = list(uuid_to_key)
        for offset in range(0, len(uuids), 200):
            batch = uuids[offset : offset + 200]
            placeholders = ",".join("?" for _ in batch)
            query = (
                "SELECT c.pdaOrderUuid, c.pdaGoodsUuid, c.id, c.traceBackCode, g.[json] "  # noqa: S608
                "FROM TraceBackOnlyCode c LEFT JOIN TraceBackGoods g "
                "ON g.pdaGoodsUuid = c.pdaGoodsUuid "
                f"WHERE c.pdaOrderUuid IN ({placeholders})"
            )
            for uuid, goods_uuid, code_id, barcode, raw_goods in cursor.execute(query, *batch):
                goods = _trace_json(raw_goods)
                bill_key = uuid_to_key[str(uuid)]
                group_key = (*bill_key, str(uuid), str(goods_uuid or ""))
                if group_key not in grouped:
                    grouped[group_key] = ([], goods.get("quantity"))
                scan = (str(barcode or ""), int(code_id))
                if scan not in grouped[group_key][0]:
                    grouped[group_key][0].append(scan)

        scanned_codes = list({code for rows, _moved in grouped.values() for code, _id in rows})
        remaining_by_id: dict[int, Decimal | None] = {}
        for offset in range(0, len(scanned_codes), 100):
            batch = scanned_codes[offset : offset + 100]
            placeholders = ",".join("?" for _ in batch)
            query = (
                "SELECT c.id, c.traceBackCode, c.[sum], "  # noqa: S608
                "CAST(o.orderType AS nvarchar(100)) "
                "FROM TraceBackOnlyCode c LEFT JOIN TraceBackOrder o "
                "ON o.pdaOrderUuid = c.pdaOrderUuid "
                f"WHERE c.traceBackCode IN ({placeholders}) "
                "ORDER BY c.traceBackCode, c.[time], c.id"
            )
            remaining_by_id.update(_remaining_before_events(cursor.execute(query, *batch)))

        labels: dict[tuple[str, str], list[MovementGoods]] = defaultdict(list)
        for (bill_type, number, _order_uuid, _goods_uuid), (rows, moved) in grouped.items():
            scans = [(code, remaining_by_id.get(code_id)) for code, code_id in rows]
            labels[(bill_type, number)].append((scans, moved))
    return printed, labels


def list_pending_bills(
    bill_types: list[str], *, start_date: date, end_date: date, limit: int = 100
) -> tuple[list[dict[str, Any]], int, bool]:
    """Retain documents with unprinted detail quantities or ambiguous trace matches."""
    if any(code not in _BILL_CODES for code in bill_types):
        raise UnsupportedBillTypeError("unknown bill type")
    if not any(code in _PENDING_SOURCES for code in bill_types):
        return [], 0, False
    candidates, candidate_truncated = _fetch(
        pending_bills_query(bill_types),
        {"StartDate": start_date, "EndDate": end_date},
        limit=5000,
    )
    if not candidates:
        return [], 0, False
    printed, movement_labels = _read_trace_state(candidates)
    details, detail_truncated = _pending_details(candidates)
    from app.services.u8_pending import calculate_progress

    progress = calculate_progress(
        candidates, details, printed, movement_labels, legacy_scope_complete=not candidate_truncated
    )
    pending: list[dict[str, Any]] = []
    for row in candidates:
        lines = progress.get((str(row["bill_type"]), int(row["ID"])), [])
        waiting = [
            line
            for line in lines
            if Decimal(line["待打印数量"]) > 0 or line["打印状态"] == "待核对"
        ]
        if not waiting and not detail_truncated:
            continue
        review = not lines or any(line["打印状态"] == "待核对" for line in waiting)
        partial = any(Decimal(line["已打印数量"]) > 0 for line in lines)
        reason = "待核对" if review or detail_truncated else "部分打印" if partial else "待打印"
        pending.append({**row, "原因": reason, "待打印明细数": len(waiting)})
    return (
        pending[:limit],
        len(pending),
        candidate_truncated or detail_truncated or len(pending) > limit,
    )


def list_pending_details(
    bill_type: str, main_id: int, bill_number: str
) -> tuple[list[dict[str, Any]], bool]:
    today = date.today()
    sql = pending_bills_query([code for code, _name in BILL_TYPES]).replace(
        "ORDER BY bill_date", "WHERE bill_number = @Code ORDER BY bill_date"
    )
    peers, cut = _fetch(
        sql,
        {"StartDate": today - timedelta(days=29), "EndDate": today, "Code": bill_number},
        limit=5000,
    )
    if not any(row["bill_type"] == bill_type and int(row["ID"]) == main_id for row in peers):
        raise ValueError("bill_not_pending_candidate")
    details, truncated = list_details(bill_type, main_id)
    printed, movement = _read_trace_state(peers)
    from app.services.u8_pending import calculate_progress

    key = (bill_type, main_id)
    progress = calculate_progress(
        peers, {key: details}, printed, movement, legacy_scope_complete=not cut
    )
    return progress[key], cut or truncated
