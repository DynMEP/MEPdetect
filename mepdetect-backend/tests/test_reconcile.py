"""
Reconciliation tests.

The takeoff is trustworthy when the circuits, the sheet text and the symbol
counts tell the same story; the findings have to say precisely where they do
not.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reconcile import INFO, MATCH, MISMATCH, MISSING, reconcile_takeoff


def _result():
    return {
        "class_counts": {"panel": 1, "receptacle": 8},
        "tokens": {"equipment": ["LP1", "MDP-1"], "kva": ["75"]},
        "cross_sheet_circuits": [
            {"circuit_tag": "LP1-2", "panel": "LP1"},
            {"circuit_tag": "LP2-4", "panel": "LP2"},
        ],
        "circuits": [{
            "sheet": "p1",
            "homeruns": [
                {"x": 1, "y": 1, "circuit_tag": "LP1-2"},
                {"x": 2, "y": 2, "circuit_tag": None},
            ],
        }],
    }


def _by_item(report):
    return {f["item"]: f for f in report["findings"]}


def test_findings_cover_the_three_sources():
    report = reconcile_takeoff(_result())
    findings = _by_item(report)

    # LP1 is referenced by circuits and named on the sheets.
    assert findings["panel LP1"]["severity"] == MATCH

    # LP2 is referenced but nothing on the sheets confirms it.
    assert findings["panel LP2"]["severity"] == MISSING

    # MDP-1 is named but no traced circuit lands on it.
    assert findings["equipment MDP-1"]["severity"] == INFO

    # Two panels referenced, one panel symbol detected.
    count = findings["panel symbol count"]
    assert count["severity"] == MISMATCH
    assert count["expected"] == 2
    assert count["found"] == 1

    # One homerun never got a tag.
    assert findings["untagged homeruns"]["found"] == 1

    assert report["counts"] == {MATCH: 1, MISSING: 1, INFO: 2, MISMATCH: 1}


def test_agreement_reads_as_match():
    result = _result()
    result["tokens"]["equipment"] = ["LP1", "LP2"]
    result["class_counts"]["panel"] = 2
    result["circuits"][0]["homeruns"][1]["circuit_tag"] = "LP2-4"

    report = reconcile_takeoff(result)
    severities = {f["severity"] for f in report["findings"]}
    assert MISMATCH not in severities
    assert MISSING not in severities


def test_untraced_job_yields_no_findings():
    report = reconcile_takeoff({"class_counts": {"receptacle": 3}})
    assert report["findings"] == []
    assert report["counts"] == {}
