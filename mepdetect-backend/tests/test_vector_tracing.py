"""
Vector tracing tests.

Builds a small PDF the way a drawing office would - conductors on their own
pen, an arrowhead sitting a short gap off the end of the homerun, three hash
marks for the conductor count, and the circuit tag as real text - then checks
that tracing recovers the circuit from the geometry rather than the pixels.
"""

import sys
from pathlib import Path

import fitz
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from circuit_tracer import CircuitTracer
from pdf_geometry import extract_sheet_geometry, is_circuit_tag, normalize_tag

DPI = 150
SCALE = DPI / 72.0

CONDUCTOR_PEN = 1.44
BACKGROUND_PEN = 0.48

PANEL = (60, 60, 130, 190)
DEVICES = [(250, 300), (400, 300), (400, 420)]
ARROW_TIP = (196, 232)
ARROW_GAP = 6.0


def _detection(class_name, box, confidence=0.9):
    x1, y1, x2, y2 = box
    return {
        "class_id": 0,
        "class_name": class_name,
        "confidence": confidence,
        "bbox": {
            "x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2),
            "width": float(x2 - x1), "height": float(y2 - y1),
            "center_x": (x1 + x2) / 2.0, "center_y": (y1 + y2) / 2.0,
        },
    }


def _box_px(centre, half=14):
    """Device box in rendered pixels, which is where detections live."""
    x, y = centre
    return ((x - half) * SCALE, (y - half) * SCALE,
            (x + half) * SCALE, (y + half) * SCALE)


@pytest.fixture(scope="module")
def sheet(tmp_path_factory):
    """A one-circuit sheet, drawn in PDF vectors."""

    directory = tmp_path_factory.mktemp("vector")
    pdf_path = directory / "branch.pdf"

    document = fitz.open()
    page = document.new_page(width=600, height=500)

    # Architectural background, on its own light pen: walls the wiring must
    # not be confused with.
    for y in (250, 470):
        page.draw_line(fitz.Point(40, y), fitz.Point(560, y),
                       color=(0, 0, 0), width=BACKGROUND_PEN)
    page.draw_rect(fitz.Rect(*PANEL), color=(0, 0, 0), width=BACKGROUND_PEN)
    for centre in DEVICES + [(196, 232)]:
        page.draw_circle(fitz.Point(*centre), 12, color=(0, 0, 0), width=BACKGROUND_PEN)

    # Branch wiring, on the conductor pen: device to device, then the homerun.
    page.draw_line(fitz.Point(*DEVICES[0]), fitz.Point(*DEVICES[1]),
                   color=(0, 0, 0), width=CONDUCTOR_PEN)
    page.draw_line(fitz.Point(*DEVICES[1]), fitz.Point(*DEVICES[2]),
                   color=(0, 0, 0), width=CONDUCTOR_PEN)

    run_start = fitz.Point(*DEVICES[0])
    run_end = fitz.Point(210, 246)
    page.draw_line(run_start, run_end, color=(0, 0, 0), width=CONDUCTOR_PEN)

    # Arrowhead: a closed triangle on the conductor pen, set off the end of the
    # run by a deliberate gap, exactly as a real sheet draws it.
    direction = np.array([ARROW_TIP[0] - run_end.x, ARROW_TIP[1] - run_end.y], float)
    direction /= np.linalg.norm(direction)
    base = np.array(ARROW_TIP, float) - direction * 11
    perpendicular = np.array([-direction[1], direction[0]]) * 2.5
    triangle = [
        fitz.Point(*ARROW_TIP),
        fitz.Point(*(base + perpendicular)),
        fitz.Point(*(base - perpendicular)),
    ]
    shape = page.new_shape()
    shape.draw_polyline(triangle + [triangle[0]])
    shape.finish(color=(0, 0, 0), width=CONDUCTOR_PEN, closePath=True)
    shape.commit()

    # Three conductor hash marks across the run, each its own one-stroke path.
    for step in (1, 2, 3):
        centre = np.array([run_start.x, run_start.y]) + direction * (18 + step * 9)
        across = np.array([-direction[1], direction[0]]) * 6
        page.draw_line(fitz.Point(*(centre - across)), fitz.Point(*(centre + across)),
                       color=(0, 0, 0), width=CONDUCTOR_PEN)

    # The circuit tag, as real text.
    page.insert_text(fitz.Point(150, 225), "A-12", fontsize=11)

    document.save(str(pdf_path))
    document.close()

    with fitz.open(str(pdf_path)) as opened:
        pixmap = opened[0].get_pixmap(matrix=fitz.Matrix(SCALE, SCALE))
        image_path = directory / "branch.png"
        pixmap.save(str(image_path))

    detections = [
        _detection("panelboard", tuple(v * SCALE for v in PANEL)),
        _detection("receptacle", _box_px(DEVICES[0])),
        _detection("receptacle", _box_px(DEVICES[1])),
        _detection("receptacle", _box_px(DEVICES[2])),
    ]

    return pdf_path, image_path, detections, directory


@pytest.fixture(scope="module")
def geometry(sheet):
    pdf_path, _, _, _ = sheet
    return extract_sheet_geometry(pdf_path, 1, DPI)


@pytest.fixture(scope="module")
def result(sheet, geometry):
    _, image_path, detections, directory = sheet
    return CircuitTracer().trace(image_path, detections, directory, geometry=geometry)


def test_geometry_lands_inside_the_rendered_page(geometry):
    segments = geometry.segments
    assert len(segments) > 10
    assert segments[:, [0, 2]].max() <= geometry.width + 1
    assert segments[:, [1, 3]].max() <= geometry.height + 1


def test_arrowhead_is_found_though_it_is_only_stroked(geometry):
    assert geometry.arrowheads
    tips = np.array([head["tip"] for head in geometry.arrowheads])
    expected = np.array(ARROW_TIP) * SCALE
    assert np.hypot(*(tips - expected).T).min() < 12


def test_circuit_tag_is_read_from_the_text(geometry):
    assert any(is_circuit_tag(word["text"]) for word in geometry.texts)


def test_conductor_pen_is_chosen_over_the_walls(result):
    assert result["source"] == "vector"
    assert result["conductor_lineweight_pt"] == pytest.approx(CONDUCTOR_PEN, abs=0.01)


def test_devices_chain_onto_one_circuit(result):
    circuit = max(result["circuits"], key=lambda c: c["device_count"])
    refs = {device["ref"] for device in circuit["devices"]}
    assert {"RECEPTACLE-1", "RECEPTACLE-2", "RECEPTACLE-3"} <= refs


def test_homerun_carries_its_tag_and_conductor_count(result):
    homeruns = [h for h in result["homeruns"] if h.get("circuit_tag")]
    assert homeruns, result["homeruns"]

    homerun = homeruns[0]
    assert normalize_tag(homerun["circuit_tag"]) == "A-12"
    assert homerun["conductor_count"] == 3


def test_circuit_is_named_after_its_homerun(result):
    tagged = [c for c in result["circuits"] if c.get("circuit_tag")]
    assert tagged
    assert tagged[0]["circuit_tag"] == "A-12"


def test_curve_pieces_are_not_counted_as_conductors(geometry):
    """
    Regression: a flattened bezier contributes many short segments. Counting
    those as hash marks inflates the conductor count on every curved homerun,
    which is a wrong number on a takeoff rather than a missing one.
    """

    assert geometry.standalone.sum() < len(geometry.segments)
    assert geometry.standalone.any()
