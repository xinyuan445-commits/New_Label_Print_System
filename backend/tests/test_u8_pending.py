"""Quantity progress across partial printing, legacy ambiguity and PDA moves."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.services import bill_printing, u8_bills
from app.services.u8_pending import calculate_progress


def detail(
    id: int = 11, item: str = "A", batch: str = "B", quantity: str = "100"
) -> dict[str, Any]:
    return {
        "单据ID": 1,
        "明细ID": id,
        "存货编码": item,
        "批号": batch,
        "数量": quantity,
        "仓库编码": "W",
        "货位编码": "P",
    }


def candidate(type: str = "CGRK", id: int = 1) -> dict[str, Any]:
    return {"bill_type": type, "ID": id, "单据号": "RK001", "单据日期": "2026-10-08"}


def label(
    row: dict[str, Any],
    quantity: str = "50",
    sn: str = "S1",
    *,
    exact: bool = True,
    type: str = "CGRK",
    id: int = 1,
) -> dict[str, Any]:
    order: dict[str, Any] = {"documentNumber": "RK001", "orderType": "RK"}
    if exact:
        order["labelPrintSource"] = {"billType": type, "billId": id, "detailId": str(row["明细ID"])}
    return {
        "order": order,
        "goods": {
            "code": row["存货编码"],
            "warehouseCode": row["仓库编码"],
            "Attribute": {"batchNumber": row["批号"]},
            "inventory": {"storageLocationCode": row["货位编码"]},
        },
        "barcode": f"008|{row['存货编码']}|{row['批号']}|{quantity}|{sn}",
        "sn": sn,
    }


def progress(
    rows: list[dict[str, Any]], labels: list[dict[str, Any]], type: str = "CGRK"
) -> list[dict[str, Any]]:
    return calculate_progress([candidate(type)], {(type, 1): rows}, labels, {})[(type, 1)]


def test_partial_print_retains_remaining_rows_and_original_indexes() -> None:
    rows = [detail(), detail(12, "C", quantity="10")]
    result = progress(rows, [label(rows[0])])
    assert [
        (row["明细ID"], row["已打印数量"], row["待打印数量"], row["打印状态"]) for row in result
    ] == [
        (11, "50", "50", "部分打印"),
        (12, "0", "10", "未打印"),
    ]
    complete = progress(rows, [label(rows[0], "100"), label(rows[1], "10", "S2")])
    assert all(row["打印状态"] == "已打印" for row in complete)


def test_repeat_join_counts_once_but_conflicting_sn_requires_review() -> None:
    row = detail()
    original = label(row)
    assert progress([row], [original, original])[0]["已打印数量"] == "50"
    conflict = label(row, "60")
    result = progress([row], [original, conflict])[0]
    assert result["已打印数量"] == "0"
    assert result["打印状态"] == "待核对"


@pytest.mark.parametrize(
    "change", ["item", "batch", "warehouse", "location", "sn", "quantity", "goods"]
)
def test_contradictory_trace_is_never_counted(change: str) -> None:
    row = detail()
    record = label(row)
    if change == "item":
        record["goods"]["code"] = "OTHER"
    elif change == "batch":
        record["goods"]["Attribute"]["batchNumber"] = "OTHER"
    elif change == "warehouse":
        record["goods"]["warehouseCode"] = "OTHER"
    elif change == "location":
        record["goods"]["inventory"]["storageLocationCode"] = "OTHER"
    elif change == "sn":
        record["sn"] = "OTHER"
    elif change == "quantity":
        record["barcode"] = "008|A|B|NaN|S1"
    else:
        record["goods"] = {}
    result = progress([row], [record])[0]
    assert result["已打印数量"] == "0"
    assert result["打印状态"] == "待核对"


def test_same_number_different_bill_type_or_id_does_not_hide_new_bill() -> None:
    row = detail()
    candidates = [candidate(), candidate("OtherIN", 2)]
    rows = calculate_progress(
        candidates, {("CGRK", 1): [row], ("OtherIN", 2): [row]}, [label(row, "100")], {}
    )
    assert rows[("CGRK", 1)][0]["打印状态"] == "已打印"
    assert rows[("OtherIN", 2)][0]["打印状态"] == "未打印"
    assert progress([row], [label(row, "100", id=99)])[0]["打印状态"] == "未打印"
    ambiguous = calculate_progress(
        candidates, {("CGRK", 1): [row], ("OtherIN", 2): [row]}, [label(row, exact=False)], {}
    )
    assert all(result[0]["打印状态"] == "待核对" for result in ambiguous.values())


def test_legacy_unique_goods_can_count_but_identical_rows_require_review() -> None:
    row = detail()
    assert progress([row], [label(row, exact=False)])[0]["已打印数量"] == "50"
    ambiguous = progress([row, detail(12)], [label(row, exact=False)])
    assert all(item["打印状态"] == "待核对" for item in ambiguous)
    exact = progress([row, detail(12)], [label(row)])
    assert exact[0]["已打印数量"] == "50"
    assert exact[1]["打印状态"] == "未打印"


def test_legacy_cannot_match_when_candidate_scope_is_incomplete() -> None:
    row = detail()
    result = calculate_progress(
        [candidate()],
        {("CGRK", 1): [row]},
        [label(row, exact=False)],
        {},
        legacy_scope_complete=False,
    )
    assert result[("CGRK", 1)][0]["打印状态"] == "待核对"


def test_whole_and_split_pda_goods_exempt_only_correct_quantities() -> None:
    rows = [detail(quantity="95"), detail(12, "C", quantity="10")]
    movement = {
        ("DBD", "RK001"): [
            ([("008|A|B|50|OLD1", Decimal(50))], "50"),
            ([("008|A|B|50|OLD2", Decimal(50))], "45"),
        ]
    }
    result = calculate_progress([candidate("DBD")], {("DBD", 1): rows}, [], movement)[("DBD", 1)]
    assert result[0]["需打印数量"] == result[0]["待打印数量"] == "45"
    assert result[1]["待打印数量"] == "10"
    original = label(rows[0], "45", type="DBD")
    result = calculate_progress([candidate("DBD")], {("DBD", 1): rows}, [original], movement)[
        ("DBD", 1)
    ]
    assert result[0]["打印状态"] == "已打印"
    assert result[1]["打印状态"] == "未打印"


def test_outbound_only_negative_lines_need_labels() -> None:
    result = progress(
        [detail(quantity="-100"), detail(12, quantity="100")],
        [label(detail(), "50", type="XSCK")],
        "XSCK",
    )
    assert result[0]["待打印数量"] == "50"
    assert result[1]["打印状态"] == "无需打印"


def test_new_trace_stores_stable_bill_and_detail_identity() -> None:
    rows, records = bill_printing.build_label_plan(
        bill_type="CGRK",
        bill_id=1,
        bill_number="RK001",
        details=[detail()],
        selections=[{"index": 0, "quantity": "50", "packaging": "50"}],
        include_remainder=True,
        username="tester",
    )
    assert records[0]["order_json"]["labelPrintSource"] == {
        "billType": "CGRK",
        "billId": 1,
        "detailId": "11",
        "lineNumber": 1,
    }
    assert rows[0]["行号"] == "1"


def test_batch_detail_queries_preserve_ids_order_and_bound_values() -> None:
    for code, _ in u8_bills.BILL_TYPES:
        sql = u8_bills.pending_details_query(code)
        assert "a.ID AS 单据ID" in sql and "AutoID AS 明细ID" in sql
        assert "a.ID IN (@MainID)" in sql
        bound, values = u8_bills.bind_query(sql, {"MainID": [1, 2]})
        assert "a.ID IN (?,?)" in bound
        assert values == [1, 2]
        assert bound.endswith("ORDER BY 单据ID, 明细ID")


def test_platform_reader_requires_all_three_links_and_ignores_mutated_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    import pyodbc

    record = label(detail(), "100")

    class Cursor:
        def execute(self, sql: str, *_params: object) -> list[tuple[object, ...]]:
            if "FROM TraceBackOrder WHERE" in sql:
                return [(json.dumps(record["order"]), "ORDER", "打印平台")]
            assert "c.sn, g.[json]" in sql and "c.[sum]" not in sql
            return [("ORDER", record["barcode"], "S1", json.dumps(record["goods"]))]

    class Connection:
        timeout = 0

        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            pass

    monkeypatch.setattr(u8_bills, "get_connection_string", lambda: "Database=ufdata_998_2021")
    monkeypatch.setattr(pyodbc, "connect", lambda *_args, **_kwargs: Connection())
    labels, _movement = u8_bills._read_trace_state([candidate()])
    assert progress([detail()], labels)[0]["打印状态"] == "已打印"


def test_nonfinite_pda_quantity_is_reviewable_not_a_query_crash() -> None:
    assert u8_bills._movement_group([("008|A|B|NaN|S1", Decimal(50))], "50")[3] == "待核对"
    assert u8_bills._movement_group([("008|A|B|50|S1", Decimal("NaN"))], "50")[3] == "待核对"


def test_changed_detail_id_cannot_reuse_the_displayed_row_index() -> None:
    with pytest.raises(bill_printing.BillPrintError, match="bill_changed"):
        bill_printing.build_label_plan(
            bill_type="CGRK",
            bill_id=1,
            bill_number="RK001",
            details=[detail(12)],
            selections=[{"index": 0, "detail_id": "11", "quantity": "50", "packaging": "50"}],
            include_remainder=True,
            username="tester",
        )
