"""
Reconcile
Cross-checks the takeoff against what the drawings say about themselves.

A traced circuit names its panel; the sheets name their equipment in text;
the detector counts panel symbols. When those three agree the takeoff can be
trusted, and when they disagree the discrepancy is exactly what an estimator
needs to look at before the numbers go in a bid. Severity model follows the
DataCenter PRO reconciliation layer (dc_reconcile.py): MATCH / MISMATCH /
MISSING / INFO, one finding per checkable item.
"""

from typing import Dict, List, Sequence

MATCH = "MATCH"
MISMATCH = "MISMATCH"
MISSING = "MISSING"  # referenced by circuits, nothing on the sheets confirms it
INFO = "INFO"        # sheet data with no takeoff item to compare


def _finding(item: str, severity: str, expected, found, note: str = "") -> Dict:
    return {"item": item, "severity": severity, "expected": expected,
            "found": found, "note": note}


def reconcile_takeoff(
    combined_result: Dict,
    panel_keywords: Sequence[str] = ("panel", "panelboard", "switchboard",
                                    "loadcenter", "load_center", "mdp",
                                    "distribution", "disconnect"),
) -> Dict:
    """
    Reconcile circuits, text and detections into a findings list.

    Args:
        combined_result: Job result carrying 'cross_sheet_circuits' (merged
            circuits), 'class_counts', and optionally 'tokens' (job-level
            token summary from plan_tokens).

    Returns:
        {'findings': [...], 'counts': {severity: n}}
    """

    findings: List[Dict] = []

    circuits = combined_result.get("cross_sheet_circuits", [])
    referenced_panels = sorted({
        c["panel"] for c in circuits if c.get("panel")
    })

    tokens = combined_result.get("tokens", {})
    named_equipment = {v.upper() for v in tokens.get("equipment", [])}

    # Circuits point at panels; the sheets should name that equipment somewhere.
    for panel in referenced_panels:
        if panel.upper() in named_equipment:
            findings.append(_finding(
                f"panel {panel}", MATCH, panel, panel,
                "referenced by circuits and named on the sheets",
            ))
        else:
            findings.append(_finding(
                f"panel {panel}", MISSING, panel, None,
                "circuits reference this panel but no sheet names it - "
                "check the tag or the panel schedule sheet",
            ))

    # Equipment the sheets name that no traced circuit lands on.
    referenced_upper = {p.upper() for p in referenced_panels}
    for name in sorted(named_equipment - referenced_upper):
        findings.append(_finding(
            f"equipment {name}", INFO, None, name,
            "named on the sheets, no traced circuit references it",
        ))

    # Distinct panels referenced vs panel symbols detected. More references
    # than symbols means panels feeding these sheets were not detected -
    # normal when the panel lives on another sheet, worth flagging when not.
    class_counts = combined_result.get("class_counts", {})
    keywords = tuple(k.lower() for k in panel_keywords)
    detected_panels = sum(
        count for name, count in class_counts.items()
        if any(k in name.lower() for k in keywords)
    )
    if referenced_panels:
        severity = MATCH if detected_panels >= len(referenced_panels) else MISMATCH
        findings.append(_finding(
            "panel symbol count", severity,
            len(referenced_panels), detected_panels,
            "distinct panels referenced by circuits vs panel symbols detected",
        ))

    # Homeruns that never got a circuit tag leave devices uncounted per panel.
    untagged = sum(
        1
        for sheet in combined_result.get("circuits", [])
        for homerun in sheet.get("homeruns", [])
        if not homerun.get("circuit_tag")
    )
    if untagged:
        findings.append(_finding(
            "untagged homeruns", INFO, 0, untagged,
            "homerun arrows with no readable circuit tag - their devices "
            "are traced but not assigned to a panel",
        ))

    counts: Dict[str, int] = {}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1

    return {"findings": findings, "counts": counts}
