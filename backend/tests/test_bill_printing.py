"""Bill PDF preparation and three-table trace registration boundaries."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.db.session import get_session
from app.models.label_format import FormatKind, LabelFormat
from app.services import bill_printing, client_label_print, u8_bills, windows_label_print
from app.services.users import create_user
from tests.conftest import CsrfHelper


def _detail(quantity: str = "105") -> dict[str, Any]:
    return {
        "仓库编码": "WH1",
        "仓库名称": "测试仓库",
        "货位编码": "P1",
        "货位名称": "一号货位",
        "存货编码": "ITEM-1",
        "存货名称": "测试物料",
        "数量": quantity,
        "单位": "张",
        "批号": "BATCH-1",
    }


def test_plan_matches_legacy_three_table_shape_and_pdf_variables() -> None:
    rows, records = bill_printing.build_label_plan(
        bill_type="CGRK",
        bill_number="RK001",
        details=[_detail()],
        selections=[{"index": 0, "quantity": Decimal(105), "packaging": Decimal(50)}],
        include_remainder=True,
        username="operator",
    )
    assert [row["数量"] for row in rows] == ["50.00", "50.00", "5.00"]
    assert len({row["sn"] for row in rows}) == 3
    for row, record in zip(rows, records, strict=True):
        assert record["line_number"] == 1
        assert row["行号"] == "1"
        assert record["order_json"] == {"documentNumber": "RK001", "orderType": "RK"}
        assert record["goods_json"]["quantity"] == 0.0
        assert record["goods_json"]["inventory"] == {
            "warehouse": "测试仓库",
            "storageLocation": "一号货位",
            "storageLocationCode": "P1",
        }
        assert record["goods_json"]["Attribute"]["batchNumber"] == "BATCH-1"
        assert record["pda_order_uuid"] == f"{row['sn']}dyx"
        assert record["pda_goods_uuid"] == f"{row['sn']}syx"
        assert record["trace_back_code"] == row["条码"]
        assert row["条码"] == f"008|ITEM-1|BATCH-1|{row['数量']}|{row['sn']}"
        assert record["sum"] == row["数量"]


def test_inventory_count_labels_use_actual_count_and_normal_packaging() -> None:
    detail = {**_detail("11"), "账面数量": "0"}
    rows, records = bill_printing.build_label_plan(
        bill_type="PDD",
        bill_number="PDD26071015",
        details=[detail],
        selections=[{"index": 0, "quantity": Decimal(11), "packaging": Decimal(10)}],
        include_remainder=True,
        username="operator",
    )
    assert [row["数量"] for row in rows] == ["10.00", "1.00"]
    assert all(row["单据编码"] == "PDD26071015" for row in rows)
    assert records[0]["order_json"] == {
        "documentNumber": "PDD26071015",
        "orderType": "PDD",
    }


def test_negative_outbound_return_uses_positive_label_quantity() -> None:
    rows, _ = bill_printing.build_label_plan(
        bill_type="XSCK",
        bill_number="R001",
        details=[_detail("-12")],
        selections=[{"index": 0, "quantity": Decimal(12), "packaging": Decimal(10)}],
        include_remainder=True,
        username="operator",
    )
    assert [row["数量"] for row in rows] == ["10.00", "2.00"]
    with pytest.raises(bill_printing.BillPrintError, match="not_inbound_line"):
        bill_printing.build_label_plan(
            bill_type="XSCK",
            bill_number="R001",
            details=[_detail("12")],
            selections=[{"index": 0, "quantity": Decimal(12), "packaging": Decimal(10)}],
            include_remainder=True,
            username="operator",
        )


def test_plan_rejects_overprinting_and_excessive_label_count() -> None:
    with pytest.raises(bill_printing.BillPrintError, match="invalid_quantity"):
        bill_printing.build_label_plan(
            bill_type="CGRK",
            bill_number="RK001",
            details=[_detail("50")],
            selections=[{"index": 0, "quantity": Decimal(51), "packaging": Decimal(50)}],
            include_remainder=True,
            username="operator",
        )
    with pytest.raises(bill_printing.BillPrintError, match="too_many_labels"):
        bill_printing.build_label_plan(
            bill_type="CGRK",
            bill_number="RK001",
            details=[_detail("1001")],
            selections=[{"index": 0, "quantity": Decimal(1001), "packaging": Decimal(1)}],
            include_remainder=True,
            username="operator",
        )


def test_saved_pdf_manifest_is_owner_bound_and_detects_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PDFS_DIR", str(tmp_path))
    rows, records = bill_printing.build_label_plan(
        bill_type="CGRK",
        bill_number="RK001",
        details=[_detail("5")],
        selections=[{"index": 0, "quantity": Decimal(5), "packaging": Decimal(5)}],
        include_remainder=True,
        username="operator",
    )
    run_id = bill_printing.save_run(
        owner_id=7,
        template_id=3,
        bill_type="CGRK",
        bill_number="RK001",
        rows=rows,
        records=records,
        pdf_bytes=b"%PDF-test",
    )
    assert bill_printing.print_pdf_path(run_id, owner_id=7).read_bytes() == b"%PDF-test"
    with pytest.raises(bill_printing.BillPrintError, match="run_not_found"):
        bill_printing.load_run(run_id, owner_id=8)
    bill_printing.print_pdf_path(run_id, owner_id=7).write_bytes(b"modified")
    with pytest.raises(bill_printing.BillPrintError, match="pdf_missing"):
        bill_printing.load_run(run_id, owner_id=7)


def test_write_connection_is_locked_to_998(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bill_printing,
        "get_connection_string",
        lambda: (
            "Driver={ODBC Driver 17 for SQL Server};Database=ufdata_998_2021;"
            "ApplicationIntent=ReadOnly"
        ),
    )
    assert "ApplicationIntent=ReadWrite" in bill_printing._write_connection_string()
    monkeypatch.setattr(
        bill_printing,
        "get_connection_string",
        lambda: (
            "Driver={ODBC Driver 17 for SQL Server};Database=UFDATA_008_2021;"
            "ApplicationIntent=ReadOnly"
        ),
    )
    with pytest.raises(u8_bills.U8DatabaseMismatchError):
        bill_printing._write_connection_string()


def test_confirmation_inserts_one_transaction_for_all_three_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {
            "order_json": {"documentNumber": "RK001", "orderType": "CGRK"},
            "goods_json": {"name": "物料", "quantity": 0.0},
            "pda_order_uuid": "serialdyx",
            "pda_goods_uuid": "serialsyx",
            "trace_back_code": "008|ITEM|B|5.00|serial",
            "sn": "serial",
            "sum": "5.00",
            "user": "operator",
            "time": "2026-10-02T12:00:00+08:00",
        }
    ]
    monkeypatch.setattr(
        bill_printing,
        "load_run",
        lambda *_args, **_kwargs: {
            "records": records,
            "label_count": 1,
        },
    )
    monkeypatch.setattr(bill_printing, "_write_connection_string", lambda: "test-998")

    class Cursor:
        def __init__(self) -> None:
            self.queries: list[tuple[str, tuple[object, ...]]] = []
            self.last = ""

        def execute(self, sql: str, *args: object) -> Cursor:
            self.last = sql
            self.queries.append((sql, args))
            return self

        def fetchval(self) -> object:
            return "ufdata_998_2021" if "DB_NAME" in self.last else 0

    class Connection:
        timeout = 0

        def __init__(self) -> None:
            self.the_cursor = Cursor()
            self.commits = 0
            self.rollbacks = 0

        def cursor(self) -> Cursor:
            return self.the_cursor

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

        def close(self) -> None:
            pass

    connection = Connection()
    import pyodbc

    monkeypatch.setattr(pyodbc, "connect", lambda *_args, **_kwargs: connection)
    assert bill_printing.confirm_run("a" * 32, owner_id=7) == 1
    inserts = [
        (sql, args) for sql, args in connection.the_cursor.queries if sql.startswith("INSERT")
    ]
    assert len(inserts) == 3
    assert "TraceBackOrder" in inserts[0][0]
    assert json.loads(str(inserts[0][1][0]))["documentNumber"] == "RK001"
    assert "TraceBackGoods" in inserts[1][0]
    assert "TraceBackOnlyCode" in inserts[2][0]
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_print_route_prepares_then_registers_only_after_client_acceptance(
    app: Flask,
    client: FlaskClient,
    csrf: CsrfHelper,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with app.app_context():
        session = get_session()
        label_format = LabelFormat(
            name="Test label", width_mm=100, height_mm=50, kind=FormatKind.CUSTOM
        )
        session.add(label_format)
        session.commit()
        format_id = label_format.id
        create_user(session, email="operator@example.com", plain_password="password")
    client.post(
        "/api/auth/login",
        json={"email": "operator@example.com", "password": "password"},
        headers=csrf.headers(),
    )
    created = client.post(
        "/api/templates",
        json={"name": "Bill label", "format_id": format_id, "canvas_data": {}},
        headers=csrf.headers(),
    )
    assert created.status_code == 201
    template_id = created.get_json()["id"]
    monkeypatch.setattr(u8_bills, "is_configured", lambda: True)
    monkeypatch.setattr(
        u8_bills,
        "list_bills",
        lambda *_args, **_kwargs: (
            [{"ID": 7, "单据号": "RK001"}],
            False,
        ),
    )
    monkeypatch.setattr(
        u8_bills,
        "list_details",
        lambda *_args, **_kwargs: (
            [_detail("5")],
            False,
        ),
    )
    dispatched: dict[str, object] = {}

    def fake_dispatch(**kwargs: object) -> dict[str, object]:
        dispatched.update(kwargs)
        return {"output_dir": "C:\\Downloads\\标签打印", "files": ["RK001_1_123.pdf"]}

    monkeypatch.setattr(windows_label_print, "dispatch", fake_dispatch)
    observed: dict[str, object] = {}

    def fake_confirm(given_run_id: str, *, owner_id: int) -> int:
        observed.update(run_id=given_run_id, owner_id=owner_id)
        return 1

    monkeypatch.setattr(bill_printing, "confirm_run", fake_confirm)
    response = client.post(
        "/api/u8/print",
        json={
            "bill_type": "CGRK",
            "bill_id": 7,
            "bill_number": "RK001",
            "bill_date": "2026-10-02",
            "template_id": template_id,
            "printer": "Microsoft Print to PDF",
            "lines": [
                {
                    "index": 0,
                    "item_code": "ITEM-1",
                    "batch": "BATCH-1",
                    "quantity": 5,
                    "packaging": 5,
                }
            ],
            "include_remainder": True,
        },
        headers=csrf.headers(),
    )
    assert response.status_code == 200
    result = response.get_json()
    assert result["label_count"] == 1
    assert "printed" not in result
    run_id = result["run_id"]
    assert dispatched == observed == {}
    unprinted = client.post(f"/api/u8/print/{run_id}/register", headers=csrf.headers())
    assert unprinted.status_code == 409
    assert observed == {}
    assert client.get(result["bundle_url"]).status_code == 200
    with app.app_context():
        state = client_label_print.state_for(run_id, 1)
    acknowledgment = {
        "receipt": state["receipt"],
        "bundle_sha256": result["bundle_sha256"],
        "printer": "Microsoft Print to PDF",
        "printed": 1,
    }
    completed = client.post(
        f"/api/u8/print/{run_id}/complete", json=acknowledgment, headers=csrf.headers()
    )
    assert completed.status_code == 200
    assert completed.get_json()["printed"] == completed.get_json()["registered"] == 1
    assert observed == {"run_id": run_id, "owner_id": 1}
    assert dispatched == {}
    assert client.get("/api/history").status_code == 200
    manifest = bill_printing.load_run(run_id, owner_id=1)
    assert manifest["label_count"] == 1
    assert manifest["records"][0]["trace_back_code"].startswith("008|ITEM-1|BATCH-1|5.00|")
    monkeypatch.setattr(
        u8_bills,
        "list_pending_details",
        lambda *_args, **_kwargs: (
            [
                {
                    **_detail("5"),
                    "待打印数量": "0",
                    "已打印数量": "5",
                    "打印状态": "已打印",
                }
            ],
            False,
        ),
    )
    stale = client.post(
        "/api/u8/print",
        json={
            "bill_type": "CGRK",
            "bill_id": 7,
            "bill_number": "RK001",
            "bill_date": "2026-10-02",
            "template_id": template_id,
            "printer": "Microsoft Print to PDF",
            "pending_only": True,
            "lines": [
                {
                    "index": 0,
                    "item_code": "ITEM-1",
                    "batch": "BATCH-1",
                    "quantity": 5,
                    "packaging": 5,
                }
            ],
        },
        headers=csrf.headers(),
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"] == "print_progress_changed"

    confirmed = client.post(f"/api/u8/print/{run_id}/register", headers=csrf.headers())
    assert confirmed.status_code == 200
    assert confirmed.get_json() == {"registered": 1}
    assert observed == {"run_id": run_id, "owner_id": 1}


def test_pdf_printer_filename_uses_document_line_and_sn() -> None:
    assert windows_label_print.label_filename("RK/001", 3, "260102123456") == (
        "RK_001_3_260102123456.pdf"
    )


def test_pdf_printer_saves_one_correctly_sized_file_per_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pdfplumber

    from app.services.batch_render import render_batch_pdf

    monkeypatch.setattr(windows_label_print, "_is_windows", lambda: True)
    monkeypatch.setattr(
        windows_label_print, "list_local_printers", lambda: ["Microsoft Print to PDF"]
    )
    monkeypatch.setenv("LABEL_PRINT_OUTPUT_DIR", str(tmp_path))
    rows = [{"sn": "S1"}, {"sn": "S2"}]
    records = [{"line_number": 2, "sn": "S1"}, {"line_number": 2, "sn": "S2"}]
    canvas_data: dict[str, Any] = {"objects": []}
    result = windows_label_print.dispatch(
        printer="Microsoft Print to PDF",
        bill_number="RK001",
        rows=rows,
        records=records,
        pdf_bytes=render_batch_pdf(canvas_data, rows, width_mm=100, height_mm=60),
        canvas_data=canvas_data,
        width_mm=100,
        height_mm=60,
        resolve_asset=None,
    )
    assert result["files"] == ["RK001_2_S1.pdf", "RK001_2_S2.pdf"]
    for filename in result["files"]:
        with pdfplumber.open(tmp_path / filename) as pdf:
            assert len(pdf.pages) == 1
            assert pdf.pages[0].width == pytest.approx(100 * 72 / 25.4, abs=0.1)
            assert pdf.pages[0].height == pytest.approx(60 * 72 / 25.4, abs=0.1)
