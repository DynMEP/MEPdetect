"""
PDF Geometry
Reads the vector line work, filled marks and text of a PDF sheet.

CAD-exported drawings carry exact geometry, and using it instead of the
rendered pixels removes the guesswork of separating conductors from text and
hatching. Two very different drawing conventions show up in practice:

  * Traditional sheets draw the conductor runs and end them in a filled
    homerun arrowhead. Those are traced.
  * Revit-style sheets draw no wiring at all and annotate each device with its
    panel-circuit tag instead. Those are circuited from the annotations.

Both are supported, because both turn up in the same plan set.

Everything is returned in the pixel space of the page rendered at `dpi`, which
is the space the YOLO detections live in. PDF drawing and text coordinates are
unrotated, so a page with /Rotate is transformed here to match the render.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF
import numpy as np


# Panel-circuit designations as annotated on devices and homeruns: "A-2",
# "4NPL5-26", "LP1-2,4,6". The panel part may lead with a digit (level or
# building prefix), so it is not restricted to letters.
#
# The circuit part must be one or two bare digits: that is what separates a
# circuit tag from an equipment id such as "CMP-1CE4A" (letters after the
# dash), "TBLPW-044" or "CPC-93800" (too many digits). Getting this wrong puts
# a wrong circuit number on the takeoff, so it stays strict.
CIRCUIT_TAG = re.compile(
    r"^[A-Z0-9]{1,8}[-‐-―]\d{1,2}(?:\s*[,/]\s*\d{1,2})*$"
)

# Bare circuit numbers, used when the panel is named elsewhere on the run.
CIRCUIT_NUMBERS = re.compile(r"^\d{1,2}(?:\s*[,/]\s*\d{1,2})+$")

# Sheet and detail references share the tag shape ("E0001-2"), so they are
# rejected outright: a panel name is not a drawing number.
SHEET_REFERENCE = re.compile(r"^[EMPAS]\d{3,4}[-‐-―]\d{1,2}$")


def is_circuit_tag(text: str) -> bool:
    """True for a panel-circuit designation, false for equipment and sheet ids."""

    text = text.strip()
    return bool(CIRCUIT_TAG.match(text)) and not SHEET_REFERENCE.match(text)


@dataclass
class SheetGeometry:
    """Vector content of one PDF page, in rendered-image pixels."""

    page_number: int
    dpi: int
    width: int
    height: int
    segments: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), np.float32))
    widths: np.ndarray = field(default_factory=lambda: np.zeros((0,), np.float32))
    standalone: np.ndarray = field(default_factory=lambda: np.zeros((0,), bool))
    arrowheads: List[Dict] = field(default_factory=list)
    texts: List[Dict] = field(default_factory=list)

    @property
    def has_line_work(self) -> bool:
        """Any vector line work to trace, rather than a scanned page."""
        return len(self.segments) >= 20

    @property
    def circuit_tags(self) -> List[Dict]:
        """Text entries that read as a panel-circuit designation."""
        return [word for word in self.texts if is_circuit_tag(word["text"])]

    def width_classes(self, min_length_share: float = 0.01) -> List[Tuple[float, np.ndarray]]:
        """
        Line work grouped by plotted lineweight, heaviest first.

        A drawing office gives conductors their own pen: on a traditional sheet
        one lineweight holds the branch wiring and nothing else, while the
        architectural background sits on lighter pens. Splitting by pen is an
        exact separation the raster cannot offer.

        Args:
            min_length_share: Drop pens carrying less than this share of the
                total drawn length - they are borders, leaders and noise.

        Returns:
            [(width, segment indices)], heaviest pen first.
        """

        if not len(self.segments):
            return []

        lengths = np.hypot(
            self.segments[:, 2] - self.segments[:, 0],
            self.segments[:, 3] - self.segments[:, 1],
        )
        total = float(lengths.sum())
        if total <= 0:
            return []

        rounded = np.round(self.widths.astype(np.float64), 2)
        classes = []
        for width in np.unique(rounded):
            indices = np.nonzero(rounded == width)[0]
            if float(lengths[indices].sum()) / total >= min_length_share:
                classes.append((float(width), indices))

        return sorted(classes, key=lambda item: item[0], reverse=True)


def extract_sheet_geometry(
    pdf_path: Path,
    page_number: int,
    dpi: int,
    arrow_area_range: Tuple[float, float] = (0.3, 60.0),
) -> SheetGeometry:
    """
    Pull the vector geometry of one page.

    Args:
        pdf_path: Source PDF.
        page_number: 1-based page.
        dpi: Resolution the page was rendered at for detection.
        arrow_area_range: Filled-shape area, in PDF points squared, that can
            be a homerun arrowhead. Kept in points so the same drawing yields
            the same arrows whatever resolution it is rendered at.

    Returns:
        SheetGeometry in rendered-image pixel coordinates.
    """

    scale = dpi / 72.0
    area_range = (arrow_area_range[0] * scale ** 2, arrow_area_range[1] * scale ** 2)

    with fitz.open(str(pdf_path)) as document:
        page = document[page_number - 1]
        rect = page.rect
        transform = _display_transform(page, scale)
        drawings = page.get_drawings()
        words = page.get_text("words")

    raw_segments: List[Tuple[float, float, float, float]] = []
    raw_widths: List[float] = []
    raw_standalone: List[bool] = []
    arrowheads: List[Dict] = []

    for drawing in drawings:
        kind = drawing.get("type", "s")
        items = drawing.get("items", [])
        filled = "f" in kind
        width = float(drawing.get("width") or 0.0)

        arrow = _as_arrowhead(
            transform(_path_points(items)),
            area_range,
            filled=filled,
            closed=bool(drawing.get("closePath")) or _is_closed(items),
            width=width,
        )
        if arrow:
            arrowheads.append(arrow)

        if filled and "s" not in kind:
            # A pure fill is a symbol, an arrowhead or a hatch - never a
            # conductor - so it contributes no line work.
            continue

        path_segments = _path_segments(items)
        raw_segments.extend(path_segments)
        raw_widths.extend([width] * len(path_segments))
        # A conductor hash mark is drawn as its own one-stroke path. A run is a
        # polyline or a curve, so its pieces never qualify - which is what
        # stops flattened curve segments being counted as conductors.
        is_tick = len(items) == 1 and items[0][0] == "l"
        raw_standalone.extend([is_tick] * len(path_segments))

    segments = np.asarray(raw_segments, np.float64).reshape(-1, 4)
    if len(segments):
        segments = np.hstack([
            transform(segments[:, :2]),
            transform(segments[:, 2:]),
        ]).astype(np.float32)
    else:
        segments = np.zeros((0, 4), np.float32)

    texts = _extract_texts(words, transform)

    return SheetGeometry(
        page_number=page_number,
        dpi=dpi,
        width=int(round(rect.width * scale)),
        height=int(round(rect.height * scale)),
        segments=segments,
        widths=np.asarray(raw_widths, np.float32),
        standalone=np.asarray(raw_standalone, bool),
        arrowheads=arrowheads,
        texts=texts,
    )


def _display_transform(page, scale: float):
    """
    Map unrotated PDF coordinates to rendered-image pixels.

    get_drawings() and get_text() report coordinates before /Rotate is applied,
    while the pixmap the detector sees is rotated. Without this, everything on
    a rotated sheet lands outside the image.
    """

    matrix = page.rotation_matrix
    linear = np.array([[matrix.a, matrix.b], [matrix.c, matrix.d]], np.float64)
    offset = np.array([matrix.e, matrix.f], np.float64)

    def transform(points) -> np.ndarray:
        points = np.asarray(points, np.float64).reshape(-1, 2)
        if not len(points):
            return points
        return (points @ linear + offset) * scale

    return transform


# ----------------------------------------------------------------------
# Text
# ----------------------------------------------------------------------

def _extract_texts(words: Sequence, transform) -> List[Dict]:
    """
    Words in image pixels, plus recombined neighbours.

    A tag drawn as "A - 2" arrives as three words, so adjacent words on the
    same line are also offered joined; the tag matcher picks whichever form
    reads as a circuit.
    """

    entries = []
    for word in words:
        corners = transform([(word[0], word[1]), (word[2], word[3])])
        x0, y0 = corners.min(axis=0)
        x1, y1 = corners.max(axis=0)
        entries.append({
            "text": word[4],
            "bbox": [float(x0), float(y0), float(x1), float(y1)],
            "x": float((x0 + x1) / 2),
            "y": float((y0 + y1) / 2),
            "line": (word[5], word[6]),
            "order": word[7],
        })

    merged = []
    for current, following in zip(entries, entries[1:]):
        if current["line"] != following["line"]:
            continue
        if following["order"] != current["order"] + 1:
            continue

        gap = following["bbox"][0] - current["bbox"][2]
        span = max(current["bbox"][2] - current["bbox"][0], 1.0)
        if gap > span:
            continue

        joined = f"{current['text']}{following['text']}"
        if not is_circuit_tag(joined):
            continue

        bbox = [
            min(current["bbox"][0], following["bbox"][0]),
            min(current["bbox"][1], following["bbox"][1]),
            max(current["bbox"][2], following["bbox"][2]),
            max(current["bbox"][3], following["bbox"][3]),
        ]
        merged.append({
            "text": joined,
            "bbox": bbox,
            "x": (bbox[0] + bbox[2]) / 2,
            "y": (bbox[1] + bbox[3]) / 2,
            "line": current["line"],
            "order": current["order"],
        })

    return entries + merged


def ocr_tags_near(
    image_path: Path,
    points: Sequence[Sequence[float]],
    radius: int = 260,
    min_confidence: int = 55,
) -> List[Dict]:
    """
    Read circuit tags off the raster around given points.

    Needed when the sheet has its annotation converted to curves, which is
    common on drawings plotted from older CAD: the tag is visible but carries
    no text. OCR runs only in a window around each homerun, never on the whole
    sheet, which would be far too slow at plotting resolution.

    Returns an empty list when pytesseract or the tesseract binary is missing,
    so tag reading degrades instead of failing.
    """

    try:
        import cv2
        import pytesseract
    except ImportError:
        return []

    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return []

    height, width = image.shape
    found: List[Dict] = []

    for point in points:
        cx, cy = int(point[0]), int(point[1])
        x0, y0 = max(0, cx - radius), max(0, cy - radius)
        x1, y1 = min(width, cx + radius), min(height, cy + radius)
        if x1 - x0 < 10 or y1 - y0 < 10:
            continue

        crop = image[y0:y1, x0:x1]
        try:
            data = pytesseract.image_to_data(
                crop,
                config="--psm 11 -c tessedit_char_whitelist="
                       "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-,/",
                output_type=pytesseract.Output.DICT,
            )
        except Exception:
            return []

        for index, text in enumerate(data["text"]):
            text = text.strip()
            if not text or not is_circuit_tag(text):
                continue
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                continue
            if confidence < min_confidence:
                continue

            left, top = data["left"][index], data["top"][index]
            box_w, box_h = data["width"][index], data["height"][index]
            found.append({
                "text": text,
                "bbox": [x0 + left, y0 + top, x0 + left + box_w, y0 + top + box_h],
                "x": float(x0 + left + box_w / 2),
                "y": float(y0 + top + box_h / 2),
                "source": "ocr",
                "confidence": confidence,
            })

    return found


def find_circuit_tag(
    texts: Sequence[Dict],
    point: Sequence[float],
    radius: float,
) -> Optional[Dict]:
    """
    The panel-circuit designation closest to a point, within `radius` pixels.

    Returns:
        {'tag', 'distance'} for the closest match, or None.
    """

    best = None
    best_distance = radius

    for word in texts:
        if not is_circuit_tag(word["text"]):
            continue

        distance = float(np.hypot(word["x"] - point[0], word["y"] - point[1]))
        if distance < best_distance:
            best_distance = distance
            best = {"tag": word["text"].strip(), "distance": round(distance, 1)}

    return best


def normalize_tag(tag: str) -> str:
    """Canonical form of a tag, for matching the same circuit across sheets."""

    return re.sub(r"[\s‐-―]", lambda m: "" if m.group().isspace() else "-",
                  tag.strip().upper())


# ----------------------------------------------------------------------
# Path decoding
# ----------------------------------------------------------------------

def _path_segments(items: Sequence) -> List[Tuple[float, float, float, float]]:
    """Flatten one path's drawing items into straight segments."""

    segments = []

    for item in items:
        operator = item[0]

        if operator == "l":
            (x1, y1), (x2, y2) = item[1], item[2]
            segments.append((x1, y1, x2, y2))

        elif operator == "c":
            flattened = _flatten_cubic(item[1], item[2], item[3], item[4])
            for (x1, y1), (x2, y2) in zip(flattened, flattened[1:]):
                segments.append((x1, y1, x2, y2))

        elif operator == "re":
            rect = item[1]
            corners = [
                (rect.x0, rect.y0), (rect.x1, rect.y0),
                (rect.x1, rect.y1), (rect.x0, rect.y1), (rect.x0, rect.y0),
            ]
            segments.extend(
                (a[0], a[1], b[0], b[1]) for a, b in zip(corners, corners[1:])
            )

        elif operator == "qu":
            quad = item[1]
            corners = [
                (quad.ul.x, quad.ul.y), (quad.ur.x, quad.ur.y),
                (quad.lr.x, quad.lr.y), (quad.ll.x, quad.ll.y), (quad.ul.x, quad.ul.y),
            ]
            segments.extend(
                (a[0], a[1], b[0], b[1]) for a, b in zip(corners, corners[1:])
            )

    return segments


