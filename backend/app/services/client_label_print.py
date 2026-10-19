"""Prepare immutable driver jobs; acknowledge client dispatch before trace registration."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from contextlib import closing
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from zipfile import ZIP_DEFLATED, ZipFile

import pypdfium2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generated_file import GeneratedFile
from app.models.template import Template
from app.services import bill_printing, generated_files, windows_label_print

_LOCK = threading.RLock()
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
BROWSER_PRINTER = "浏览器打印"


def _state_path(run_id: str) -> Path:
    return bill_printing._run_path(run_id, "client.json")


def _write_state(run_id: str, state: dict[str, Any]) -> None:
    target = _state_path(run_id)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def state_for(run_id: str, owner_id: int) -> dict[str, Any]:
    bill_printing.load_run(run_id, owner_id=owner_id)
    try:
        return cast("dict[str, Any]", json.loads(_state_path(run_id).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise bill_printing.BillPrintError("client_job_missing") from exc


def prepare(
    *,
    owner_id: int,
    template: Template,
    bill_type: str,
    bill_number: str,
    printer: str,
    rows: list[dict[str, str]],
    records: list[dict[str, Any]],
    pdf_bytes: bytes,
) -> dict[str, Any]:
    """Package PDF pages for PDF output, or 300 DPI PNGs for the client's driver."""
    run_id = bill_printing.save_run(
        owner_id=owner_id,
        template_id=template.id,
        bill_type=bill_type,
        bill_number=bill_number,
        rows=rows,
        records=records,
        pdf_bytes=pdf_bytes,
    )
    receipt = secrets.token_hex(32)
    manifest: dict[str, Any] = {
        "version": 1,
        "run_id": run_id,
        "receipt": receipt,
        "printer": printer,
        "width_mm": float(template.width_mm),
        "height_mm": float(template.height_mm),
        "reprint": bill_type == "REPRINT",
        "pages": [],
    }
    if printer == BROWSER_PRINTER:
        digest = hashlib.sha256(pdf_bytes).hexdigest()
        filename = windows_label_print.label_filename(bill_number, 1, "labels")
        filename = filename.removesuffix("_1_labels.pdf") + ".pdf"
        if len(records) == 1:
            filename = windows_label_print.label_filename(
                str(records[0].get("document_number") or bill_number),
                int(records[0]["line_number"]),
                str(records[0]["sn"]),
            )
        from urllib.parse import quote

        _write_state(
            run_id,
            {
                "status": "prepared",
                "receipt": receipt,
                "bundle_sha256": digest,
                "printer": printer,
                "template_name": template.name,
            },
        )
        return {
            "run_id": run_id,
            "label_count": len(rows),
            "bundle_sha256": digest,
            "bundle_url": "",
            "receipt": receipt,
            "printer": printer,
            "pdf_url": f"/api/u8/print/{run_id}/pdf/{quote(filename, safe='')}",
        }
    buffer = BytesIO()
    with _LOCK, ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        with pypdfium2.PdfDocument(pdf_bytes) as document:
            if len(document) != len(records):
                raise bill_printing.BillPrintError("invalid_print_job")
            for index, record in enumerate(records):
                filename = windows_label_print.label_filename(
                    str(record.get("document_number") or bill_number),
                    int(record["line_number"]),
                    str(record["sn"]),
                )
                if bill_type == "REPRINT" and len(records) > 1:
                    filename = f"{filename[:-4]}_{index + 1}.pdf"
                member = (
                    f"{index + 1}.pdf"
                    if printer == windows_label_print.PDF_PRINTER
                    else f"{index + 1}.png"
                )
                if printer == windows_label_print.PDF_PRINTER:
                    page_bytes = BytesIO()
                    with pypdfium2.PdfDocument.new() as single:
                        single.import_pages(document, pages=[index])
                        single.save(page_bytes)
                    archive.writestr(member, page_bytes.getvalue())
                else:
                    # PDFium is not thread-safe; serialize render work and close every bitmap.
                    with (
                        closing(document[index]) as page,
                        closing(page.render(scale=300 / 72)) as bitmap,
                        bitmap.to_pil() as image,
                    ):
                        png = BytesIO()
                        image.save(png, format="PNG")
                        archive.writestr(member, png.getvalue())
                manifest["pages"].append({"file": member, "filename": filename})
                if buffer.tell() > MAX_BUNDLE_BYTES:
                    raise bill_printing.BillPrintError("print_job_too_large")
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    data = buffer.getvalue()
    if len(data) > MAX_BUNDLE_BYTES:
        raise bill_printing.BillPrintError("print_job_too_large")
    digest = hashlib.sha256(data).hexdigest()
    bill_printing._run_path(run_id, "zip").write_bytes(data)
    _write_state(
        run_id,
        {
            "status": "prepared",
            "receipt": receipt,
            "bundle_sha256": digest,
            "printer": printer,
            "template_name": template.name,
        },
    )
    return {
        "run_id": run_id,
        "label_count": len(rows),
        "bundle_sha256": digest,
        "bundle_url": f"/api/u8/print/{run_id}/bundle",
    }


