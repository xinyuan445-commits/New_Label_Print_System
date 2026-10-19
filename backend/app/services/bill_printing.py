"""Prepare bill PDFs and register confirmed labels in the U8 test account."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from app.services.jobs import pdfs_dir
from app.services.u8_bills import barcode_account_code, get_connection_string, validate_database

if TYPE_CHECKING:
    import pyodbc

_CENT = Decimal("0.01")
_RUN_ID = re.compile(r"^[0-9a-f]{32}$")
_CONFIRM_LOCK = threading.Lock()
_MAX_LABELS = 1000


class BillPrintError(ValueError):
    """A bill or saved print run cannot be used safely."""


def _decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BillPrintError("invalid_quantity") from exc
    if not result.is_finite():
        raise BillPrintError("invalid_quantity")
    return result


def _serial() -> str:
    return datetime.now().strftime("%y%m%d%H%M%S%f") + f"{secrets.randbelow(10000):04d}"


def build_label_plan(
    *,
    bill_type: str,
    bill_number: str,
    details: list[dict[str, Any]],
    selections: list[dict[str, Any]],
    include_remainder: bool,
    username: str,
    bill_id: int | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Create PDF variables and exact legacy-style trace records per label."""
    if not selections:
        raise BillPrintError("no_lines")
    if len({item["index"] for item in selections}) != len(selections):
        raise BillPrintError("duplicate_line")
    rows: list[dict[str, str]] = []
    records: list[dict[str, Any]] = []
    serials: set[str] = set()
    account_code = barcode_account_code()
    order_type_code = "".join(character for character in bill_number if character.isalpha())
    for item in selections:
        index = item["index"]
        if not isinstance(index, int) or not 0 <= index < len(details):
            raise BillPrintError("invalid_line")
        detail = details[index]
        if item.get("detail_id") is not None and str(item["detail_id"]) != str(
            detail.get("明细ID")
        ):
            raise BillPrintError("bill_changed")
        source = _decimal(detail.get("数量"))
        if bill_type in {"XSCK", "OtherOUT", "CLCK"}:
            if source >= 0:
                raise BillPrintError("not_inbound_line")
            source = -source
        elif source <= 0:
            raise BillPrintError("not_inbound_line")
        quantity = _decimal(item["quantity"]).quantize(_CENT, rounding=ROUND_HALF_UP)
        packaging = _decimal(item["packaging"]).quantize(_CENT, rounding=ROUND_HALF_UP)
        if quantity <= 0 or packaging <= 0 or quantity > source:
            raise BillPrintError("invalid_quantity")
        full_count = int(quantity // packaging)
        if len(rows) + full_count > _MAX_LABELS:
            raise BillPrintError("too_many_labels")
        remainder = (quantity - packaging * full_count).quantize(_CENT)
        amounts = [packaging] * full_count
        if include_remainder and remainder > 0:
            amounts.append(remainder)
        if not amounts:
            raise BillPrintError("no_labels_for_line")
        if len(rows) + len(amounts) > _MAX_LABELS:
            raise BillPrintError("too_many_labels")

        code = str(detail.get("存货编码") or "").strip()
        name = str(detail.get("存货名称") or "").strip()
        batch = str(detail.get("批号") or "").strip()
        if item.get("item_code", code) != code or item.get("batch", batch) != batch:
            raise BillPrintError("bill_changed")
        if not code or "|" in code or "|" in batch:
            raise BillPrintError("invalid_item")
        warehouse_name = str(detail.get("仓库名称") or "")
        location_name = str(detail.get("货位名称") or "")
        location_code = str(detail.get("货位编码") or "")
        warehouse_code = str(detail.get("仓库编码") or "")
        unit = str(detail.get("单位") or "")
        for amount in amounts:
            serial = _serial()
            while serial in serials:
                serial = _serial()
            serials.add(serial)
            quantity_text = f"{amount:.2f}"
            barcode = f"{account_code}|{code}|{batch}|{quantity_text}|{serial}"
            now = datetime.now().astimezone()
            order_uuid = f"{serial}dyx"
            goods_uuid = f"{serial}syx"
            order_json: dict[str, Any] = {
                "documentNumber": bill_number,
                "orderType": order_type_code,
            }
            if bill_id is not None and detail.get("明细ID") is not None:
                order_json["labelPrintSource"] = {
                    "billType": bill_type,
                    "billId": bill_id,
                    "detailId": str(detail["明细ID"]),
                    "lineNumber": index + 1,
                }
            goods_json = {
                "name": name,
                "code": code,
                "CurrencyGoodsData": {},
                "inventory": {
                    "warehouse": warehouse_name,
                    "storageLocation": location_name,
                    "storageLocationCode": location_code,
                },
                "Attribute": {
                    "batchNumber": batch,
                    "productionDate": "9999-01-01",
                    "expirationDate": "9999-12-12",
                },
                "warehouseCode": warehouse_code,
                "quantity": 0.0,
            }
            records.append(
                {
                    "line_number": index + 1,
                    "order_json": order_json,
                    "goods_json": goods_json,
                    "pda_order_uuid": order_uuid,
                    "pda_goods_uuid": goods_uuid,
                    "trace_back_code": barcode,
                    "sn": serial,
                    "sum": quantity_text,
                    "user": username,
                    "time": now.isoformat(),
                }
            )
            rows.append(
                {
                    "账套名": "科米龙",
                    "单据编码": bill_number,
                    "行号": str(index + 1),
                    "物料编码": code,
                    "物料名称": name,
                    "批号": batch,
                    "数量": quantity_text,
                    "单位": unit,
                    "sn": serial,
                    "条码": barcode,
                }
            )
    return rows, records


def build_stock_label_plan(
    *,
    stock: list[dict[str, Any]],
    selections: list[dict[str, Any]],
    include_remainder: bool,
    username: str,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Plan stock labels from freshly reloaded inventory rows."""
    if not selections:
        raise BillPrintError("no_lines")
    if len({(item["source"], item["stock_id"]) for item in selections}) != len(selections):
        raise BillPrintError("duplicate_line")
    by_key = {(row["source"], int(row["stock_id"])): row for row in stock}
    details: list[dict[str, Any]] = []
    mapped: list[dict[str, Any]] = []
    for index, item in enumerate(selections):
        row = by_key.get((item["source"], item["stock_id"]))
        if row is None or row["item_code"] != item["item_code"] or row["batch"] != item["batch"]:
            raise BillPrintError("stock_changed")
        details.append(
            {
                "仓库编码": row["warehouse_code"],
                "仓库名称": row["warehouse_name"],
                "货位编码": row["location_code"],
                "货位名称": row["location_name"],
                "存货编码": row["item_code"],
                "存货名称": row["item_name"],
                "数量": row["quantity"],
                "单位": row["unit"],
                "批号": row["batch"],
            }
        )
        mapped.append(
            {
                "index": index,
                "item_code": item["item_code"],
                "batch": item["batch"],
                "quantity": item["quantity"],
                "packaging": item["packaging"],
            }
        )
    document_number = datetime.now().strftime("%Y%m%d%H")
    rows, records = build_label_plan(
        bill_type="STOCK",
        bill_number=document_number,
        details=details,
        selections=mapped,
        include_remainder=include_remainder,
        username=username,
    )
    for row, record in zip(rows, records, strict=True):
        source = by_key[
            (
                selections[int(record["line_number"]) - 1]["source"],
                selections[int(record["line_number"]) - 1]["stock_id"],
            )
        ]
        record["order_json"] = {"documentNumber": document_number, "orderType": "KC"}
        record["document_number"] = document_number
        row["单据编码"] = document_number
        row.update(
            {
                "仓库编码": str(source["warehouse_code"]),
                "仓库名称": str(source["warehouse_name"]),
                "货位编码": str(source["location_code"]),
                "货位名称": str(source["location_name"]),
                "规格型号": str(source.get("specification") or ""),
            }
        )
    return rows, records


def _run_dir() -> Path:
    path = pdfs_dir() / "bill-print-runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_path(run_id: str, suffix: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise BillPrintError("invalid_run")
    return _run_dir() / f"{run_id}.{suffix}"


def save_run(
    *,
    owner_id: int,
    template_id: int,
    bill_type: str,
    bill_number: str,
    rows: list[dict[str, str]],
    records: list[dict[str, Any]],
    pdf_bytes: bytes,
) -> str:
    run_id = uuid.uuid4().hex
    pdf_path = _run_path(run_id, "pdf")
    manifest_path = _run_path(run_id, "json")
    manifest = {
        "run_id": run_id,
        "owner_id": owner_id,
        "template_id": template_id,
        "bill_type": bill_type,
        "bill_number": bill_number,
        "created_at": datetime.now(UTC).isoformat(),
        "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "label_count": len(rows),
        "records": records,
        "rows": rows,
    }
    pdf_path.write_bytes(pdf_bytes)
    try:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    except OSError:
        pdf_path.unlink(missing_ok=True)
        raise
    return run_id


def load_run(run_id: str, *, owner_id: int) -> dict[str, Any]:
    path = _run_path(run_id, "json")
    if not path.is_file():
        raise BillPrintError("run_not_found")
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(run["created_at"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BillPrintError("invalid_run") from exc
    if run.get("run_id") != run_id or run.get("owner_id") != owner_id:
        raise BillPrintError("run_not_found")
    if created < datetime.now(UTC) - timedelta(days=30):
        raise BillPrintError("run_expired")
    pdf_path = _run_path(run_id, "pdf")
    if not pdf_path.is_file() or hashlib.sha256(pdf_path.read_bytes()).hexdigest() != run.get(
        "pdf_sha256"
    ):
        raise BillPrintError("pdf_missing")
    return cast("dict[str, Any]", run)


def print_pdf_path(run_id: str, *, owner_id: int) -> Path:
    load_run(run_id, owner_id=owner_id)
    return _run_path(run_id, "pdf")


def _write_connection_string() -> str:
    connection_string = get_connection_string()
    validate_database(connection_string, for_write=True)
    if not connection_string:
        raise BillPrintError("u8_not_configured")
    if re.search(r"(?:^|;)\s*ApplicationIntent\s*=", connection_string, re.I):
        connection_string = re.sub(
            r"(?i)(ApplicationIntent\s*=\s*)ReadOnly", r"\1ReadWrite", connection_string
        )
    else:
        connection_string += ";ApplicationIntent=ReadWrite"
    validate_database(connection_string, for_write=True)
    return connection_string


def confirm_run(run_id: str, *, owner_id: int) -> int:
    """Insert all three trace rows per label in one transaction, into 998 only."""
    import pyodbc

    with _CONFIRM_LOCK:
        run = load_run(run_id, owner_id=owner_id)
        if run.get("bill_type") == "REPRINT":
            raise BillPrintError("reprint_registration_forbidden")
        records = run["records"]
        if not records or len(records) != run.get("label_count"):
            raise BillPrintError("invalid_run")
        uuids = [record["pda_order_uuid"] for record in records]
        goods_uuids = [record["pda_goods_uuid"] for record in records]
        codes = [record["trace_back_code"] for record in records]
        if len(set(uuids)) != len(uuids) or len(set(goods_uuids)) != len(goods_uuids):
            raise BillPrintError("invalid_run")
        with closing(pyodbc.connect(_write_connection_string(), timeout=5, autocommit=False)) as cn:
            cn.timeout = 20
            cursor = cn.cursor()
            if str(cursor.execute("SELECT DB_NAME()").fetchval()).casefold() != "ufdata_998_2021":
                raise BillPrintError("u8_database_mismatch")
            existing = (
                _existing_count(cursor, "TraceBackOrder", "pdaOrderUuid", uuids),
                _existing_count(cursor, "TraceBackGoods", "pdaGoodsUuid", goods_uuids),
                _existing_count(cursor, "TraceBackOnlyCode", "traceBackCode", codes),
            )
            if existing == (len(records),) * 3:
                return len(records)
            if any(existing):
                raise BillPrintError("trace_conflict")
            try:
                for record in records:
                    timestamp = datetime.fromisoformat(record["time"]).replace(tzinfo=None)
                    cursor.execute(
                        "INSERT INTO TraceBackOrder ([json], pdaOrderUuid, orderType, [time]) "
                        "VALUES (?, ?, N'打印平台', ?)",
                        json.dumps(record["order_json"], ensure_ascii=False),
                        record["pda_order_uuid"],
                        timestamp,
                    )
                    cursor.execute(
                        "INSERT INTO TraceBackGoods ([json], pdaGoodsUuid, [time]) "
                        "VALUES (?, ?, ?)",
                        json.dumps(record["goods_json"], ensure_ascii=False),
                        record["pda_goods_uuid"],
                        timestamp,
                    )
                    cursor.execute(
                        "INSERT INTO TraceBackOnlyCode "
                        "(traceBackCode, traceBackType, pdaOrderUuid, pdaGoodsUuid, "
                        "sn, [sum], [User], [time]) "
                        "VALUES (?, N'条码', ?, ?, ?, ?, ?, ?)",
                        record["trace_back_code"],
                        record["pda_order_uuid"],
                        record["pda_goods_uuid"],
                        record["sn"],
                        record["sum"],
                        record["user"],
                        timestamp,
                    )
                cn.commit()
            except Exception:
                cn.rollback()
                raise
        return len(records)


def _existing_count(cursor: pyodbc.Cursor, table: str, column: str, values: list[str]) -> int:
    # Table and column come only from the fixed call sites above.
    placeholders = ",".join("?" for _ in values)
    return int(
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({placeholders})",  # noqa: S608
            *values,
        ).fetchval()
    )
