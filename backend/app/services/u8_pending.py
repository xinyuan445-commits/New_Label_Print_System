"""Match confirmed original labels to U8 detail quantities without guessing rows."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from app.services.u8_bills import MovementGoods, _movement_group, barcode_account_code

BillKey = tuple[str, int]
OUTBOUND = {"XSCK", "OtherOUT", "CLCK"}
MOVEMENT = {"DBD", "HWTZ"}


def _text(value: object) -> str:
    return str(value or "").strip()


def _quantity(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (ValueError, ArithmeticError):
        return None


def _required(bill_type: str, row: dict[str, Any]) -> Decimal:
    value = _quantity(row.get("数量"))
    if value is None:
        return Decimal(0)
    return (
        -value
        if bill_type in OUTBOUND and value < 0
        else (value if bill_type not in OUTBOUND and value > 0 else Decimal(0))
    )


def _goods_matches(row: dict[str, Any], goods: dict[str, Any], parts: list[str]) -> bool:
    if (
        len(parts) != 5
        or _text(row.get("存货编码")) != parts[1]
        or _text(row.get("批号")) != parts[2]
    ):
        return False
    attribute = goods.get("Attribute")
    inventory = goods.get("inventory")
    if not isinstance(attribute, dict) or not isinstance(inventory, dict):
        return False
    return (
        _text(goods.get("code")) == parts[1]
        and _text(attribute.get("batchNumber")) == parts[2]
        and _text(goods.get("warehouseCode")) == _text(row.get("仓库编码"))
        and _text(inventory.get("storageLocationCode")) == _text(row.get("货位编码"))
    )


def calculate_progress(
    candidates: list[dict[str, Any]],
    details: dict[BillKey, list[dict[str, Any]]],
    printed: list[dict[str, Any]],
    movement: dict[tuple[str, str], list[MovementGoods]],
    *,
    legacy_scope_complete: bool = True,
) -> dict[BillKey, list[dict[str, Any]]]:
    """Return all original rows in their original order, enriched with print progress.

    Old labels only count when their bill and full goods identity select one row.
    Missing/contradictory identity stays visible for review. Only linked platform
    originals count; consumption balances and reprints cannot reduce this progress.
    """
    totals: dict[tuple[BillKey, int], Decimal] = defaultdict(Decimal)
    review: set[tuple[BillKey, int]] = set()
    by_number: dict[str, list[dict[str, Any]]] = defaultdict(list)
    required: dict[tuple[BillKey, int], Decimal] = {}
    for candidate in candidates:
        key = (str(candidate["bill_type"]), int(candidate["ID"]))
        by_number[str(candidate["单据号"])].append(candidate)
        for index, row in enumerate(details.get(key, [])):
            required[(key, index)] = _required(key[0], row)
            if _quantity(row.get("数量")) is None:
                review.add((key, index))

    # Whole PDA groups exempt their actual moved amount, never the entire bill.
    for candidate in candidates:
        key = (str(candidate["bill_type"]), int(candidate["ID"]))
        if key[0] not in MOVEMENT:
            continue
        rows = details.get(key, [])
        whole: dict[int, Decimal] = defaultdict(Decimal)
        moved_totals: dict[int, Decimal] = defaultdict(Decimal)
        for barcodes, moved_raw in movement.get((key[0], str(candidate["单据号"])), []):
            identities = {
                tuple(code.split("|")[1:3]) for code, _ in barcodes if len(code.split("|")) == 5
            }
            matches = [
                i
                for i, row in enumerate(rows)
                if (_text(row.get("存货编码")), _text(row.get("批号"))) in identities
            ]
            valid_codes = bool(barcodes) and all(len(code.split("|")) == 5 for code, _ in barcodes)
            if len(identities) != 1 or len(matches) != 1 or not valid_codes:
                review.update((key, i) for i in matches or range(len(rows)))
                continue
            index = matches[0]
            _original, _remaining, moved, status = _movement_group(barcodes, moved_raw)
            if moved is None or not moved.is_finite() or status == "待核对":
                review.add((key, index))
                continue
            moved_totals[index] += moved
            if status == "整托":
                whole[index] += moved
        for index, total in moved_totals.items():
            if total > required[(key, index)]:
                review.add((key, index))
        for index, amount in whole.items():
            if (key, index) not in review:
                required[(key, index)] -= amount

    # A duplicate join cannot count twice. Conflicting labels sharing an SN
    # invalidate every possible target instead of choosing the first result.
    labels: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in printed:
        parts = str(record.get("barcode") or "").split("|")
        serial = parts[4] if len(parts) == 5 else _text(record.get("sn"))
        labels[(parts[0], serial)].append(record)
    records_to_match: list[tuple[dict[str, Any], bool]] = []
    for copies in labels.values():
        unique = {json.dumps(copy, ensure_ascii=False, sort_keys=True): copy for copy in copies}
        records_to_match.extend((record, len(unique) != 1) for record in unique.values())
    for record, conflict in records_to_match:
        order = record.get("order") or {}
        goods = record.get("goods") or {}
        parts = str(record.get("barcode") or "").split("|")
        peers = by_number.get(_text(order.get("documentNumber")), [])
        if order.get("orderType") == "KC":
            continue
        source = order.get("labelPrintSource")
        exact = isinstance(source, dict)
        if isinstance(source, dict):
            peers = [
                peer
                for peer in peers
                if peer["bill_type"] == source.get("billType")
                and str(peer["ID"]) == str(source.get("billId"))
            ]
        legacy_ambiguous = not exact and (len(peers) != 1 or not legacy_scope_complete)
        affected: list[tuple[BillKey, int]] = []
        matched: list[tuple[BillKey, int]] = []
        for peer in peers:
            key = (str(peer["bill_type"]), int(peer["ID"]))
            for index, row in enumerate(details.get(key, [])):
                if required.get((key, index), Decimal(0)) <= 0:
                    continue
                # Retain an explicit ID match for review even if goods changed.
                id_match = isinstance(source, dict) and str(row.get("明细ID")) == str(
                    source.get("detailId")
                )
                item_match = (
                    len(parts) == 5
                    and _text(row.get("存货编码")) == parts[1]
                    and _text(row.get("批号")) == parts[2]
                )
                goods_match = _text(goods.get("code")) == _text(row.get("存货编码"))
                if id_match or item_match or goods_match or len(parts) != 5:
                    affected.append((key, index))
                if (not exact or id_match) and _goods_matches(row, goods, parts):
                    matched.append((key, index))
        label_amount = _quantity(parts[3]) if len(parts) == 5 else None
        valid = (
            len(parts) == 5
            and parts[0] == barcode_account_code()
            and bool(parts[4])
            and parts[4] == _text(record.get("sn"))
            and label_amount is not None
            and label_amount > 0
        )
        if conflict or legacy_ambiguous or not valid or len(matched) != 1 or label_amount is None:
            review.update(affected)
            continue
        totals[matched[0]] += label_amount

    result: dict[BillKey, list[dict[str, Any]]] = {}
    for key, rows in details.items():
        enriched = []
        for index, row in enumerate(rows):
            needed = required.get((key, index), Decimal(0))
            done = totals[(key, index)]
            if done > needed:
                review.add((key, index))
            remaining = max(needed - done, Decimal(0))
            status = (
                "待核对"
                if (key, index) in review
                else "无需打印"
                if needed <= 0
                else "已打印"
                if remaining <= 0
                else "部分打印"
                if done > 0
                else "未打印"
            )
            enriched.append(
                {
                    **row,
                    "需打印数量": str(needed),
                    "已打印数量": str(done),
                    "待打印数量": str(remaining),
                    "打印状态": status,
                }
            )
        result[key] = enriched
    return result
