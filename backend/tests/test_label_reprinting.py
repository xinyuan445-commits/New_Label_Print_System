"""Reprints retain the original identity and never register a second label."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.db.session import get_session
from app.models.label_format import FormatKind, LabelFormat
from app.services import (
    bill_printing,
    client_label_print,
    label_reprinting,
    u8_bills,
    windows_label_print,
)
from app.services.batch_render import render_batch_pdf
from app.services.users import create_user
from tests.conftest import CsrfHelper


def _trace() -> dict[str, Any]:
    return {
        "barcode": "008|ITEM-1|BATCH-1|50.00|SN123",
        "remaining_quantity": "7.00",
        "order_json": json.dumps({"documentNumber": "RK001", "orderType": "RK"}),
        "goods_json": json.dumps(
            {
                "name": "原物料名称",
                "code": "ITEM-1",
                "warehouseCode": "W1",
                "inventory": {"warehouse": "原仓库", "storageLocation": "原货位"},
                "Attribute": {"batchNumber": "BATCH-1"},
            }
        ),
        "printed_at": "2026-09-10 13:10:00",
        "printed_by": "operator",
    }


def test_recover_uses_original_quantity_and_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bill_printing, "_run_dir", lambda: tmp_path)
    label = label_reprinting.recover(_trace(), sn="SN123", unit="张")
    assert label["quantity"] == "50.00"
    assert label["sn"] == "SN123"
    assert label["barcode"] == _trace()["barcode"]
    assert label["document_number"] == "RK001"
    assert label["item_name"] == "原物料名称"
    assert label["variables"]["条码"] == _trace()["barcode"]
    assert label["variables"]["行号"] == ""


@pytest.mark.parametrize(
    "barcode",
    [
        "008|ITEM-1|BATCH-1|NaN|SN123",
        "008|ITEM-1|BATCH-1|0|SN123",
        "008|ITEM-1|BATCH-1|50|OTHER",
        "incomplete",
    ],
)
def test_recover_rejects_incomplete_or_wrong_identity(barcode: str) -> None:
    trace = {**_trace(), "barcode": barcode}
    with pytest.raises(label_reprinting.ReprintError, match="invalid_label_record"):
        label_reprinting.recover(trace, sn="SN123")


def test_local_snapshot_restores_original_unit_line_and_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bill_printing, "_run_dir", lambda: tmp_path)
    variables = label_reprinting.recover(_trace(), sn="SN123")["variables"]
    variables.update({"单位": "原单位", "规格型号": "原规格", "行号": "7"})
    manifest = {
        "bill_type": "CGRK",
        "template_id": 42,
        "records": [{"sn": "SN123", "trace_back_code": _trace()["barcode"], "line_number": 7}],
        "rows": [variables],
    }
    (tmp_path / "original.json").write_text(json.dumps(manifest), encoding="utf-8")
    label = label_reprinting.recover(_trace(), sn="SN123", unit="当前单位")
    assert label["unit"] == "原单位"
    assert label["line_number"] == 7
    assert label["template_id"] == 42
    assert label["variables"]["规格型号"] == "原规格"


def test_reprint_run_cannot_be_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bill_printing,
        "load_run",
        lambda *_args, **_kwargs: {
            "bill_type": "REPRINT",
            "records": [],
        },
    )
    with pytest.raises(bill_printing.BillPrintError, match="reprint_registration_forbidden"):
        bill_printing.confirm_run("a" * 32, owner_id=1)


def test_reprint_route_uses_original_sn_for_copies_and_no_trace_writes(
    app: Flask,
    client: FlaskClient,
    csrf: CsrfHelper,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with app.app_context():
        session = get_session()
        fmt = LabelFormat(name="Reprint", width_mm=100, height_mm=50, kind=FormatKind.CUSTOM)
        session.add(fmt)
        session.commit()
        format_id = fmt.id
        create_user(session, email="reprint@example.com", plain_password="123")
    assert client.get("/api/u8/reprint?sn=SN123").status_code == 401
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "reprint@example.com", "password": "123"},
            headers=csrf.headers(),
        ).status_code
        == 200
    )
    created = client.post(
        "/api/templates",
        json={"name": "Reprint", "format_id": format_id, "canvas_data": {}},
        headers=csrf.headers(),
    )
    assert created.status_code == 201
    template_id = created.get_json()["id"]
    monkeypatch.setattr(u8_bills, "is_configured", lambda: True)
    label = label_reprinting.recover(_trace(), sn="SN123", unit="张")
    monkeypatch.setattr(label_reprinting, "lookup", lambda _sn: label)
    observed: dict[str, Any] = {}

    def dispatch(**kwargs: Any) -> dict[str, Any]:
        observed.update(kwargs)
        return {"output_dir": None, "files": []}

    def forbidden_registration(*_args: Any, **_kwargs: Any) -> int:
        pytest.fail("Reprints must not write another trace record")

    monkeypatch.setattr(windows_label_print, "dispatch", dispatch)
    monkeypatch.setattr(bill_printing, "confirm_run", forbidden_registration)
    assert client.get("/api/u8/reprint?sn=SN123").get_json()["label"]["quantity"] == "50.00"
    request_data = {
        "sn": "SN123",
        "template_id": template_id,
        "printer": "Microsoft Print to PDF",
        "copies": 2,
    }
    preview = client.post(
        "/api/u8/reprint/preview",
        json=request_data,
        headers=csrf.headers(),
    )
    assert preview.status_code == 200 and preview.data.startswith(b"%PDF-")
    assert observed == {}
    printed = client.post("/api/u8/reprint", json=request_data, headers=csrf.headers())
    assert printed.status_code == 200
    result = printed.get_json()
    assert result["label_count"] == 2
    assert observed == {}
    with app.app_context():
        manifest = bill_printing.load_run(result["run_id"], owner_id=1)
        state = client_label_print.state_for(result["run_id"], 1)
    assert all(row["sn"] == "SN123" for row in manifest["rows"])
    assert all(row["条码"] == _trace()["barcode"] for row in manifest["rows"])
    completed = client.post(
        f"/api/u8/print/{result['run_id']}/complete",
        json={
            "receipt": state["receipt"],
            "bundle_sha256": result["bundle_sha256"],
            "printer": "Microsoft Print to PDF",
            "printed": 2,
        },
        headers=csrf.headers(),
    )
    assert completed.status_code == 200
    assert completed.get_json()["printed"] == 2
    assert observed == {}
    history = client.get("/api/history").get_json()["files"]
    assert history[0]["mode"] == "reprint"
    assert history[0]["download_name"] == "RK001_补打.pdf"
    invalid = client.post(
        "/api/u8/reprint",
        json={**request_data, "copies": 101},
        headers=csrf.headers(),
    )
    assert invalid.status_code == 400


def test_pdf_reprints_can_repeat_an_existing_sn_without_filename_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(windows_label_print, "_is_windows", lambda: True)
    monkeypatch.setattr(
        windows_label_print,
        "list_local_printers",
        lambda: [
            "Microsoft Print to PDF",
        ],
    )
    monkeypatch.setenv("LABEL_PRINT_OUTPUT_DIR", str(tmp_path))
    original = tmp_path / "RK001_7_SN123.pdf"
    original.write_bytes(b"original")
    rows = [{"sn": "SN123"}] * 2
    records = [{"line_number": 7, "sn": "SN123"}] * 2
    pdf = render_batch_pdf({}, rows, width_mm=100, height_mm=50)
    result = windows_label_print.dispatch(
        printer="Microsoft Print to PDF",
        bill_number="RK001",
        rows=rows,
        records=records,
        pdf_bytes=pdf,
        canvas_data={},
        width_mm=100,
        height_mm=50,
        resolve_asset=None,
        reprint=True,
    )
    assert original.read_bytes() == b"original"
    assert result["files"] == ["RK001_7_SN123_1.pdf", "RK001_7_SN123_2.pdf"]
    assert Path(result["output_dir"]).parent.name == "补打"
    assert all((Path(result["output_dir"]) / name).is_file() for name in result["files"])
