"""Recover original label values by SN without creating new trace identities."""

from __future__ import annotations

import json
from contextlib import closing
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services import bill_printing, u8_bills


class ReprintError(ValueError):
    """The original label cannot be recovered unambiguously."""


def _object(raw: object) -> dict[str, Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise ReprintError("invalid_label_record") from exc
    if not isinstance(value, dict):
        raise ReprintError("invalid_label_record")
    return value


def recover(
    trace: dict[str, Any], *, sn: str, unit: str = "", specification: str = ""
) -> dict[str, Any]:
    """Use barcode quantity, since the trace sum can become a remaining balance."""
    barcode = str(trace["barcode"] or "").strip()
    parts = barcode.split("|")
    if len(parts) != 5 or parts[4] != sn or not parts[1]:
        raise ReprintError("invalid_label_record")
    try:
        quantity = Decimal(parts[3])
    except InvalidOperation as exc:
        raise ReprintError("invalid_label_record") from exc
    if not quantity.is_finite() or quantity <= 0:
        raise ReprintError("invalid_label_record")
    order = _object(trace["order_json"])
    goods = _object(trace["goods_json"])
    inventory = goods.get("inventory") or {}
    if not isinstance(inventory, dict):
        raise ReprintError("invalid_label_record")
    document_number = str(order.get("documentNumber") or "").strip()
    variables = {
        "账套名": "科米龙",
        "单据编码": document_number,
        "行号": "",
        "物料编码": parts[1],
        "物料名称": str(goods.get("name") or ""),
        "批号": parts[2],
        "数量": parts[3],
        "单位": unit,
        "sn": sn,
        "条码": barcode,
        "仓库编码": str(goods.get("warehouseCode") or ""),
        "仓库名称": str(inventory.get("warehouse") or ""),
        "货位编码": str(inventory.get("storageLocationCode") or ""),
        "货位名称": str(inventory.get("storageLocation") or ""),
        "规格型号": specification,
    }
    label: dict[str, Any] = {
        "sn": sn,
        "barcode": barcode,
        "document_number": document_number,
        "item_code": parts[1],
        "item_name": variables["物料名称"],
        "batch": parts[2],
        "quantity": parts[3],
        "unit": unit,
        "warehouse": variables["仓库名称"],
        "location": variables["货位名称"],
        "specification": specification,
        "printed_at": str(trace.get("printed_at") or ""),
        "printed_by": str(trace.get("printed_by") or ""),
        "line_number": None,
        "template_id": None,
        "variables": variables,
    }
    # The local snapshot adds values absent from historical U8 trace JSON,
    # such as the original unit, detail row number, and template choice.
    for path in sorted(bill_printing._run_dir().glob("*.json"), reverse=True):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
            if run.get("bill_type") == "REPRINT":
                continue
            for index, record in enumerate(run.get("records", [])):
                if record.get("sn") != sn or record.get("trace_back_code") != barcode:
                    continue
                label["line_number"] = int(record["line_number"])
                label["template_id"] = run.get("template_id")
                variables["行号"] = str(label["line_number"])
                snapshots = run.get("rows", [])
                if index < len(snapshots) and isinstance(snapshots[index], dict):
                    snapshot = snapshots[index]
                    if snapshot.get("sn") == sn and snapshot.get("条码") == barcode:
                        variables.update({key: str(value) for key, value in snapshot.items()})
                        label.update(
                            unit=variables["单位"],
                            item_name=variables["物料名称"],
                            specification=variables.get("规格型号", specification),
                        )
                return label
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return label


def lookup(sn: str) -> dict[str, Any]:
    import pyodbc

    connection_string = u8_bills.get_connection_string()
    u8_bills.validate_database(connection_string)
    with closing(pyodbc.connect(connection_string, timeout=5)) as cn:
        cn.timeout = 20
        cursor = cn.cursor()
        actual_database = str(cursor.execute("SELECT DB_NAME()").fetchval()).casefold()
        if actual_database != u8_bills.database_name():
            raise u8_bills.U8DatabaseMismatchError("U8 database does not match configuration")
        cursor.execute(
            "SELECT TOP (21) c.traceBackCode AS barcode, o.[json] AS order_json, "
            "g.[json] AS goods_json, o.[time] AS printed_at, c.[User] AS printed_by "
            "FROM TraceBackOnlyCode c "
            "JOIN TraceBackOrder o ON o.pdaOrderUuid = c.pdaOrderUuid "
            "JOIN TraceBackGoods g ON g.pdaGoodsUuid = c.pdaGoodsUuid "
            "WHERE c.sn = ? AND o.orderType = N'打印平台' "
            "AND c.traceBackType = N'条码' ORDER BY o.[time] ASC",
            sn,
        )
        columns = [entry[0] for entry in cursor.description]
        traces = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        if not traces:
            raise ReprintError("label_not_found")
        if len(traces) > 20 or len({str(row["barcode"]) for row in traces}) != 1:
            raise ReprintError("ambiguous_label")
        parts = str(traces[0]["barcode"] or "").split("|")
        if len(parts) != 5:
            raise ReprintError("invalid_label_record")
        item = cursor.execute(
            "SELECT inv.cInvStd, cp.cComUnitName FROM Inventory inv "
            "LEFT JOIN ComputationUnit cp ON cp.cComunitCode = inv.cComUnitCode "
            "WHERE inv.cInvCode = ?",
            parts[1],
        ).fetchone()
    return recover(
        traces[0],
        sn=sn,
        unit=str(item[1] or "") if item else "",
        specification=str(item[0] or "") if item else "",
    )
