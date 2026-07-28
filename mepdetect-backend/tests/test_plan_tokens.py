"""
Token mining tests.

A panel schedule states its ratings as text; the miner has to read them, keep
their positions in the rendered pixel space, and hang them off the right
detections. Built on a real PDF so the word extraction path is the one
production takes.
"""

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plan_tokens
from circuit_tracer import PANEL_KEYWORDS

DPI = 150
SCALE = DPI / 72.0


@pytest.fixture(scope="module")
def sheet_tokens(tmp_path_factory):
    """Tokens of a one-panel sheet with ratings printed beside the panel."""

    directory = tmp_path_factory.mktemp("tokens")
    pdf_path = directory / "panel.pdf"

    document = fitz.open()
    page = document.new_page(width=612, height=792)

    # The panel and its nameplate data, clustered top-left
    page.insert_text((72, 100), "LP-1", fontsize=10)
    page.insert_text((72, 115), "75 KVA", fontsize=8)
    page.insert_text((72, 130), "208Y/120 V", fontsize=8)
    page.insert_text((72, 145), "225 A", fontsize=8)
    page.insert_text((72, 160), "10 KAIC", fontsize=8)

    # Sheet furniture that must not read as ratings
    page.insert_text((400, 700), "E0001-2", fontsize=8)
    page.insert_text((400, 715), "GENERAL NOTES", fontsize=8)

    document.save(str(pdf_path))
    document.close()

    return plan_tokens.extract_page_tokens(pdf_path, 1, DPI)


def test_ratings_and_equipment_found(sheet_tokens):
    by_kind = {}
    for token in sheet_tokens:
        by_kind.setdefault(token["kind"], set()).add(token["value"])

    assert by_kind["equipment"] == {"LP-1"}
    assert by_kind["kva"] == {"75"}
    assert by_kind["voltage"] == {"208Y/120"}
    assert by_kind["amps"] == {"225"}
    assert by_kind["kaic"] == {"10"}


def test_sheet_furniture_ignored(sheet_tokens):
    values = {token["value"] for token in sheet_tokens}
    assert "E0001-2" not in values
    assert not any("NOTES" in v for v in values)


def test_positions_are_rendered_pixels(sheet_tokens):
    tag = next(t for t in sheet_tokens if t["value"] == "LP-1")
    # Inserted at x=72 pt; the rendered pixel position scales with the DPI.
    assert tag["x"] == pytest.approx(72 * SCALE, abs=20 * SCALE)
    assert tag["y"] == pytest.approx(100 * SCALE, abs=20 * SCALE)


def _panel_detection(cx, cy, size=100.0):
    return {
        "class_name": "panel",
        "confidence": 0.9,
        "bbox": {
            "x1": cx - size / 2, "y1": cy - size / 2,
            "x2": cx + size / 2, "y2": cy + size / 2,
            "width": size, "height": size,
            "center_x": cx, "center_y": cy,
        },
    }


def test_ratings_attach_to_the_panel_beside_them(sheet_tokens):
    tag = next(t for t in sheet_tokens if t["value"] == "LP-1")
    near = _panel_detection(tag["x"], tag["y"] + 40)
    far = _panel_detection(tag["x"] + 4000, tag["y"] + 4000)
    receptacle = dict(_panel_detection(tag["x"], tag["y"]), class_name="receptacle")

    annotated = plan_tokens.attach_ratings(
        [near, far, receptacle], sheet_tokens, PANEL_KEYWORDS
    )

    assert annotated == 1
    assert near["ratings"]["kva"]["value"] == "75"
    assert near["ratings"]["voltage"]["value"] == "208Y/120"
    assert "ratings" not in far
    assert "ratings" not in receptacle


def test_summarize_tokens_unions_sheets():
    sheets = [
        [{"kind": "kva", "value": "75"}, {"kind": "equipment", "value": "LP-1"}],
        [{"kind": "kva", "value": "45"}, {"kind": "kva", "value": "75"}],
    ]
    summary = plan_tokens.summarize_tokens(sheets)
    assert summary == {"equipment": ["LP-1"], "kva": ["45", "75"]}


def test_scan_words_joins_split_ratings():
    words = [
        {"text": "75", "bbox": [0, 0, 10, 8], "x": 5, "y": 4,
         "line": (0, 0), "order": 0},
        {"text": "KVA", "bbox": [12, 0, 30, 8], "x": 21, "y": 4,
         "line": (0, 0), "order": 1},
    ]
    tokens = plan_tokens.scan_words(words)
    assert [(t["kind"], t["value"]) for t in tokens] == [("kva", "75")]
