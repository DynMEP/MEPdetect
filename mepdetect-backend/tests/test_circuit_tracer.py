"""
Circuit tracer tests.

Builds a synthetic single-line branch circuit — panel, three receptacles, a
switch leg tapped off a T, and a homerun arrow pointing back at the panel —
and checks that tracing recovers the connectivity.
"""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from circuit_tracer import CircuitTracer


WIDTH, HEIGHT = 1400, 900
LINE = 3

PANEL = (70, 70, 170, 260)
RECEPTACLES = [(470, 340), (900, 340), (900, 700)]
SWITCH = (660, 660)
HOMERUN_TIP = (250, 190)


def _box(center, half=26):
    x, y = center
    return (x - half, y - half, x + half, y + half)


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


def _draw_arrowhead(img, tip, direction, length=34, half_base=11):
    dx, dy = direction
    base = np.array(tip, float) - np.array([dx, dy]) * length
    perp = np.array([-dy, dx]) * half_base
    triangle = np.array([tip, base + perp, base - perp], np.int32)
    cv2.fillPoly(img, [triangle], 0)


@pytest.fixture(scope="module")
def sheet(tmp_path_factory):
    """Synthetic drawing plus the detections a symbol model would return."""

    img = np.full((HEIGHT, WIDTH), 255, np.uint8)

    # Panel enclosure.
    cv2.rectangle(img, PANEL[:2], PANEL[2:], 0, LINE)

    # Devices.
    for center in RECEPTACLES:
        cv2.circle(img, center, 22, 0, LINE)
    cv2.circle(img, SWITCH, 22, 0, LINE)

    # Branch wiring: receptacle 1 -> 2 -> 3, with a switch leg tapped at a T.
    cv2.line(img, RECEPTACLES[0], RECEPTACLES[1], 0, LINE)
    cv2.line(img, RECEPTACLES[1], RECEPTACLES[2], 0, LINE)
    tee = (660, RECEPTACLES[0][1])
    cv2.line(img, tee, SWITCH, 0, LINE)

    # Homerun: run from the first receptacle up-left, ending in a solid arrow.
    direction = np.array(HOMERUN_TIP, float) - np.array(RECEPTACLES[0], float)
    direction /= np.linalg.norm(direction)
    cv2.line(img, RECEPTACLES[0], HOMERUN_TIP, 0, LINE)
    _draw_arrowhead(img, HOMERUN_TIP, direction)

    path = tmp_path_factory.mktemp("sheets") / "branch_circuit.png"
    cv2.imwrite(str(path), img)

    detections = [
        _detection("panelboard", PANEL),
        _detection("receptacle", _box(RECEPTACLES[0])),
        _detection("receptacle", _box(RECEPTACLES[1])),
        _detection("receptacle", _box(RECEPTACLES[2])),
        _detection("switch", _box(SWITCH)),
    ]

    return path, detections


@pytest.fixture(scope="module")
def result(sheet, tmp_path_factory):
    path, detections = sheet
    tracer = CircuitTracer()
    return tracer.trace(path, detections, output_dir=tmp_path_factory.mktemp("out"))


def test_traces_conductor_runs(result):
    assert result["stats"]["net_count"] >= 1
    assert result["stats"]["traced_length_px"] > 500


def test_every_device_lands_on_a_net(result):
    """All four devices are wired; only the panel is reached by arrow alone."""

    connected = {
        connection["ref"]
        for net in result["nets"]
        for connection in net["connections"]
    }
    assert {"RECEPTACLE-1", "RECEPTACLE-2", "RECEPTACLE-3", "SWITCH-1"} <= connected


def test_detects_the_tee_as_a_node(result):
    """The switch leg tap is a junction node, near the drawn tee."""

    assert result["stats"]["node_count"] >= 1
    assert any(
        abs(node["x"] - 660) < 25 and abs(node["y"] - RECEPTACLES[0][1]) < 25
        for node in result["nodes"]
    )


def test_diagonal_runs_do_not_invent_nodes(result):
    """
    Regression: counting touching neighbours reads every staircase pixel on a
    diagonal as a junction. The drawing has exactly one tee.
    """

    assert result["stats"]["node_count"] <= 3, result["nodes"]


def test_detects_the_homerun_and_its_panel(result):
    assert result["stats"]["homerun_count"] >= 1

    homerun = min(
        result["homeruns"],
        key=lambda h: (h["x"] - HOMERUN_TIP[0]) ** 2 + (h["y"] - HOMERUN_TIP[1]) ** 2,
    )
    assert abs(homerun["x"] - HOMERUN_TIP[0]) < 30
    assert abs(homerun["y"] - HOMERUN_TIP[1]) < 30
    assert homerun["direction"][0] < 0 and homerun["direction"][1] < 0
    assert homerun["panel_ref"] == "PANELBOARD-1"


def test_devices_group_into_one_circuit(result):
    """Nets daisy-chained through pass-through devices collapse to a circuit."""

    circuit = max(result["circuits"], key=lambda c: c["device_count"])
    refs = {device["ref"] for device in circuit["devices"]}
    assert {"RECEPTACLE-1", "RECEPTACLE-2", "RECEPTACLE-3", "SWITCH-1"} <= refs
    assert circuit["homerun_count"] >= 1


def test_writes_an_overlay(result):
    assert result["overlay_path"] is not None
    assert Path(result["overlay_path"]).exists()


def test_survives_a_sheet_with_no_detections(sheet, tmp_path):
    path, _ = sheet
    result = CircuitTracer().trace(path, [], output_dir=tmp_path)

    assert result["stats"]["net_count"] >= 1
    assert result["stats"]["connected_symbols"] == 0
    assert result["circuits"]
