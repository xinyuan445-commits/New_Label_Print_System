"""Inventory lookup and stock label planning stay within the test account."""

from __future__ import annotations

from decimal import Decimal

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.db.session import get_session
from app.models.label_format import FormatKind, LabelFormat
from app.services import (
    bill_printing,
    client_label_print,
    u8_bills,
    u8_inventory,
    windows_label_print,
)
from app.services.users import create_user
from tests.conftest import CsrfHelper


def _stock(batch: str = "B-1", quantity: str = "53") -> dict[str, object]:
    return {
        "source": "position",
        "stock_id": 17,
        "warehouse_code": "W1",
        "warehouse_name": "测试仓库",
        "location_code": "P1",
        "location_name": "一号货位",
        "item_code": "ITEM-1",
        "item_name": "测试存货",
        "specification": "100×50",
        "quantity": quantity,
        "unit": "件",
        "batch": batch,
    }


def _selection(batch: str = "B-1", quantity: str = "53") -> dict[str, object]:
    return {
        "source": "position",
        "stock_id": 17,
        "item_code": "ITEM-1",
        "batch": batch,
        "quantity": Decimal(quantity),
        "packaging": Decimal("50"),
    }


def test_stock_plan_uses_inventory_batch_and_hour_document_number() -> None:
    rows, records = bill_printing.build_stock_label_plan(
        stock=[_stock()],
        selections=[_selection()],
        include_remainder=True,
        username="operator",
    )
    assert [row["数量"] for row in rows] == ["50.00", "3.00"]
    for row, record in zip(rows, records, strict=True):
        number = row["单据编码"]
        assert len(number) == 10 and number.isdigit()
        assert record["order_json"] == {"documentNumber": number, "orderType": "KC"}
        assert record["goods_json"]["Attribute"]["batchNumber"] == "B-1"
        assert record["goods_json"]["inventory"]["storageLocationCode"] == "P1"
        assert record["document_number"] == number
        assert row["规格型号"] == "100×50"
        assert row["条码"] == f"008|ITEM-1|B-1|{row['数量']}|{row['sn']}"


def test_stock_plan_allows_empty_batch_and_rejects_stale_or_excess_quantity() -> None:
    rows, records = bill_printing.build_stock_label_plan(
        stock=[_stock(batch="", quantity="10")],
        selections=[_selection(batch="", quantity="10")],
        include_remainder=True,
        username="operator",
    )
    assert rows[0]["批号"] == ""
    assert records[0]["goods_json"]["Attribute"]["batchNumber"] == ""
    with pytest.raises(bill_printing.BillPrintError, match="stock_changed"):
        bill_printing.build_stock_label_plan(
            stock=[_stock(batch="NEW")],
            selections=[_selection()],
            include_remainder=True,
            username="operator",
        )
    with pytest.raises(bill_printing.BillPrintError, match="invalid_quantity"):
        bill_printing.build_stock_label_plan(
            stock=[_stock(quantity="49")],
            selections=[_selection(quantity="50")],
            include_remainder=True,
            username="operator",
        )


def test_inventory_sql_uses_both_sources() -> None:
    sql = u8_inventory._BASE_SQL
    assert "FROM CurrentStock a" in sql
    assert "FROM InvPositionSum a" in sql
    assert "wh.bWhPos = 0" in sql and "wh.bWhPos = 1" in sql
    assert "wh.dWhEndDate IS NULL" in sql


def test_stock_routes_query_and_print_without_touching_live_u8(
    app: Flask,
    client: FlaskClient,
    csrf: CsrfHelper,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with app.app_context():
        session = get_session()
        session.add(
            LabelFormat(
                name="Stock test format",
                width_mm=100,
                height_mm=50,
                kind=FormatKind.CUSTOM,
            )
        )
        session.commit()
        format_id = session.query(LabelFormat).filter_by(name="Stock test format").one().id
        create_user(session, email="stock@example.com", plain_password="password")
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "stock@example.com", "password": "password"},
            headers=csrf.headers(),
        ).status_code
        == 200
    )
    created = client.post(
        "/api/templates",
        json={"name": "Stock label", "format_id": format_id, "canvas_data": {}},
        headers=csrf.headers(),
    )
    assert created.status_code == 201
    template_id = created.get_json()["id"]
    monkeypatch.setattr(u8_bills, "is_configured", lambda: True)
    monkeypatch.setattr(u8_inventory, "search", lambda **_kwargs: ([_stock()], False))
    monkeypatch.setattr(u8_inventory, "get_selected", lambda _keys: [_stock()])
    monkeypatch.setattr(
        windows_label_print,
        "dispatch",
        lambda **_kwargs: {
            "output_dir": "C:\\Downloads\\标签打印",
            "files": [],
        },
    )
    monkeypatch.setattr(bill_printing, "confirm_run", lambda *_args, **_kwargs: 2)

    queried = client.get("/api/u8/stock?warehouse=W1")
    assert queried.status_code == 200
    assert queried.get_json()["stock"][0]["item_code"] == "ITEM-1"
    printed = client.post(
        "/api/u8/stock/print",
        json={
            "template_id": template_id,
            "printer": "Microsoft Print to PDF",
            "lines": [
                {
                    "source": "position",
                    "stock_id": 17,
                    "item_code": "ITEM-1",
                    "batch": "B-1",
                    "quantity": 53,
                    "packaging": 50,
                }
            ],
            "include_remainder": True,
        },
        headers=csrf.headers(),
    )
    assert printed.status_code == 200
    result = printed.get_json()
    assert result["label_count"] == 2
    assert "printed" not in result
    with app.app_context():
        state = client_label_print.state_for(result["run_id"], 1)
    complete = client.post(
        f"/api/u8/print/{result['run_id']}/complete",
        json={
            "receipt": state["receipt"],
            "bundle_sha256": result["bundle_sha256"],
            "printer": "Microsoft Print to PDF",
            "printed": 2,
        },
        headers=csrf.headers(),
    )
    assert complete.status_code == 200
    assert complete.get_json()["printed"] == complete.get_json()["registered"] == 2
    manifest = bill_printing.load_run(result["run_id"], owner_id=1)
    assert len(manifest["bill_number"]) == 10
    assert manifest["records"][0]["goods_json"]["Attribute"]["batchNumber"] == "B-1"
