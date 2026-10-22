# 작성: 2026-10-22 21:31 KST
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import rows as r  # noqa: E402

ITEMS = [
    {"name": "달걀", "quantity": "6개", "confidence": "high"},
    {"name": "우유", "quantity": "", "confidence": "low"},
    {"name": "당근", "quantity": "2개", "confidence": "medium"},
]


def test_make_rows_assigns_unique_increasing_ids():
    rows, next_id = r.make_rows(ITEMS, start_id=10)
    assert [x["id"] for x in rows] == [10, 11, 12]
    assert next_id == 13
    assert rows[1]["name"] == "우유" and rows[1]["confidence"] == "low"


def test_remove_middle_row_keeps_the_others():
    rows, _ = r.make_rows(ITEMS)
    left = r.remove_row(rows, rows[1]["id"])
    assert [x["name"] for x in left] == ["달걀", "당근"]


def test_remove_unknown_id_changes_nothing():
    rows, _ = r.make_rows(ITEMS)
    assert r.remove_row(rows, 999) == rows


def test_collect_uses_edited_widget_values_and_keeps_confidence():
    rows, _ = r.make_rows(ITEMS)
    values = {r.name_key(0): "  유정란 ", r.qty_key(0): "10개", r.qty_key(2): "3개"}
    got = r.collect_confirmed(rows, values)
    assert got[0] == {"name": "유정란", "quantity": "10개", "confidence": "high"}
    assert got[1] == {"name": "우유", "quantity": "", "confidence": "low"}
    assert got[2] == {"name": "당근", "quantity": "3개", "confidence": "medium"}


def test_collect_drops_rows_with_empty_name():
    rows, _ = r.make_rows(ITEMS)
    values = {r.name_key(1): "   "}
    assert [x["name"] for x in r.collect_confirmed(rows, values)] == ["달걀", "당근"]


def test_blank_row_added_by_user_is_confirmed_once_named():
    rows = [r.blank_row(5)]
    assert r.collect_confirmed(rows, {}) == []
    assert r.collect_confirmed(rows, {r.name_key(5): "두부", r.qty_key(5): "1모"}) == [
        {"name": "두부", "quantity": "1모", "confidence": "high"}
    ]


def test_collect_handles_none_values():
    rows, _ = r.make_rows(ITEMS)
    assert r.collect_confirmed(rows, {r.qty_key(0): None})[0]["quantity"] == ""