def _flatten_cubic(p0, p1, p2, p3, steps: int = 6) -> List[Tuple[float, float]]:
    """Sample a cubic bezier - homerun arcs are drawn as curves."""

    t = np.linspace(0.0, 1.0, steps)[:, None]
    points = (
        (1 - t) ** 3 * np.array([p0.x, p0.y])
        + 3 * (1 - t) ** 2 * t * np.array([p1.x, p1.y])
        + 3 * (1 - t) * t ** 2 * np.array([p2.x, p2.y])
        + t ** 3 * np.array([p3.x, p3.y])
    )
    return [tuple(point) for point in points]


def _path_points(items: Sequence) -> List[Tuple[float, float]]:
    """Corner points of a path, for classifying filled shapes."""

    points: List[Tuple[float, float]] = []

    for item in items:
        operator = item[0]
        if operator == "l":
            points.extend([(item[1].x, item[1].y), (item[2].x, item[2].y)])
        elif operator == "c":
            points.extend([(item[1].x, item[1].y), (item[4].x, item[4].y)])
        elif operator == "re":
            rect = item[1]
            points.extend([
                (rect.x0, rect.y0), (rect.x1, rect.y0),
                (rect.x1, rect.y1), (rect.x0, rect.y1),
            ])
        elif operator == "qu":
            quad = item[1]
            points.extend([
                (quad.ul.x, quad.ul.y), (quad.ur.x, quad.ur.y),
                (quad.lr.x, quad.lr.y), (quad.ll.x, quad.ll.y),
            ])

    return points


