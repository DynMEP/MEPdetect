"""
OCR tag-reading tests.

Sheets plotted from older CAD carry their circuit tags as curves, not text, so
the tags are visible but unreadable. The OCR fallback covers that. tesseract is
not installed in this environment, so these stub it out and pin the parts that
are ours: where the crops are taken, how results are filtered, and that the
coordinates come back in the full sheet's frame rather than the crop's.
"""

import sys
import types
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf_geometry import ocr_tags_near


@pytest.fixture
def sheet(tmp_path):
    image = np.full((1200, 1600), 255, np.uint8)
    path = tmp_path / "sheet.png"
    cv2.imwrite(str(path), image)
    return path


def _stub_tesseract(monkeypatch, words, record=None):
    """Install a fake pytesseract that returns fixed words for every crop."""

    module = types.ModuleType("pytesseract")
    module.Output = types.SimpleNamespace(DICT="dict")

    def image_to_data(crop, config=None, output_type=None):
        if record is not None:
            record.append(crop.shape)
        return {
            "text": [w[0] for w in words],
            "conf": [w[1] for w in words],
            "left": [w[2] for w in words],
            "top": [w[3] for w in words],
            "width": [w[4] for w in words],
            "height": [w[5] for w in words],
        }

    module.image_to_data = image_to_data
    monkeypatch.setitem(sys.modules, "pytesseract", module)


def test_missing_tesseract_degrades_to_no_tags(sheet, monkeypatch):
    """Tag reading is optional; its absence must not fail the job."""

    # A None entry in sys.modules makes the import raise, which is what a
    # deployment without the package looks like.
    monkeypatch.setitem(sys.modules, "pytesseract", None)

    assert ocr_tags_near(sheet, [(400, 400)]) == []


def test_tag_coordinates_come_back_in_sheet_space(sheet, monkeypatch):
    _stub_tesseract(monkeypatch, [("A-12", 90, 30, 20, 44, 18)])

    found = ocr_tags_near(sheet, [(800, 600)], radius=200)

    assert len(found) == 1
    # Crop starts at (600, 400), so the word sits at (630, 420) on the sheet.
    assert found[0]["bbox"][0] == 630
    assert found[0]["bbox"][1] == 420
    assert found[0]["x"] == pytest.approx(652)
    assert found[0]["source"] == "ocr"


def test_non_tags_and_low_confidence_are_dropped(sheet, monkeypatch):
    _stub_tesseract(monkeypatch, [
        ("A-12", 90, 10, 10, 40, 16),     # kept
        ("BEDROOM", 95, 10, 40, 80, 16),  # not a circuit tag
        ("CMP-1CE4A", 95, 10, 70, 90, 16),  # equipment id
        ("B-3", 20, 10, 100, 40, 16),     # too unsure to put on a takeoff
    ])

    found = ocr_tags_near(sheet, [(400, 400)])

    assert [entry["text"] for entry in found] == ["A-12"]


def test_only_windows_around_the_given_points_are_read(sheet, monkeypatch):
    """
    OCR runs per homerun, never over the whole sheet: at plotting resolution
    a full-page pass would take longer than the rest of the job.
    """

    crops = []
    _stub_tesseract(monkeypatch, [("A-12", 90, 5, 5, 40, 16)], record=crops)

    ocr_tags_near(sheet, [(400, 400), (900, 700)], radius=150)

    assert len(crops) == 2
    assert all(shape == (300, 300) for shape in crops)


def test_crops_are_clipped_to_the_sheet(sheet, monkeypatch):
    crops = []
    _stub_tesseract(monkeypatch, [("A-12", 90, 5, 5, 40, 16)], record=crops)

    ocr_tags_near(sheet, [(10, 10)], radius=200)

    assert crops == [(210, 210)]
