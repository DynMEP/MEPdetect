"""
Trace a PDF sheet from the command line.

Renders a page, pulls its vector geometry, runs the circuit tracer and writes
the overlay and netlist next to the output directory. Detections are optional:
without them the wiring, nodes and homeruns are still traced, which is what
makes this usable for checking the tracer against a real drawing before a
symbol model exists for it.

    python tools/trace_pdf.py "plan.pdf" --page 1 --dpi 150 --out traced/
"""

import argparse
import json
import sys
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from circuit_tracer import CircuitTracer
from pdf_geometry import extract_sheet_geometry, ocr_tags_near
from result_exporter import ResultExporter


def render_page(pdf_path: Path, page_number: int, dpi: int, output_dir: Path) -> Path:
    """Render one page to PNG at the resolution the geometry is scaled to."""

    with fitz.open(str(pdf_path)) as document:
        page = document[page_number - 1]
        zoom = dpi / 72.0
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        image_path = output_dir / f"{pdf_path.stem}_page_{page_number}.png"
        pixmap.save(str(image_path))

    return image_path


def load_detections(path: Path) -> list:
    """Detections from a previous /api/detect JSON export."""

    if path is None:
        return []

    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        return data.get("detections", [])
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Trace circuits on a PDF sheet")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--out", type=Path, default=Path("traced"))
    parser.add_argument("--detections", type=Path, default=None,
                        help="detections JSON from /api/detect")
    parser.add_argument("--ocr", action="store_true",
                        help="read circuit tags off the raster when the sheet "
                             "has none as text (needs tesseract)")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    started = time.time()
    image_path = render_page(args.pdf, args.page, args.dpi, args.out)
    rendered = time.time()

    geometry = extract_sheet_geometry(args.pdf, args.page, args.dpi)
    extracted = time.time()

    if args.ocr and geometry.arrowheads and not geometry.circuit_tags:
        tips = [head["tip"] for head in geometry.arrowheads]
        found = ocr_tags_near(image_path, tips)
        geometry.texts.extend(found)
        print(f"OCR recovered {len(found)} tag(s)")

    detections = load_detections(args.detections)
    result = CircuitTracer().trace(image_path, detections, args.out, geometry=geometry)
    traced = time.time()

    if result.get("circuits") or result.get("tag_circuits"):
        ResultExporter().generate_netlist({"circuits": [result]}, args.out)

    print(f"\n{args.pdf.name} page {args.page} at {args.dpi} DPI")
    print(f"  render {rendered - started:.1f}s | geometry {extracted - rendered:.1f}s "
          f"| trace {traced - extracted:.1f}s")
    print(f"  line work: {len(geometry.segments)} segments, "
          f"{len(geometry.arrowheads)} filled arrowheads, "
          f"{len(geometry.circuit_tags)} circuit tags in text")
    print(f"  conductor pen: {result['conductor_lineweight_pt']} pt (source: {result['source']})")
    print(f"  stats: {json.dumps(result['stats'])}")

    homeruns = result["homeruns"]
    if homeruns:
        tagged = [h for h in homeruns if h.get("circuit_tag")]
        counted = [h for h in homeruns if h.get("conductor_count")]
        print(f"  homeruns: {len(homeruns)} ({len(tagged)} tagged, "
              f"{len(counted)} with conductor marks)")
        for homerun in homeruns[:8]:
            print(f"     ({homerun['x']}, {homerun['y']}) tag={homerun.get('circuit_tag')} "
                  f"conductors={homerun.get('conductor_count')} panel={homerun.get('panel_ref')}")

    if result["tag_circuits"]:
        print(f"  annotated circuits: {len(result['tag_circuits'])}")
        for circuit in result["tag_circuits"][:8]:
            print(f"     {circuit['circuit_tag']}: {circuit['device_count']} device(s)")

    print(f"  overlay: {result['overlay_path']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
