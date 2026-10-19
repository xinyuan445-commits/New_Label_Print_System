"""Dispatch rendered bill labels to a Windows print queue.

Microsoft Print to PDF is saved directly as one correctly sized PDF per label.
The Windows driver otherwise substitutes A4 for custom label sizes and its
Save As dialog is invisible when the local server runs in the background.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from app.services.batch_render import AssetResolver, render_batch_pdf
from app.services.local_printers import list_local_printers

PDF_PRINTER = "Microsoft Print to PDF"
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_FILENAME = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.I)


class PrinterError(RuntimeError):
    """The requested printer could not accept the label job."""


def _is_windows() -> bool:
    return sys.platform == "win32"


def label_filename(bill_number: str, line_number: int, serial: str) -> str:
    """Build the operator-facing filename: document_line_SN.pdf."""
    if line_number < 1 or not serial:
        raise PrinterError("invalid_label_name")
    safe_bill = _INVALID_FILENAME.sub("_", bill_number).strip(" .")
    safe_serial = _INVALID_FILENAME.sub("_", serial).strip(" .")
    if not safe_bill or not safe_serial:
        raise PrinterError("invalid_label_name")
    if _RESERVED_FILENAME.fullmatch(safe_bill):
        safe_bill = f"_{safe_bill}"
    return f"{safe_bill}_{line_number}_{safe_serial}.pdf"


def output_dir() -> Path:
    configured = os.environ.get("LABEL_PRINT_OUTPUT_DIR")
    path = Path(configured) if configured else Path.home() / "Downloads" / "标签打印"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dispatch(
    *,
    printer: str,
    bill_number: str,
    rows: list[dict[str, str]],
    records: list[dict[str, Any]],
    pdf_bytes: bytes,
    canvas_data: dict[str, Any],
    width_mm: float,
    height_mm: float,
    resolve_asset: AssetResolver | None,
    reprint: bool = False,
) -> dict[str, Any]:
    """Print the already planned labels; return where PDF output was saved."""
    if not _is_windows():
        raise PrinterError("windows_printer_required")
    if not printer or printer not in list_local_printers():
        raise PrinterError("printer_not_found")
    if len(rows) != len(records) or not rows:
        raise PrinterError("invalid_print_job")

    if printer == PDF_PRINTER:
        folder = output_dir()
        if reprint:
            folder = folder / "补打" / f"{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}"
            folder.mkdir(parents=True, exist_ok=False)
        created: list[Path] = []
        try:
            for row, record in zip(rows, records, strict=True):
                filename = label_filename(
                    str(record.get("document_number") or bill_number),
                    int(record["line_number"]),
                    str(record["sn"]),
                )
                if reprint and len(rows) > 1:
                    filename = f"{Path(filename).stem}_{len(created) + 1}.pdf"
                destination = folder / filename
                if destination.exists():
                    raise PrinterError("file_exists")
                label_pdf = render_batch_pdf(
                    canvas_data,
                    [row],
                    width_mm=width_mm,
                    height_mm=height_mm,
                    resolve_asset=resolve_asset,
                )
                with destination.open("xb") as file:
                    file.write(label_pdf)
                created.append(destination)
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return {"output_dir": str(folder), "files": [path.name for path in created]}

    import pdfplumber

    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise PrinterError("powershell_unavailable")
    script = Path(__file__).with_name("windows_print_pages.ps1")
    with tempfile.TemporaryDirectory(prefix="bill-label-print-") as temp_name:
        temp = Path(temp_name)
        pages: list[Path] = []
        with pdfplumber.open(BytesIO(pdf_bytes)) as document:
            for index, page in enumerate(document.pages):
                image = page.to_image(resolution=300).original
                path = temp / f"page-{index + 1:04d}.png"
                image.save(path)
                image.close()
                pages.append(path)
        page_list = temp / "pages.txt"
        page_list.write_text("\n".join(str(path) for path in pages), encoding="utf-8")
        try:
            subprocess.run(  # noqa: S603 — fixed script and argument list
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(script),
                    "-PrinterName",
                    printer,
                    "-PageListPath",
                    str(page_list),
                    "-WidthMm",
                    str(width_mm),
                    "-HeightMm",
                    str(height_mm),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise PrinterError("printer_failed") from exc
    return {"output_dir": None, "files": []}
