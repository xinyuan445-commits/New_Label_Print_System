"""U8 query boundary and personal bill selection."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.db.session import get_session
from app.services import bill_printing, u8_bills, windows_label_print
from app.services.users import create_user
from tests.conftest import CsrfHelper


def _login(app: Flask, client: FlaskClient, csrf: CsrfHelper) -> None:
    with app.app_context():
        create_user(
            get_session(), email="operator@example.com", plain_password="initialPassword123"
        )
    response = client.post(
        "/api/auth/login",
        json={"email": "operator@example.com", "password": "initialPassword123"},
        headers=csrf.headers(),
    )
    assert response.status_code == 200


def test_supported_bills_have_header_and_detail_queries() -> None:
    assert len(u8_bills.BILL_TYPES) == 11
    for code, _name in u8_bills.BILL_TYPES:
        assert "SELECT" in u8_bills.load_query(code, "main")
        assert "SELECT" in u8_bills.load_query(code, "detail")
    with pytest.raises(u8_bills.UnsupportedBillTypeError):
        u8_bills.load_query("unknown", "main")


def test_inventory_count_uses_positive_actual_count_not_book_quantity() -> None:
    assert ("PDD", "盘点单") in u8_bills.BILL_TYPES
    details = u8_bills.load_query("PDD", "detail")
    assert "b.iCVCQuantity AS 数量" in details
    assert "b.iCVCQuantity > 0" in details
    assert "iCVQuantity" not in details
    pending = u8_bills.pending_bills_query(["PDD"])
    assert "FROM CheckVouch a" in pending
    assert "d.iCVCQuantity > 0" in pending


def test_pending_query_includes_negative_outbound_and_excludes_positive_outbound() -> None:
    sql = u8_bills.pending_bills_query(["CGRK", "XSCK", "OtherOUT", "CLCK", "DBD", "HWTZ"])
    assert "d.Class = '01' AND d.ID = r.ID AND d.iQuantity > 0" in sql
    for code in ("32", "09", "11"):
        assert f"d.Class = '{code}' AND d.ID = r.ID AND d.iQuantity < 0" in sql
    assert "TransVouchs d WHERE d.ID = a.ID AND d.iTVQuantity > 0" in sql
    assert "AdjustPVouchs d WHERE d.ID = a.ID AND d.iQuantity > 0" in sql
    with pytest.raises(u8_bills.UnsupportedBillTypeError):
        u8_bills.pending_bills_query(["CGRK", "unsafe"])


def test_movement_requires_new_label_only_for_split_or_unknown_scan() -> None:
    assert u8_bills._movement_reason([([("998|item|batch|50|sn", Decimal(50))], 50)]) is None
    assert (
        u8_bills._movement_reason(
            [
                (
                    [
                        ("998|item|batch|20|sn1", Decimal(20)),
                        ("998|item|batch|24|sn2", Decimal(24)),
                    ],
                    44,
                )
            ]
        )
        is None
    )
    assert u8_bills._movement_reason([([("998|item|batch|30|sn", Decimal(9))], 9)]) is None
    assert (
        u8_bills._movement_reason([([("998|item|batch|50|sn", Decimal(50))], 45)]) == "零散需补打"
    )
    assert u8_bills._movement_reason([]) == "无PDA标签记录"
    assert u8_bills._movement_reason([([("bad-code", None)], 45)]) == "标签数量待核对"
    assert (
        u8_bills._movement_reason([([("998|item|batch|20|sn", Decimal(20))], 44)])
        == "标签数量待核对"
    )


def test_prior_material_issue_can_leave_a_whole_label_for_transfer() -> None:
    barcode = "998|item|batch|30|sn"
    remaining = u8_bills._remaining_before_events(
        [
            (1, barcode, "30", "打印平台"),
            (2, barcode, "-21", "材料出库"),
            (3, barcode, "0", "调拨单"),
        ]
    )
    assert remaining[3] == Decimal(9)
    assert u8_bills._movement_reason([([(barcode, remaining[3])], 9)]) is None


def test_movement_label_details_show_original_and_moved_quantities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        u8_bills,
        "_read_trace_state",
        lambda _rows: (set(), {("DBD", "D001"): [([("998|ITEM|BATCH|50|SN", Decimal(50))], 45)]}),
    )
    labels = u8_bills.list_movement_labels("DBD", "D001")
    assert labels == [
        {
            "存货编码": "ITEM",
            "批号": "BATCH",
            "原标签数量": "50",
            "标签剩余": "50",
            "本次数量": "45",
            "状态": "零散",
        }
    ]


def test_pending_list_excludes_printed_and_full_pda_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = [
        {"bill_type": "CGRK", "ID": 1, "单据号": "IN-1", "单据日期": "2026-07-01"},
        {"bill_type": "DBD", "ID": 2, "单据号": "MOVE-FULL", "单据日期": "2026-07-02"},
        {"bill_type": "DBD", "ID": 3, "单据号": "MOVE-SPLIT", "单据日期": "2026-07-03"},
    ]
    monkeypatch.setattr(u8_bills, "_fetch", lambda *_args, **_kwargs: (candidates, False))
    from tests.test_u8_pending import detail, label

    monkeypatch.setattr(
        u8_bills,
        "_pending_details",
        lambda _rows: (
            {
                ("CGRK", 1): [detail(quantity="50")],
                ("DBD", 2): [detail(item="item", batch="batch", quantity="50")],
                ("DBD", 3): [detail(item="item", batch="batch", quantity="45")],
            },
            False,
        ),
    )
    monkeypatch.setattr(
        u8_bills,
        "_read_trace_state",
        lambda _rows: (
            [{**label(detail(), "50"), "order": {"documentNumber": "IN-1", "orderType": "IN"}}],
            {
                ("DBD", "MOVE-FULL"): [([("998|item|batch|50|sn", Decimal(50))], 50)],
                ("DBD", "MOVE-SPLIT"): [([("998|item|batch|50|sn", Decimal(50))], 45)],
            },
        ),
    )
    rows, total, truncated = u8_bills.list_pending_bills(
        ["CGRK", "DBD"], start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)
    )
    assert total == 1
    assert truncated is False
    assert rows[0]["单据号"] == "MOVE-SPLIT"
    assert rows[0]["原因"] == "待打印"
    assert rows[0]["待打印明细数"] == 1


def test_query_parameters_are_bound_in_occurrence_order() -> None:
    sql = u8_bills.load_query("CGRK", "main")
    code = "%' OR 1=1 --"
    query, values = u8_bills.bind_query(
        sql,
        {"Code": code, "StartDate": date(2026, 1, 1), "EndDate": date(2026, 1, 31)},
    )
    assert code not in query
    assert "@Code" not in query
    assert values == [code, code, date(2026, 1, 1), date(2026, 1, 31)]


def test_only_test_account_database_is_allowed() -> None:
    u8_bills.validate_database("Driver={ODBC Driver 18 for SQL Server};Database=ufdata_998_2021")
    with pytest.raises(u8_bills.U8DatabaseMismatchError):
        u8_bills.validate_database("Server=production;Database=UFDATA_008_2021")
    with pytest.raises(u8_bills.U8DatabaseMismatchError):
        u8_bills.validate_database("DSN=production")
    with pytest.raises(u8_bills.U8DatabaseMismatchError):
        u8_bills.validate_database("Database=ufdata_998_2021;Database=UFDATA_008_2021")


def test_production_read_account_requires_explicit_setting_and_forbids_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("U8_DATABASE", "UFDATA_008_2021")
    connection = "Driver={ODBC Driver 17 for SQL Server};Database=ufdata_008_2021"
    assert u8_bills.query_only()
    u8_bills.validate_database(connection)
    for bad in (
        "Database=ufdata_998_2021",
        "Database=ufdata_008_2021;Database=other",
        "DSN=other;Database=ufdata_008_2021",
    ):
        with pytest.raises(u8_bills.U8DatabaseMismatchError):
            u8_bills.validate_database(bad)
    with pytest.raises(u8_bills.U8DatabaseMismatchError):
        u8_bills.validate_database(connection, for_write=True)
    monkeypatch.setattr(bill_printing, "get_connection_string", lambda: connection)
    with pytest.raises(u8_bills.U8DatabaseMismatchError):
        bill_printing._write_connection_string()
    monkeypatch.setenv("U8_DATABASE", "another_database")
    with pytest.raises(u8_bills.U8DatabaseMismatchError):
        u8_bills.database_name()


def test_production_mode_blocks_dispatch_and_registration(
    app: Flask,
    client: FlaskClient,
    csrf: CsrfHelper,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(app, client, csrf)
    monkeypatch.setenv("U8_DATABASE", "ufdata_008_2021")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Production query mode must not dispatch or register labels")

    monkeypatch.setattr(windows_label_print, "dispatch", forbidden)
    monkeypatch.setattr(bill_printing, "confirm_run", forbidden)
    assert client.get("/api/u8/bill-types").get_json()["query_only"] is True
    for endpoint in (
        "/api/u8/print",
        "/api/u8/stock/print",
        "/api/u8/reprint",
        "/api/u8/print/old-run/register",
    ):
        response = client.post(endpoint, json={}, headers=csrf.headers())
        assert response.status_code == 403
        assert response.get_json()["error"] == "u8_read_only"


def test_barcode_account_code_is_separate_from_database_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("U8_BARCODE_ACCOUNT_CODE", raising=False)
    assert u8_bills.barcode_account_code() == "008"
    monkeypatch.setenv("U8_BARCODE_ACCOUNT_CODE", "998")
    assert u8_bills.barcode_account_code() == "998"
    monkeypatch.setenv("U8_BARCODE_ACCOUNT_CODE", "UFDATA_008_2021")
    with pytest.raises(ValueError):
        u8_bills.barcode_account_code()


@pytest.mark.parametrize("database", ["ufdata_998_2021", "ufdata_008_2021"])
def test_env_builds_selected_connection_without_opening_database(
    monkeypatch: pytest.MonkeyPatch,
    database: str,
) -> None:
    import pyodbc

    monkeypatch.setenv("U8_SERVER", "test-sql-host")
    monkeypatch.setenv("U8_USER", "test-user")
    monkeypatch.setenv("U8_PASSWORD", "part;with}chars")
    monkeypatch.setenv("U8_DATABASE", database)
    monkeypatch.setattr(pyodbc, "drivers", lambda: ["ODBC Driver 17 for SQL Server"])
    connection = u8_bills.get_connection_string()
    assert "Driver={ODBC Driver 17 for SQL Server}" in connection
    assert f"Server=test-sql-host;Database={database}" in connection
    assert "ApplicationIntent=ReadOnly" in connection
    assert "Pwd={part;with}}chars}" in connection


def test_blank_component_settings_do_not_fall_back_to_old_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("U8_SERVER", "")
    monkeypatch.setenv("U8_USER", "")
    monkeypatch.setenv("U8_PASSWORD", "")
    monkeypatch.setenv("U8_ODBC_CONNECTION_STRING", "Server=old;Database=UFDATA_008_2021")
    assert not u8_bills.is_configured()
    assert u8_bills.get_connection_string() == ""


def test_bill_endpoints_require_login(client: FlaskClient) -> None:
    assert client.get("/api/u8/bill-types").status_code == 401
    assert client.get("/api/u8/bills").status_code == 401
    assert client.get("/api/u8/pending-bills").status_code == 401
    assert client.get("/api/u8/pda-labels?bill_type=DBD&bill_number=D001").status_code == 401


def test_favorites_persist_and_cap_at_eight(
    app: Flask, client: FlaskClient, csrf: CsrfHelper
) -> None:
    _login(app, client, csrf)
    favorites = ["CGRK", "XSCK", "CLCK", "DBD", "CGDH", "CCPRK", "OtherIN", "OtherOUT"]
    saved = client.put(
        "/api/u8/favorites",
        json={"bill_types": favorites},
        headers=csrf.headers(),
    )
    assert saved.status_code == 200
    assert client.get("/api/u8/bill-types").get_json()["favorites"] == favorites
    rejected = client.put(
        "/api/u8/favorites",
        json={"bill_types": [*favorites, "XTZY"]},
        headers=csrf.headers(),
    )
    assert rejected.status_code == 400
    assert client.get("/api/u8/bill-types").get_json()["favorites"] == favorites


@pytest.mark.parametrize("favorites", [[], ["CGRK", "XSCK"]])
def test_pending_bills_include_all_types_regardless_of_favorites(
    app: Flask,
    client: FlaskClient,
    csrf: CsrfHelper,
    monkeypatch: pytest.MonkeyPatch,
    favorites: list[str],
) -> None:
    _login(app, client, csrf)
    client.put(
        "/api/u8/favorites",
        json={"bill_types": favorites},
        headers=csrf.headers(),
    )
    monkeypatch.setenv("U8_ODBC_CONNECTION_STRING", "test-connection")
    seen: dict[str, object] = {}

    def fake_list_pending(
        bill_types: list[str], *, start_date: date, end_date: date, limit: int = 100
    ) -> tuple[list[dict[str, object]], int, bool]:
        seen.update(types=bill_types, start=start_date, end=end_date, limit=limit)
        return [{"bill_type": "XSCK", "ID": 7, "单据号": "R001"}], 1, False

    monkeypatch.setattr(u8_bills, "list_pending_bills", fake_list_pending)
    response = client.get("/api/u8/pending-bills")
    assert response.status_code == 200
    assert response.get_json()["total"] == 1
    assert response.get_json()["bills"][0]["bill_type"] == "XSCK"
    assert seen["types"] == [code for code, _ in u8_bills.BILL_TYPES]
    types = client.get("/api/u8/bill-types").get_json()
    assert types["favorites"] == favorites
    assert {"code": "PDD", "name": "盘点单"} in types["bill_types"]
    assert (seen["end"] - seen["start"]).days == 29  # type: ignore[operator]


def test_pda_label_endpoint_is_read_only_and_restricted_to_movement_types(
    app: Flask, client: FlaskClient, csrf: CsrfHelper, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login(app, client, csrf)
    monkeypatch.setenv("U8_ODBC_CONNECTION_STRING", "test-connection")
    monkeypatch.setattr(
        u8_bills,
        "list_movement_labels",
        lambda bill_type, bill_number: [{"状态": "零散", "本次数量": "45"}],
    )
    response = client.get("/api/u8/pda-labels?bill_type=DBD&bill_number=D001")
    assert response.status_code == 200
    assert response.get_json()["labels"][0]["本次数量"] == "45"
    assert client.get("/api/u8/pda-labels?bill_type=XSCK&bill_number=D001").status_code == 400


def test_search_uses_selected_bill_type_and_dates(
    app: Flask, client: FlaskClient, csrf: CsrfHelper, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login(app, client, csrf)
    monkeypatch.setenv("U8_ODBC_CONNECTION_STRING", "test-connection")
    seen: dict[str, object] = {}

    def fake_list_bills(
        bill_type: str, *, code: str, start_date: date, end_date: date
    ) -> tuple[list[dict[str, object]], bool]:
        seen.update(bill_type=bill_type, code=code, start_date=start_date, end_date=end_date)
        return [{"ID": 7, "单据号": "R001"}], False

    monkeypatch.setattr(u8_bills, "list_bills", fake_list_bills)
    response = client.get(
        "/api/u8/bills?bill_type=CGRK&code=R001&start_date=2026-01-01&end_date=2026-01-31"
    )
    assert response.status_code == 200
    assert response.get_json()["bills"][0]["单据号"] == "R001"
    assert seen == {
        "bill_type": "CGRK",
        "code": "R001",
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 31),
    }
