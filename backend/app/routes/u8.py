"""U8 bill discovery, read-only queries, and personal bill shortcuts."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, Response, jsonify, request, send_file
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import delete, select

from app.api_helpers import validation_error_response
from app.db.session import get_session
from app.models.bill_favorite import BillFavorite
from app.services import (
    bill_printing,
    client_label_print,
    label_reprinting,
    u8_bills,
    u8_inventory,
)
from app.services import templates as templates_svc
from app.services.batch_render import render_batch_pdf

u8_bp = Blueprint("u8", __name__)
_LOG = logging.getLogger(__name__)
_BILL_CODES = {code for code, _ in u8_bills.BILL_TYPES}


class BillSearch(BaseModel):
    bill_type: str
    code: str = Field(default="", max_length=100)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def check_dates(self) -> BillSearch:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class FavoritesRequest(BaseModel):
    bill_types: list[str] = Field(max_length=8)

    @model_validator(mode="after")
    def check_unique(self) -> FavoritesRequest:
        if len(set(self.bill_types)) != len(self.bill_types):
            raise ValueError("bill_types must be unique")
        return self


class PrintLine(BaseModel):
    index: int = Field(ge=0)
    detail_id: str | None = Field(default=None, max_length=100)
    item_code: str = Field(min_length=1, max_length=200)
    batch: str = Field(default="", max_length=200)
    quantity: Decimal = Field(gt=0)
    packaging: Decimal = Field(gt=0)


class PrintBillRequest(BaseModel):
    bill_type: str
    bill_id: int = Field(gt=0)
    bill_number: str = Field(min_length=1, max_length=100)
    bill_date: date
    template_id: int = Field(gt=0)
    printer: str = Field(min_length=1, max_length=255)
    lines: list[PrintLine] = Field(min_length=1, max_length=1000)
    include_remainder: bool = True
    pending_only: bool = False


class StockPrintLine(BaseModel):
    source: str
    stock_id: int = Field(gt=0)
    item_code: str = Field(min_length=1, max_length=200)
    batch: str = Field(default="", max_length=200)
    quantity: Decimal = Field(gt=0)
    packaging: Decimal = Field(gt=0)


class PrintStockRequest(BaseModel):
    template_id: int = Field(gt=0)
    printer: str = Field(min_length=1, max_length=255)
    lines: list[StockPrintLine] = Field(min_length=1, max_length=100)
    include_remainder: bool = True


class SerialLookup(BaseModel):
    sn: str = Field(min_length=1, max_length=100, pattern=r"^[^\s|]+$")


class ReprintRequest(SerialLookup):
    template_id: int = Field(gt=0)
    printer: str = Field(default="", max_length=255)
    copies: int = Field(default=1, ge=1, le=100)


@u8_bp.get("/u8/reprint")
@login_required
def find_reprint_label() -> ResponseReturnValue:
    try:
        payload = SerialLookup(sn=request.args.get("sn", "").strip())
    except ValidationError as exc:
        return validation_error_response(exc)
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    try:
        label = label_reprinting.lookup(payload.sn)
    except label_reprinting.ReprintError as exc:
        return jsonify({"error": str(exc)}), 404 if str(exc) == "label_not_found" else 409
    except Exception as exc:  # noqa: BLE001 — optional database driver errors
        return _query_error(exc)
    return jsonify({"label": label})


def _reprint_label(*, preview: bool) -> ResponseReturnValue:
    if not preview and u8_bills.query_only():
        return jsonify({"error": "u8_read_only"}), 403
    try:
        payload = ReprintRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return validation_error_response(exc)
    if not preview and not payload.printer.strip():
        return jsonify({"error": "printer_not_found"}), 400
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    session = get_session()
    try:
        label = label_reprinting.lookup(payload.sn)
        template = templates_svc.get(
            session, payload.template_id, requesting_user_id=current_user.id
        )
    except label_reprinting.ReprintError as exc:
        return jsonify({"error": str(exc)}), 404 if str(exc) == "label_not_found" else 409
    except templates_svc.TemplateNotFoundError:
        return jsonify({"error": "template_not_found"}), 404
    except templates_svc.TemplateAccessError:
        return jsonify({"error": "forbidden"}), 403
    except Exception as exc:  # noqa: BLE001 — optional database driver errors
        return _query_error(exc)
    from app.routes.generate import _resolve_asset_factory

    rows = [dict(label["variables"]) for _ in range(payload.copies)]
    records = [
        {
            "sn": label["sn"],
            "trace_back_code": label["barcode"],
            "line_number": label["line_number"] or 1,
            "document_number": label["document_number"] or "补打",
        }
        for _ in rows
    ]
    try:
        resolver = _resolve_asset_factory(template)
        pdf_bytes = render_batch_pdf(
            dict(template.canvas_data or {}),
            rows,
            width_mm=float(template.width_mm),
            height_mm=float(template.height_mm),
            resolve_asset=resolver,
        )
        if preview:
            response = Response(pdf_bytes, mimetype="application/pdf")
            response.headers["Content-Disposition"] = 'inline; filename="reprint-preview.pdf"'
            response.headers["Cache-Control"] = "no-store"
            return response
        prepared = client_label_print.prepare(
            owner_id=current_user.id,
            template=template,
            bill_type="REPRINT",
            bill_number=label["document_number"] or "补打",
            printer=payload.printer,
            rows=rows,
            records=records,
            pdf_bytes=pdf_bytes,
        )
    except bill_printing.BillPrintError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:  # noqa: BLE001 — renderer and storage failures
        _LOG.exception("Label reprint preparation failed")
        return jsonify({"error": "print_failed"}), 500
    return jsonify(prepared)


@u8_bp.post("/u8/reprint/preview")
@login_required
def preview_reprint_label() -> ResponseReturnValue:
    return _reprint_label(preview=True)


@u8_bp.post("/u8/reprint")
@login_required
def print_reprint_label() -> ResponseReturnValue:
    return _reprint_label(preview=False)


@u8_bp.get("/u8/stock")
@login_required
def search_stock() -> ResponseReturnValue:
    filters = {
        key: request.args.get(key, "").strip() for key in ("warehouse", "location", "item", "batch")
    }
    if any(len(value) > 100 for value in filters.values()):
        return jsonify({"error": "invalid_filter"}), 400
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    try:
        rows, truncated = u8_inventory.search(
            warehouse=filters["warehouse"],
            location=filters["location"],
            item=filters["item"],
            batch=filters["batch"],
        )
    except Exception as exc:  # noqa: BLE001 — driver-specific errors
        return _query_error(exc)
    return jsonify({"stock": rows, "truncated": truncated})


@u8_bp.post("/u8/stock/print")
@login_required
def print_stock() -> ResponseReturnValue:
    if u8_bills.query_only():
        return jsonify({"error": "u8_read_only"}), 403
    try:
        payload = PrintStockRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return validation_error_response(exc)
    if any(line.source not in {"current", "position"} for line in payload.lines):
        return jsonify({"error": "invalid_stock"}), 400
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    session = get_session()
    try:
        template = templates_svc.get(
            session, payload.template_id, requesting_user_id=current_user.id
        )
    except templates_svc.TemplateNotFoundError:
        return jsonify({"error": "template_not_found"}), 404
    except templates_svc.TemplateAccessError:
        return jsonify({"error": "forbidden"}), 403
    try:
        stock = u8_inventory.get_selected([(line.source, line.stock_id) for line in payload.lines])
        rows, records = bill_printing.build_stock_label_plan(
            stock=stock,
            selections=[line.model_dump() for line in payload.lines],
            include_remainder=payload.include_remainder,
            username=str(current_user.email),
        )
    except bill_printing.BillPrintError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 — driver-specific errors
        return _query_error(exc)

    from app.routes.generate import _resolve_asset_factory

    try:
        resolver = _resolve_asset_factory(template)
        pdf_bytes = render_batch_pdf(
            dict(template.canvas_data or {}),
            rows,
            width_mm=float(template.width_mm),
            height_mm=float(template.height_mm),
            resolve_asset=resolver,
        )
        prepared = client_label_print.prepare(
            owner_id=current_user.id,
            template=template,
            bill_type="STOCK",
            bill_number=records[0]["document_number"],
            printer=payload.printer,
            rows=rows,
            records=records,
            pdf_bytes=pdf_bytes,
        )
    except bill_printing.BillPrintError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:  # noqa: BLE001 — renderer and storage failures
        _LOG.exception("Stock print preparation failed")
        return jsonify({"error": "print_failed"}), 500
    return jsonify(prepared)


def _favorites() -> list[str]:
    rows = get_session().scalars(
        select(BillFavorite)
        .where(BillFavorite.user_id == current_user.id)
        .order_by(BillFavorite.position)
    )
    return [row.bill_type for row in rows]


@u8_bp.get("/u8/bill-types")
@login_required
def bill_types() -> ResponseReturnValue:
    return jsonify(
        {
            "bill_types": [{"code": code, "name": name} for code, name in u8_bills.BILL_TYPES],
            "favorites": _favorites(),
            "configured": u8_bills.is_configured(),
            "barcode_account_code": u8_bills.barcode_account_code(),
            "query_only": u8_bills.query_only(),
        }
    )


@u8_bp.get("/u8/pending-bills")
@login_required
def pending_bills() -> ResponseReturnValue:
    today = date.today()
    start = today - timedelta(days=29)
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    try:
        rows, total, truncated = u8_bills.list_pending_bills(
            [code for code, _ in u8_bills.BILL_TYPES], start_date=start, end_date=today
        )
    except Exception as exc:  # noqa: BLE001 — driver-specific errors are optional at import time
        return _query_error(exc)
    return jsonify({"bills": rows, "total": total, "truncated": truncated})


@u8_bp.get("/u8/pda-labels")
@login_required
def pda_labels() -> ResponseReturnValue:
    bill_type = request.args.get("bill_type", "")
    bill_number = request.args.get("bill_number", "").strip()
    if bill_type not in {"DBD", "HWTZ"} or not bill_number or len(bill_number) > 100:
        return jsonify({"error": "invalid_bill"}), 400
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    try:
        labels = u8_bills.list_movement_labels(bill_type, bill_number)
    except Exception as exc:  # noqa: BLE001 — driver-specific errors are optional at import time
        return _query_error(exc)
    return jsonify({"labels": labels})


@u8_bp.post("/u8/print")
@login_required
def print_bill() -> ResponseReturnValue:
    """Prepare labels for dispatch on the browser computer."""
    if u8_bills.query_only():
        return jsonify({"error": "u8_read_only"}), 403
    try:
        payload = PrintBillRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return validation_error_response(exc)
    if payload.bill_type not in _BILL_CODES:
        return jsonify({"error": "unsupported_bill_type"}), 400
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    session = get_session()
    try:
        template = templates_svc.get(
            session, payload.template_id, requesting_user_id=current_user.id
        )
    except templates_svc.TemplateNotFoundError:
        return jsonify({"error": "template_not_found"}), 404
    except templates_svc.TemplateAccessError:
        return jsonify({"error": "forbidden"}), 403
    try:
        headers, _ = u8_bills.list_bills(
            payload.bill_type,
            code=payload.bill_number,
            start_date=payload.bill_date,
            end_date=payload.bill_date,
        )
        if not any(
            int(row["ID"]) == payload.bill_id and str(row["单据号"]) == payload.bill_number
            for row in headers
        ):
            return jsonify({"error": "bill_not_found"}), 404
        if payload.pending_only:
            details, truncated = u8_bills.list_pending_details(
                payload.bill_type, payload.bill_id, payload.bill_number
            )
            if truncated:
                return jsonify({"error": "bill_changed"}), 409
            for line in payload.lines:
                if (
                    line.index >= len(details)
                    or details[line.index]["打印状态"] == "待核对"
                    or line.quantity > Decimal(details[line.index]["待打印数量"])
                ):
                    return jsonify({"error": "print_progress_changed"}), 409
        else:
            details, _ = u8_bills.list_details(payload.bill_type, payload.bill_id)
        rows, records = bill_printing.build_label_plan(
            bill_type=payload.bill_type,
            bill_number=payload.bill_number,
            details=details,
            selections=[line.model_dump() for line in payload.lines],
            include_remainder=payload.include_remainder,
            username=str(current_user.email),
            bill_id=payload.bill_id,
        )
    except bill_printing.BillPrintError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 — optional SQL Server driver errors
        return _query_error(exc)

    from app.routes.generate import _resolve_asset_factory

    try:
        pdf_bytes = render_batch_pdf(
            dict(template.canvas_data or {}),
            rows,
            width_mm=float(template.width_mm),
            height_mm=float(template.height_mm),
            resolve_asset=_resolve_asset_factory(template),
        )
        prepared = client_label_print.prepare(
            owner_id=current_user.id,
            template=template,
            bill_type=payload.bill_type,
            bill_number=payload.bill_number,
            printer=payload.printer,
            rows=rows,
            records=records,
            pdf_bytes=pdf_bytes,
        )
    except bill_printing.BillPrintError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:  # noqa: BLE001 — renderer and storage failures
        _LOG.exception("Bill print preparation failed")
        return jsonify({"error": "print_failed"}), 500
    return jsonify(prepared)


@u8_bp.get("/u8/print/<run_id>/bundle")
@login_required
def client_print_bundle(run_id: str) -> ResponseReturnValue:
    if u8_bills.query_only():
        return jsonify({"error": "u8_read_only"}), 403
    try:
        path = client_label_print.bundle_path(run_id, current_user.id)
    except bill_printing.BillPrintError as exc:
        return jsonify({"error": str(exc)}), 404
    response = send_file(path, mimetype="application/zip", conditional=False)
    response.headers["Cache-Control"] = "no-store"
    return response


@u8_bp.get("/u8/print/<run_id>/pdf/<filename>")
@login_required
def browser_print_pdf(run_id: str, filename: str) -> ResponseReturnValue:
    if u8_bills.query_only():
        return jsonify({"error": "u8_read_only"}), 403
    try:
        path = bill_printing.print_pdf_path(run_id, owner_id=current_user.id)
    except bill_printing.BillPrintError as exc:
        return jsonify({"error": str(exc)}), 404
    response = send_file(
        path,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=filename,
        conditional=False,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@u8_bp.post("/u8/print/<run_id>/complete")
@login_required
def complete_client_print(run_id: str) -> ResponseReturnValue:
    if u8_bills.query_only():
        return jsonify({"error": "u8_read_only"}), 403
    try:
        result = client_label_print.complete(
            run_id,
            owner_id=current_user.id,
            session=get_session(),
            acknowledgment=request.get_json(silent=True) or {},
        )
    except bill_printing.BillPrintError as exc:
        return jsonify({"error": str(exc)}), 409
    except Exception:  # noqa: BLE001 — client already accepted; never resend on failure
        _LOG.exception("Client print completed but registration failed")
        return jsonify(
            {"error": "trace_registration_failed", "printed": True, "run_id": run_id}
        ), 500
    return jsonify(result)


@u8_bp.post("/u8/print/<run_id>/register")
@login_required
def register_bill_print(run_id: str) -> ResponseReturnValue:
    if u8_bills.query_only():
        return jsonify({"error": "u8_read_only"}), 403
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    try:
        if client_label_print._state_path(run_id).is_file():
            result = client_label_print.complete(
                run_id,
                owner_id=current_user.id,
                session=get_session(),
                acknowledgment=None,
            )
            count = result["registered"]
        else:
            # Older server-dispatched runs retain their original retry route.
            count = bill_printing.confirm_run(run_id, owner_id=current_user.id)
    except bill_printing.BillPrintError as exc:
        code = str(exc)
        status = 404 if code in {"run_not_found", "run_expired"} else 409
        return jsonify({"error": code}), status
    except Exception as exc:  # noqa: BLE001 — optional SQL Server driver errors
        return _query_error(exc)
    return jsonify({"registered": count})


@u8_bp.put("/u8/favorites")
@login_required
def update_favorites() -> ResponseReturnValue:
    try:
        payload = FavoritesRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return validation_error_response(exc)
    if any(code not in _BILL_CODES for code in payload.bill_types):
        return jsonify({"error": "unsupported_bill_type"}), 400

    session = get_session()
    session.execute(delete(BillFavorite).where(BillFavorite.user_id == current_user.id))
    for position, bill_type in enumerate(payload.bill_types):
        session.add(BillFavorite(user_id=current_user.id, bill_type=bill_type, position=position))
    session.commit()
    return jsonify({"favorites": payload.bill_types})


def _query_error(exc: Exception) -> ResponseReturnValue:
    if isinstance(exc, u8_bills.U8DatabaseMismatchError):
        return jsonify({"error": "u8_database_mismatch"}), 503
    # SQL errors can contain server details. Keep them in server logs only.
    _LOG.warning("U8 query failed: %s", type(exc).__name__)
    return jsonify({"error": "u8_query_failed"}), 503


@u8_bp.get("/u8/bills")
@login_required
def search_bills() -> ResponseReturnValue:
    try:
        payload = BillSearch.model_validate(request.args.to_dict())
    except ValidationError as exc:
        return validation_error_response(exc)
    if payload.bill_type not in _BILL_CODES:
        return jsonify({"error": "unsupported_bill_type"}), 400
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    try:
        rows, truncated = u8_bills.list_bills(
            payload.bill_type,
            code=payload.code.strip(),
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except Exception as exc:  # noqa: BLE001 — driver-specific errors are optional at import time
        return _query_error(exc)
    return jsonify({"bills": rows, "truncated": truncated})


@u8_bp.get("/u8/bills/<bill_type>/<int:main_id>/details")
@login_required
def bill_details(bill_type: str, main_id: int) -> ResponseReturnValue:
    if bill_type not in _BILL_CODES:
        return jsonify({"error": "unsupported_bill_type"}), 400
    if not u8_bills.is_configured():
        return jsonify({"error": "u8_not_configured"}), 503
    try:
        if request.args.get("pending") == "1":
            number = request.args.get("bill_number", "").strip()
            if not number or len(number) > 100:
                return jsonify({"error": "invalid_bill"}), 400
            rows, truncated = u8_bills.list_pending_details(bill_type, main_id, number)
        else:
            rows, truncated = u8_bills.list_details(bill_type, main_id)
    except Exception as exc:  # noqa: BLE001 — driver-specific errors are optional at import time
        return _query_error(exc)
    return jsonify({"details": rows, "truncated": truncated})
