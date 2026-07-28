"""
Takeoff export tests: DXF overlay and PDF report.

The DXF has to open in CAD with the takeoff on its own layers, in real units
when the job was calibrated and with Y turned the right way up. The PDF has
to simply be a well-formed report carrying the numbers.
"""

import asyncio
import sys
import zipfile
from pathlib import Path

import cv2
import ezdxf
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from result_exporter import ResultExporter

SHEET_W, SHEET_H = 400, 200


def _detection(sheet, x1, y1, x2, y2, class_name="panel", ratings=None):
    det = {
        "sheet": sheet,
        "class_name": class_name,
        "confidence": 0.9,
        "bbox": {
            "x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2),
            "width": float(x2 - x1), "height": float(y2 - y1),
            "center_x": (x1 + x2) / 2.0, "center_y": (y1 + y2) / 2.0,
        },
    }
    if ratings:
        det["ratings"] = ratings
    return det


@pytest.fixture
def results(tmp_path):
    """A calibrated one-sheet job with two detections and a homerun."""

    image_path = tmp_path / "plan_page_1.png"
    cv2.imwrite(str(image_path),
                np.full((SHEET_H, SHEET_W), 255, np.uint8))

    return {
        "total_detections": 2,
        "confidence_avg": 0.88,
        "num_images": 1,
        "processing_time": 1.5,
        "class_counts": {"panel": 1, "receptacle": 1},
        "calibration": {"units": "feet", "units_per_pixel": 0.1},
        "sheets": [{"name": "plan_page_1.png", "image_path": str(image_path)}],
        "detections": [
            _detection("plan_page_1.png", 100, 40, 140, 80,
                       ratings={"kva": {"value": "75", "distance": 12.0}}),
            _detection("plan_page_1.png", 300, 120, 320, 140,
                       class_name="receptacle"),
        ],
        "circuits": [{
            "sheet": "plan_page_1.png",
            "nets": [],
            "circuits": [],
            "tag_circuits": [],
            "homeruns": [{"x": 200.0, "y": 100.0, "circuit_tag": "LP1-2",
                          "conductor_count": 3}],
            "unconnected_symbols": [],
        }],
        "circuit_summary": {"sheets_traced": 1, "homeruns": 1},
        "tokens": {"kva": ["75"], "equipment": ["LP-1"]},
        "reconciliation": {
            "findings": [{"item": "panel LP1", "severity": "MATCH",
                          "expected": "LP1", "found": "LP1", "note": "ok"}],
            "counts": {"MATCH": 1},
        },
    }


def test_dxf_overlay_layers_and_units(results, tmp_path):
    path = ResultExporter()._export_dxf(results, tmp_path)
    assert path.suffix == ".dxf"

    doc = ezdxf.readfile(path)
    assert doc.header["$INSUNITS"] == 2  # feet
    for layer in ("MEPD-SYMBOL", "MEPD-LABEL", "MEPD-HOMERUN"):
        assert layer in doc.layers

    msp = doc.modelspace()
    boxes = msp.query("LWPOLYLINE[layer=='MEPD-SYMBOL']")
    assert len(boxes) == 2

    # First detection: x1=100 px at 0.1 ft/px -> 10 ft; y1=40 px on a 200 px
    # sheet flips to (200-40)*0.1 = 16 ft.
    points = {(round(p[0], 3), round(p[1], 3))
              for p in boxes[0].get_points("xy")}
    assert (10.0, 16.0) in points

    # Homerun marker and tag land on their layer, with the conductor count.
    assert len(msp.query("CIRCLE[layer=='MEPD-HOMERUN']")) == 1
    homerun_texts = [t.dxf.text for t in msp.query("TEXT[layer=='MEPD-HOMERUN']")]
    assert homerun_texts == ["LP1-2 (3c)"]

    # The panel label carries the rating read off the sheet.
    labels = [t.dxf.text for t in msp.query("TEXT[layer=='MEPD-LABEL']")]
    assert any("panel" in label and "75" in label for label in labels)


def test_dxf_multiple_sheets_zip(results, tmp_path):
    second = _detection("plan_page_2.png", 10, 10, 30, 30)
    results["detections"].append(second)

    path = ResultExporter()._export_dxf(results, tmp_path)
    assert path.suffix == ".zip"
    with zipfile.ZipFile(path) as zipf:
        assert len(zipf.namelist()) == 2


def test_uncalibrated_dxf_stays_in_pixels(results, tmp_path):
    del results["calibration"]
    path = ResultExporter()._export_dxf(results, tmp_path)

    doc = ezdxf.readfile(path)
    assert doc.header["$INSUNITS"] == 0

    boxes = doc.modelspace().query("LWPOLYLINE[layer=='MEPD-SYMBOL']")
    points = {(round(p[0], 3), round(p[1], 3))
              for p in boxes[0].get_points("xy")}
    assert (100.0, 160.0) in points  # unscaled, still flipped


def test_pdf_report_is_well_formed(results, tmp_path):
    path = ResultExporter()._export_pdf(results, tmp_path)

    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 1000


def test_export_dispatches_new_formats(results, tmp_path):
    files = asyncio.run(
        ResultExporter().export(results, tmp_path, ["dxf", "pdf"])
    )
    assert set(files) == {"dxf", "pdf"}
    assert Path(files["dxf"]).exists()
    assert Path(files["pdf"]).exists()
