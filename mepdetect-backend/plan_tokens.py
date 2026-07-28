"""
Plan Tokens
Mines electrical ratings and equipment names out of a sheet's text.

A drawing states more than its symbols: panels carry their kVA, voltage and
interrupting ratings as text, and equipment is named with tags like LP-1 or
MDP-2. Reading those alongside the symbol detections turns "a panel was found
here" into "panel LP-1, 208Y/120, 42 circuits was found here" - at the cost of
a regex pass over text the PDF already yields.

Positions matter: a rating is only attached to a detection when it is printed
next to it, so everything here keeps the rendered-pixel coordinates the
detections live in. Pattern set adapted from the DataCenter PRO ingest layer
(dc_pdf_ingest.py), narrowed to what appears on MEP branch drawings.
"""

import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import fitz  # PyMuPDF

from pdf_geometry import _display_transform, _extract_texts


# What a rating or an equipment name looks like when printed on a sheet.
# Ratings may arrive split across words ("75 KVA"), which scan_words handles
# by also offering adjacent same-line words joined.
TOKEN_PATTERNS = {
    "kva": re.compile(r"^(\d{1,5}(?:\.\d+)?)\s?KVA$", re.I),
    "kw": re.compile(r"^(\d{1,5}(?:\.\d+)?)\s?KW$", re.I),
    "kaic": re.compile(r"^(\d{1,3})\s?KAIC$", re.I),
    "amps": re.compile(r"^(\d{2,4})\s?A(?:MPS?)?$", re.I),
    "voltage": re.compile(
        r"^(480Y?/?277|480|415Y?/?240|400Y?/?230|240|230|208Y?/?120|208"
        r"|120/240|120|277|600Y?/?347|600)\s?V(?:OLTS?|AC)?$", re.I),
}

# Distribution-equipment names: a recognized prefix, then at least one digit,
# so "LP-1" and "MDP2" match but the words "PANEL" or "EMERGENCY" do not.
EQUIPMENT_TAG_PREFIXES = (
    "MDP", "MSB", "SWBD", "SWGR", "MCC", "ATS", "XFMR", "TX", "UPS", "PDU",
    "GEN", "LP", "RP", "PP", "DP", "EP", "MP", "NP", "HP",
)

EQUIPMENT_TAG = re.compile(
    r"^((?:%s)[A-Z0-9-]*\d[A-Z0-9-]*)$" % "|".join(EQUIPMENT_TAG_PREFIXES),
    re.I,
)


def extract_page_tokens(pdf_path: Path, page_number: int, dpi: int) -> List[Dict]:
    """
    Tokens of one PDF page, with rendered-pixel positions.

    Args:
        pdf_path: Source PDF.
        page_number: 1-based page.
        dpi: Resolution the page was rendered at for detection - fixes the
            pixel space the token positions are reported in.

    Returns:
        [{'kind', 'value', 'text', 'x', 'y', 'bbox'}]
    """

    with fitz.open(str(pdf_path)) as document:
        page = document[page_number - 1]
        transform = _display_transform(page, dpi / 72.0)
        words = page.get_text("words")

    return scan_words(_extract_texts(words, transform))


def scan_words(texts: Sequence[Dict]) -> List[Dict]:
    """
    Token entries found in a sheet's word list.

    Args:
        texts: Word dicts as extracted by pdf_geometry ({'text', 'bbox', 'x',
            'y', 'line', 'order'}). Entries without line/order metadata are
            still matched singly.

    Returns:
        [{'kind', 'value', 'text', 'x', 'y', 'bbox'}], one per match.
    """

    candidates = list(texts)

    # A rating split across words ("75" "KVA") only reads as one joined. Only
    # adjacent words on the same text line qualify, the same adjacency rule
    # pdf_geometry applies to split circuit tags.
    for current, following in zip(texts, texts[1:]):
        if current.get("line") is None or current.get("line") != following.get("line"):
            continue
        if following.get("order") != current.get("order", -2) + 1:
            continue
        bbox = [
            min(current["bbox"][0], following["bbox"][0]),
            min(current["bbox"][1], following["bbox"][1]),
            max(current["bbox"][2], following["bbox"][2]),
            max(current["bbox"][3], following["bbox"][3]),
        ]
        candidates.append({
            "text": f"{current['text']} {following['text']}",
            "bbox": bbox,
            "x": (bbox[0] + bbox[2]) / 2,
            "y": (bbox[1] + bbox[3]) / 2,
        })

    tokens = []
    seen = set()
    for word in candidates:
        token = _match(word)
        if token is None:
            continue
        # The joined form of a match duplicates its single-word form; one
        # entry per (kind, value, place) is enough.
        key = (token["kind"], token["value"],
               round(token["x"] / 4), round(token["y"] / 4))
        if key in seen:
            continue
        seen.add(key)
        tokens.append(token)

    return tokens


def _match(word: Dict) -> Optional[Dict]:
    """Classify one word (or joined pair) as a token, or None."""

    text = word["text"].strip()
    if not text:
        return None

    for kind, pattern in TOKEN_PATTERNS.items():
        match = pattern.match(text)
        if match:
            return {
                "kind": kind,
                "value": match.group(1).upper(),
                "text": text,
                "x": float(word["x"]),
                "y": float(word["y"]),
                "bbox": [float(v) for v in word["bbox"]],
            }

    match = EQUIPMENT_TAG.match(text)
    if match:
        return {
            "kind": "equipment",
            "value": match.group(1).upper(),
            "text": text,
            "x": float(word["x"]),
            "y": float(word["y"]),
            "bbox": [float(v) for v in word["bbox"]],
        }

    return None


def attach_ratings(
    detections: List[Dict],
    tokens: Sequence[Dict],
    panel_keywords: Sequence[str],
    radius_boxes: float = 1.5,
) -> int:
    """
    Annotate panel-like detections with the ratings printed next to them.

    A rating belongs to the equipment it is printed on or beside, so the
    search radius scales with the symbol's own size rather than the sheet's.

    Args:
        detections: Detection dicts; matching ones gain a 'ratings' key.
        tokens: Sheet tokens from scan_words / extract_page_tokens.
        panel_keywords: Class-name fragments that mark distribution equipment.
        radius_boxes: Search radius, in multiples of the box's long side.

    Returns:
        Number of detections annotated.
    """

    if not tokens:
        return 0

    keywords = tuple(k.lower() for k in panel_keywords)
    annotated = 0

    for det in detections:
        name = str(det.get("class_name", "")).lower()
        if not any(k in name for k in keywords):
            continue

        bbox = det.get("bbox", {})
        cx, cy = bbox.get("center_x", 0.0), bbox.get("center_y", 0.0)
        radius = radius_boxes * max(
            bbox.get("width", 0.0), bbox.get("height", 0.0), 1.0
        )

        ratings: Dict[str, Dict] = {}
        for token in tokens:
            distance = math.hypot(token["x"] - cx, token["y"] - cy)
            if distance > radius:
                continue
            kind = token["kind"]
            if kind not in ratings or distance < ratings[kind]["distance"]:
                ratings[kind] = {
                    "value": token["value"],
                    "distance": round(distance, 1),
                }

        if ratings:
            det["ratings"] = ratings
            annotated += 1

    return annotated


def summarize_tokens(sheet_tokens: Sequence[Sequence[Dict]]) -> Dict[str, List[str]]:
    """Unique token values across the job's sheets, by kind."""

    found: Dict[str, set] = {}
    for tokens in sheet_tokens:
        for token in tokens:
            found.setdefault(token["kind"], set()).add(token["value"])

    return {kind: sorted(values) for kind, values in sorted(found.items())}
