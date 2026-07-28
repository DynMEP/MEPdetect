"""
Cross-sheet circuit tests.

A branch circuit does not stop at a matchline. These check that the same
panel-circuit designation on two sheets is reported once, with its devices
added together rather than counted twice.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from circuit_tracer import merge_cross_sheet_circuits


def _traced_sheet(sheet, tag, refs, homeruns=1):
    return {
        "sheet": sheet,
        "circuits": [{
            "circuit_id": "C1",
            "circuit_tag": tag,
            "net_ids": ["N1"],
            "device_count": len(refs),
            "devices": [{"ref": ref} for ref in refs],
            "homerun_count": homeruns,
        }],
        "tag_circuits": [],
    }


def _annotated_sheet(sheet, tag, refs):
    return {
        "sheet": sheet,
        "circuits": [],
        "tag_circuits": [{
            "circuit_tag": tag,
            "panel": tag.rsplit("-", 1)[0],
            "sheet": sheet,
            "device_count": len(refs),
            "devices": [{"ref": ref} for ref in refs],
        }],
    }


def test_same_tag_on_two_sheets_is_one_circuit():
    merged = merge_cross_sheet_circuits([
        _traced_sheet("E1.png", "A-12", ["RECEPTACLE-1", "RECEPTACLE-2"]),
        _traced_sheet("E2.png", "A-12", ["RECEPTACLE-1"]),
    ])

    assert len(merged) == 1
    circuit = merged[0]
    assert circuit["circuit_tag"] == "A-12"
    assert circuit["sheet_count"] == 2
    assert circuit["device_count"] == 3
    assert circuit["homerun_count"] == 2


def test_devices_are_qualified_by_sheet():
    """
    RECEPTACLE-1 exists on both sheets and is not the same device, so the two
    must not collapse into one.
    """

    merged = merge_cross_sheet_circuits([
        _traced_sheet("E1.png", "A-12", ["RECEPTACLE-1"]),
        _traced_sheet("E2.png", "A-12", ["RECEPTACLE-1"]),
    ])

    assert merged[0]["device_count"] == 2
    assert set(merged[0]["devices"]) == {"E1.png:RECEPTACLE-1", "E2.png:RECEPTACLE-1"}


def test_traced_and_annotated_sheets_join_on_the_tag():
    """One sheet draws its wiring, the next only annotates it: still one circuit."""

    merged = merge_cross_sheet_circuits([
        _traced_sheet("E1.png", "A-12", ["RECEPTACLE-1"]),
        _annotated_sheet("E2.png", "A-12", ["RECEPTACLE-7", "RECEPTACLE-8"]),
    ])

    assert len(merged) == 1
    assert merged[0]["device_count"] == 3
    assert merged[0]["sheet_count"] == 2


def test_different_circuits_stay_apart():
    merged = merge_cross_sheet_circuits([
        _traced_sheet("E1.png", "A-12", ["RECEPTACLE-1"]),
        _traced_sheet("E1.png", "A-14", ["RECEPTACLE-2"]),
    ])

    assert {circuit["circuit_tag"] for circuit in merged} == {"A-12", "A-14"}
    assert all(circuit["sheet_count"] == 1 for circuit in merged)


def test_panel_is_split_off_the_tag():
    merged = merge_cross_sheet_circuits([
        _traced_sheet("E1.png", "4NPL5-26", ["RECEPTACLE-1"]),
    ])

    assert merged[0]["panel"] == "4NPL5"


def test_untagged_circuits_are_left_out():
    """Without a designation there is nothing to match across sheets on."""

    sheet = _traced_sheet("E1.png", None, ["RECEPTACLE-1"])
    assert merge_cross_sheet_circuits([sheet]) == []