# ----------------------------------------------------------------------
# Arrowheads
# ----------------------------------------------------------------------

def _as_arrowhead(
    points: np.ndarray,
    area_range: Tuple[float, float],
    filled: bool,
    closed: bool,
    width: float,
) -> Optional[Dict]:
    """
    Classify a small polygon as a homerun arrowhead.

    An arrowhead is a small triangle with one vertex clearly further from the
    centre than the rest: the tip. It may be a filled shape, but plenty of
    drawing offices draw it as a closed triangle stroked with the conductor
    pen, which plots solid at the sheet's line weight and is indistinguishable
    on paper. Both count, or every homerun on such a sheet is missed.
    """

    polygon = _unique_points(points)

    if filled:
        if not 3 <= len(polygon) <= 4:
            return None
    elif not (closed and len(polygon) == 3):
        return None

    area = _polygon_area(polygon)
    if not area_range[0] <= area <= area_range[1]:
        return None

    centroid = polygon.mean(axis=0)
    distances = np.hypot(*(polygon - centroid).T)
    # A square dot, a bullet or an equilateral mark has every corner the same
    # distance from the centre; an arrow has a tip that stands out.
    if distances.min() <= 1e-6 or distances.max() / distances.min() < 1.3:
        return None

    tip_index = int(distances.argmax())
    tip = polygon[tip_index]
    base = np.delete(polygon, tip_index, axis=0).mean(axis=0)

    direction = tip - base
    norm = float(np.hypot(*direction))
    if norm < 1e-6:
        return None

    return {
        "tip": [float(tip[0]), float(tip[1])],
        "base": [float(base[0]), float(base[1])],
        "direction": [float(direction[0] / norm), float(direction[1] / norm)],
        "length": norm,
        "area": float(area),
        "filled": filled,
        "width": width,
    }


