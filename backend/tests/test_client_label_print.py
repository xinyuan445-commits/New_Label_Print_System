"""Client receipts, printable payloads, retry safety and production-account boundaries."""

import json
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pypdfium2
import pytest

from app.db.session import get_session
from app.models.label_format import FormatKind, LabelFormat
from app.services import bill_printing, client_label_print, u8_bills
from app.services.batch_render import render_batch_pdf
from app.services.users import create_user


def _prepare(printer="Microsoft Print to PDF"):
    rows = [{"sn": "SN123", "数量": "5.00"}]
    template = SimpleNamespace(id=1, name="Test", width_mm=100, height_mm=50)
    pdf = render_batch_pdf({}, rows, width_mm=100, height_mm=50)
    return client_label_print.prepare(
        owner_id=1,
        template=template,
        bill_type="CGRK",
        bill_number="RK001",
        printer=printer,
        rows=rows,
        records=[{"sn": "SN123", "line_number": 3}],
        pdf_bytes=pdf,
    )


@pytest.mark.parametrize("printer", ["Microsoft Print to PDF", "热敏测试队列"])
def test_bundle_preserves_physical_size_and_label_filename(printer):
    result = _prepare(printer)
    with ZipFile(client_label_print.bundle_path(result["run_id"], 1)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["pages"][0]["filename"] == "RK001_3_SN123.pdf"
        assert manifest["width_mm"] == 100 and manifest["height_mm"] == 50
        data = bundle.read(manifest["pages"][0]["file"])
    if printer == "Microsoft Print to PDF":
        with pypdfium2.PdfDocument(data) as doc:
            assert len(doc) == 1
            width, height = doc.get_page_size(0)
            assert width == pytest.approx(100 * 72 / 25.4, abs=0.01)
            assert height == pytest.approx(50 * 72 / 25.4, abs=0.01)
    else:
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            assert image.width == pytest.approx(100 * 300 / 25.4, abs=1)
    with pytest.raises(bill_printing.BillPrintError, match="run_not_found"):
        client_label_print.bundle_path(result["run_id"], 2)


def test_browser_mode_prepares_pdf_without_client_agent_or_registration():
    prepared = _prepare("浏览器打印")
    assert prepared["receipt"]
    assert prepared["pdf_url"].endswith("/pdf/RK001_3_SN123.pdf")
    assert not prepared["bundle_url"]
    assert client_label_print.state_for(prepared["run_id"], 1)["status"] == "prepared"


def test_incomplete_or_wrong_receipt_never_registers(app, monkeypatch):
    result = _prepare()
    monkeypatch.setattr(bill_printing, "confirm_run", lambda *_a, **_k: pytest.fail("no writes"))
    with app.app_context():
        for receipt in (None, {}, {"receipt": "wrong", "printed": 1}):
            with pytest.raises(bill_printing.BillPrintError):
                client_label_print.complete(
                    result["run_id"], owner_id=1, session=get_session(), acknowledgment=receipt
                )


def test_registration_failure_retries_original_run_and_history_once(app, client, csrf, monkeypatch):
    with app.app_context():
        session = get_session()
        create_user(session, email="operator", plain_password="123")
        fmt = LabelFormat(name="Test", width_mm=100, height_mm=50, kind=FormatKind.CUSTOM)
        session.add(fmt)
        session.commit()
        format_id = fmt.id
    client.post(
        "/api/auth/login", json={"email": "operator", "password": "123"}, headers=csrf.headers()
    )
    client.post(
        "/api/templates",
        json={"name": "Test", "format_id": format_id, "canvas_data": {}},
        headers=csrf.headers(),
    )
    prepared = _prepare()
    state = client_label_print.state_for(prepared["run_id"], 1)
    receipt = {
        "receipt": state["receipt"],
        "bundle_sha256": prepared["bundle_sha256"],
        "printer": "Microsoft Print to PDF",
        "printed": 1,
    }
    calls = []

    def confirm(run_id, **_kwargs):
        calls.append(run_id)
        if len(calls) == 1:
            raise RuntimeError("database unavailable")
        return 1

    monkeypatch.setattr(bill_printing, "confirm_run", confirm)
    monkeypatch.setattr(u8_bills, "is_configured", lambda: True)
    url = f"/api/u8/print/{prepared['run_id']}"
    failed = client.post(url + "/complete", json=receipt, headers=csrf.headers())
    assert failed.status_code == 500 and failed.get_json()["printed"] is True
    assert client_label_print.state_for(prepared["run_id"], 1)["status"] == "dispatched"
    assert client.post(url + "/register", headers=csrf.headers()).get_json() == {"registered": 1}
    assert client.post(url + "/complete", json=receipt, headers=csrf.headers()).status_code == 200
    assert calls == [prepared["run_id"], prepared["run_id"]]
    assert len(client.get("/api/history").get_json()["files"]) == 1
    # A different account cannot claim or fetch this job.
    client.post("/api/auth/logout", headers=csrf.headers())
    assert client.get(url + "/bundle").status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/u8/print",
        "/api/u8/stock/print",
        "/api/u8/reprint",
        "/api/u8/print/" + "a" * 32 + "/complete",
    ],
)
def test_008_still_blocks_client_print_preparation_and_registration(
    app, client, csrf, monkeypatch, path
):
    with app.app_context():
        create_user(get_session(), email="readonly", plain_password="123")
    client.post(
        "/api/auth/login", json={"email": "readonly", "password": "123"}, headers=csrf.headers()
    )
    monkeypatch.setattr(u8_bills, "query_only", lambda: True)
    response = client.post(path, json={}, headers=csrf.headers())
    assert response.status_code == 403 and response.get_json()["error"] == "u8_read_only"