def bundle_path(run_id: str, owner_id: int) -> Path:
    with _LOCK:
        state = state_for(run_id, owner_id)
        path = bill_printing._run_path(run_id, "zip")
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != state["bundle_sha256"]
        ):
            raise bill_printing.BillPrintError("client_job_missing")
        return path


def _history(session: Session, run: dict[str, Any], state: dict[str, Any]) -> None:
    filename = f"bill-print-runs/{run['run_id']}.pdf"
    if (
        session.scalar(
            select(GeneratedFile.id).where(
                GeneratedFile.owner_id == run["owner_id"],
                GeneratedFile.storage_filename == filename,
            )
        )
        is None
    ):
        generated_files.record(
            session,
            owner_id=run["owner_id"],
            template_id=run["template_id"] if session.get(Template, run["template_id"]) else None,
            template_name=state["template_name"],
            kind="pdf",
            mode={"STOCK": "stock", "REPRINT": "reprint"}.get(run["bill_type"], "bill"),
            storage_filename=filename,
            row_count=run["label_count"],
        )


def complete(
    run_id: str,
    *,
    owner_id: int,
    session: Session,
    acknowledgment: dict[str, Any] | None,
) -> dict[str, Any]:
    """Persist client acceptance first. Retrying registration never sends labels again."""
    with _LOCK:
        run = bill_printing.load_run(run_id, owner_id=owner_id)
        state = state_for(run_id, owner_id)
        if acknowledgment is not None:
            if not isinstance(acknowledgment, dict):
                raise bill_printing.BillPrintError("invalid_client_receipt")
            if (
                acknowledgment.get("receipt") != state["receipt"]
                or acknowledgment.get("bundle_sha256") != state["bundle_sha256"]
                or acknowledgment.get("printer") != state["printer"]
                or type(acknowledgment.get("printed")) is not int
                or acknowledgment.get("printed") != run["label_count"]
            ):
                raise bill_printing.BillPrintError("invalid_client_receipt")
            if state["status"] == "prepared":
                state.update(status="dispatched", output_dir=acknowledgment.get("output_dir"))
                _write_state(run_id, state)
        if state["status"] == "prepared":
            raise bill_printing.BillPrintError("client_print_not_confirmed")
        _history(session, run, state)
        registered = 0
        if state["status"] != "completed" and run["bill_type"] != "REPRINT":
            registered = bill_printing.confirm_run(run_id, owner_id=owner_id)
        elif run["bill_type"] != "REPRINT":
            registered = run["label_count"]
        state["status"] = "completed"
        _write_state(run_id, state)
        return {
            "printed": run["label_count"],
            "registered": registered,
            "run_id": run_id,
            "output_dir": state.get("output_dir"),
            "printer": state["printer"],
        }