def _is_closed(items: Sequence, tolerance: float = 0.05) -> bool:
    """True when a path returns to where it started."""

    points = _path_points(items)
    if len(points) < 4:
        return False

    start, end = points[0], points[-1]
    return abs(start[0] - end[0]) <= tolerance and abs(start[1] - end[1]) <= tolerance


def _unique_points(points: np.ndarray, tolerance: int = 2) -> np.ndarray:
    """Corner points with duplicates from shared path edges collapsed."""

    points = np.asarray(points, np.float64).reshape(-1, 2)
    if not len(points):
        return points

    seen = {}
    for point in points:
        key = (round(float(point[0]), tolerance), round(float(point[1]), tolerance))
        seen.setdefault(key, point)

    return np.array(list(seen.values()), np.float64)


def _polygon_area(polygon: np.ndarray) -> float:
    """Shoelace area."""

    x, y = polygon[:, 0], polygon[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))


# ----------------------------------------------------------------------
# Conductor hash marks
# ----------------------------------------------------------------------

def count_conductor_ticks(
    segments: np.ndarray,
    tip: Sequence[float],
    direction: Sequence[float],
    window: float,
    max_tick_length: float,
    lateral: float,
    min_tick_length: float = 0.0,
) -> int:
    """
    Count the hash marks a homerun carries: one short slash per conductor.

    Ticks sit on the run just behind the arrowhead and cross it at an angle,
    so they are short segments whose midpoint is close to the run's axis and
    whose direction is far from the run's direction.

    Args:
        segments: (N, 4) standalone one-stroke marks of the sheet. Passing the
            whole line work counts the pieces of every flattened curve nearby,
            which silently inflates the conductor count.
        tip: Arrow tip.
        direction: Unit vector the arrow points along.
        window: How far back along the run to look.
        max_tick_length: Longest segment that can be a tick.
        lateral: How far off the run's axis a tick's midpoint may sit.

    Returns:
        Number of hash marks found. Zero when the run is unmarked.
    """

    if len(segments) == 0:
        return 0

    tip = np.asarray(tip, np.float64)
    axis = np.asarray(direction, np.float64)

    starts, ends = segments[:, :2].astype(np.float64), segments[:, 2:].astype(np.float64)
    vectors = ends - starts
    lengths = np.hypot(vectors[:, 0], vectors[:, 1])

    short = (lengths >= min_tick_length) & (lengths <= max_tick_length)
    if not short.any():
        return 0

    midpoints = (starts + ends) / 2.0
    offsets = midpoints - tip

    # Distance back along the run, and sideways off it.
    along = -(offsets @ axis)
    across = np.abs(offsets[:, 0] * -axis[1] + offsets[:, 1] * axis[0])

    in_window = short & (along > 0) & (along <= window) & (across <= lateral)
    if not in_window.any():
        return 0

    # A tick crosses the run; a piece of the run itself does not.
    unit = vectors[in_window] / lengths[in_window][:, None]
    crossing = np.abs(unit @ axis) < 0.87  # more than ~30 degrees off the run

    return int(np.count_nonzero(crossing))
