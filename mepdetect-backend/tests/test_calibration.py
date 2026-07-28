"""
Scale calibration tests.

A calibration is two reference pixels and a real distance; everything after
that is multiplication. The tests pin the arithmetic, the API-string parsing,
and the netlist growing real-unit lengths when a calibration rides along.
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibration import Calibration, parse_reference
from result_exporter import ResultExporter


def test_from_reference_scale():
    # 300-400-500 triangle: 500 px apart, 50 ft apart -> 0.1 ft/px.
    cal = Calibration.from_reference((0, 0), (300, 400), 50.0)
    assert cal.units_per_pixel == pytest.approx(0.1)
    assert cal.units == "feet"
    assert cal.length(120) == pytest.approx(12.0)


def test_from_reference_rejects_bad_input():
    with pytest.raises(ValueError):
        Calibration.from_reference((10, 10), (10, 10), 50.0)
    with pytest.raises(ValueError):
        Calibration.from_reference((0, 0), (100, 0), 0.0)


def test_parse_reference_roundtrip():
    cal = parse_reference("0,0,0,1000", 25.0, "meters")
    assert cal.units == "meters"
    assert cal.units_per_pixel == pytest.approx(0.025)


def test_parse_reference_absent_is_none():
    assert parse_reference(None, None) is None
    assert parse_reference("", None) is None


def test_parse_reference_rejects_half_a_calibration():
    with pytest.raises(ValueError):
        parse_reference("0,0,10,10", None)
    with pytest.raises(ValueError):
        parse_reference(None, 50.0)
    with pytest.raises(ValueError):
        parse_reference("1,2,3", 50.0)
    with pytest.raises(ValueError):
        parse_reference("a,b,c,d", 50.0)


@pytest.fixture
def traced_results():
    """Minimal traced job: one circuit on one net, 1500 px long."""

    return {
        "calibration": {"units": "feet", "units_per_pixel": 0.1},
        "circuits": [{
            "sheet": "plan_page_1.png",
            "nets": [{
                "net_id": "N1",
                "length_px": 1500.0,
                "junction_count": 0,
                "connections": [{
                    "ref": "RECEPTACLE-1",
                    "class_name": "receptacle",
                    "confidence": 0.9,
                    "terminal": [100.0, 200.0],
                }],
            }],
            "circuits": [{
                "circuit_id": "CKT-1",
                "circuit_tag": "LP1-2",
                "net_ids": ["N1"],
                "panel_refs": [],
                "devices": [],
            }],
            "tag_circuits": [],
            "homeruns": [],
            "unconnected_symbols": [],
        }],
    }


def test_netlist_reports_real_lengths(traced_results, tmp_path):
    path = ResultExporter().generate_netlist(traced_results, tmp_path)
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    device = next(r for r in rows if r["Role"] == "device")
    assert float(device["Length_px"]) == pytest.approx(1500.0)
    assert float(device["Length_real"]) == pytest.approx(150.0)
    assert device["Units"] == "feet"


def test_netlist_without_calibration_leaves_real_length_empty(traced_results, tmp_path):
    del traced_results["calibration"]
    path = ResultExporter().generate_netlist(traced_results, tmp_path)
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    device = next(r for r in rows if r["Role"] == "device")
    assert device["Length_real"] == ""
    assert device["Units"] == ""
