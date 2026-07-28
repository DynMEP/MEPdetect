"""
Netlist export tests.

Checks that a traced sheet survives the trip through ResultExporter as a CSV an
estimator can open, and that asking for a netlist without tracing is a no-op
rather than an error.
"""

import asyncio
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from result_exporter import ResultExporter

from test_circuit_tracer import result, sheet  # noqa: F401  (pytest fixtures)


@pytest.fixture
def exported(result, tmp_path):  # noqa: F811
    exporter = ResultExporter()
    path = exporter.generate_netlist({"circuits": [result]}, tmp_path)
    with open(path, newline="") as f:
        return path, list(csv.DictReader(f))


def test_netlist_csv_lists_every_wired_device(exported):
    _, rows = exported

    devices = {row["Component"] for row in rows if row["Role"] == "device"}
    assert {"RECEPTACLE-1", "RECEPTACLE-2", "RECEPTACLE-3", "SWITCH-1"} <= devices


def test_netlist_csv_carries_circuit_and_net_ids(exported):
    _, rows = exported

    for row in (r for r in rows if r["Role"] == "device"):
        assert row["Circuit"].startswith("C")
        assert row["Net"].startswith("N")
        assert row["Sheet"]


def test_netlist_csv_records_the_homerun_and_its_panel(exported):
    _, rows = exported

    homeruns = [row for row in rows if row["Role"] == "homerun"]
    assert homeruns
    assert any(row["Panel"] == "PANELBOARD-1" for row in homeruns)


def test_export_skips_netlist_when_tracing_was_not_run(tmp_path):
    exporter = ResultExporter()
    files = asyncio.run(exporter.export(
        {"total_detections": 0, "class_counts": {}, "detections": []},
        tmp_path,
        ["netlist"],
    ))

    assert "netlist" not in files


def test_export_emits_netlist_when_circuits_are_present(result, tmp_path):  # noqa: F811
    exporter = ResultExporter()
    files = asyncio.run(exporter.export(
        {"total_detections": 5, "class_counts": {}, "detections": [], "circuits": [result]},
        tmp_path,
        ["json", "netlist"],
    ))

    assert Path(files["netlist"]).exists()
    assert Path(files["json"]).exists()
