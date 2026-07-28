"""
Circuit Tracer
Builds a circuit netlist for a drawing from its YOLO symbol detections.

A sheet states its circuiting in one of two ways, and both turn up in the same
plan set:

  * It draws the conductor runs, ending each homerun in an arrowhead. The runs
    are followed and the symbols on them are chained into circuits.
  * It draws no wiring at all and annotates each symbol with its panel-circuit
    designation instead, as Revit does. The tags are read and the symbols
    carrying the same one are grouped.

Given the source PDF's vector geometry, connectivity comes from the drawing's
own line work, which is exact: conductors are isolated by the pen they are
plotted with, taps and arrowheads are joined by measured tolerances, and tags
are real text. A tag also lets a circuit be followed onto the next sheet.

Falling back to a scan, the pixels are traced instead: binarize, blank the
symbol boxes, discard blob-like components, take the connected runs, thin them
for junction nodes, and read an arrowhead from the thickness at a run's end.

All coordinates in the returned structure are in the coordinate space of the
input image, the same space as the detection bounding boxes.
"""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from pdf_geometry import (
    count_conductor_ticks,
    find_circuit_tag,
    is_circuit_tag,
    normalize_tag,
)
from segment_graph import SegmentGraph


# Symbol classes that terminate a circuit instead of passing through it.
PANEL_KEYWORDS = (
    "panel", "panelboard", "switchboard", "loadcenter", "load_center",
    "mdp", "distribution", "disconnect",
)

_OVERLAY_COLORS = [
    (255, 128, 0), (0, 176, 255), (0, 200, 83), (170, 0, 255),
    (255, 61, 127), (0, 229, 255), (255, 214, 0), (124, 77, 255),
]


def merge_cross_sheet_circuits(circuit_data: List[Dict]) -> List[Dict]:
    """
    Follow a circuit across the sheets it runs through.

    A branch circuit does not stop at a matchline: the same panel-circuit
    designation on another sheet is the same circuit, and an estimator counting
    devices per circuit needs them added together rather than listed twice.
    """

    groups: Dict[str, Dict] = {}

    def entry(tag: str) -> Dict:
        return groups.setdefault(tag, {
            "panel": tag.rsplit("-", 1)[0] if "-" in tag else None,
            "sheets": [],
            "devices": [],
            "homerun_count": 0,
        })

    for sheet_result in circuit_data:
        sheet = sheet_result.get('sheet', '')

        for circuit in sheet_result.get('tag_circuits', []):
            group = entry(circuit['circuit_tag'])
            group['sheets'].append(sheet)
            for device in circuit['devices']:
                group['devices'].append(sheet + ":" + device['ref'])

        for circuit in sheet_result.get('circuits', []):
            tag = circuit.get('circuit_tag')
            if not tag:
                continue
            group = entry(tag)
            group['sheets'].append(sheet)
            group['homerun_count'] += circuit.get('homerun_count', 0)
            for device in circuit['devices']:
                group['devices'].append(sheet + ":" + device['ref'])

    merged = []
    for tag in sorted(groups):
        group = groups[tag]
        devices = sorted(set(group['devices']))
        sheets = sorted(set(group['sheets']))
        merged.append({
            "circuit_tag": tag,
            "panel": group['panel'],
            "sheets": sheets,
            "sheet_count": len(sheets),
            "device_count": len(devices),
            "devices": devices,
            "homerun_count": group['homerun_count'],
        })

    return merged


def summarize_circuits(circuit_data: List[Dict]) -> Dict[str, int]:
    """Roll the per-sheet netlists up into job-level counts"""

    def total(key: str) -> int:
        return sum(sheet.get('stats', {}).get(key, 0) for sheet in circuit_data)

    return {
        "sheets_traced": len(circuit_data),
        "annotated_circuits": total('tag_circuit_count'),
        "circuits": total('circuit_count'),
        "nets": total('net_count'),
        "nodes": total('node_count'),
        "homeruns": total('homerun_count'),
        "connected_symbols": total('connected_symbols'),
        "unconnected_symbols": total('unconnected_symbols'),
    }


class _UnionFind:
    """Minimal union-find over hashable keys."""

    def __init__(self):
        self._parent = {}

    def find(self, item):
        self._parent.setdefault(item, item)
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, a, b):
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_b] = root_a


class CircuitTracer:
    """Line following, node detection and homerun tracing over a drawing."""

    def __init__(
        self,
        max_dimension: int = 2500,
        min_run_length: int = 40,
        gap_bridge: int = 7,
        terminal_margin: float = 0.35,
        thickness_factor: float = 6.0,
        arrow_thickness_factor: float = 2.0,
        max_devices_per_run: int = 12,
        tag_radius_boxes: float = 3.0,
        min_homerun_arrows: int = 3,
        min_arrow_spread: float = 0.25,
        max_conductor_share: float = 0.35,
        panel_keywords: Sequence[str] = PANEL_KEYWORDS,
    ):
        """
        Args:
            max_dimension: Long side of the working image. Tracing runs on a
                downscaled copy; results are mapped back to input coordinates.
            min_run_length: Shortest conductor run to keep, in working pixels.
            gap_bridge: Largest dashed-line gap to bridge, in working pixels.
            terminal_margin: Search band around a symbol box, as a fraction of
                the box size, in which a wire counts as landing on it.
            thickness_factor: A component is a wire when its average thickness
                stays below this many stroke widths.
            arrow_thickness_factor: Line work at an endpoint must be at least
                this many stroke widths thick to count as an arrowhead.
            max_devices_per_run: Above this, a run is background line work
                brushing past symbols rather than a branch circuit.
            tag_radius_boxes: How far from a symbol, in multiples of its box
                size, its circuit tag may be annotated.
            min_homerun_arrows: Arrows a pen needs before its spread is judged.
                Below this there are too few to tell a legend from a plan.
            min_arrow_spread: How far those arrows must spread across the sheet
                diagonal, so a legend's cluster of arrows is not mistaken for
                wiring covering the plan.
            max_conductor_share: Largest share of the sheet's drawn length the
                wiring can account for. The architectural background is most of
                a plan; branch wiring never is.
            panel_keywords: Class-name fragments that mark a circuit terminus.
        """
        self.max_dimension = max_dimension
        self.min_run_length = min_run_length
        self.gap_bridge = gap_bridge
        self.terminal_margin = terminal_margin
        self.thickness_factor = thickness_factor
        self.arrow_thickness_factor = arrow_thickness_factor
        self.max_devices_per_run = max_devices_per_run
        self.tag_radius_boxes = tag_radius_boxes
        self.min_homerun_arrows = min_homerun_arrows
        self.min_arrow_spread = min_arrow_spread
        self.max_conductor_share = max_conductor_share
        self.panel_keywords = tuple(k.lower() for k in panel_keywords)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def trace(
        self,
        image_path: Path,
        detections: List[Dict],
        output_dir: Optional[Path] = None,
        geometry=None,
        conductor_lineweight: Optional[float] = None,
    ) -> Dict:
        """
        Trace conductors and build the netlist for one sheet.

        Args:
            image_path: Sheet the detections were produced from.
            detections: Detection dicts from DetectionEngine.
            output_dir: When given, a traced overlay PNG is written here.
            geometry: Optional SheetGeometry from the source PDF. When present
                the conductors come from the drawing's own line work instead of
                the pixels, homerun arrowheads are read exactly, and circuit
                tags are picked up from the sheet's text.
            conductor_lineweight: Force the pen the conductors are drawn with,
                in PDF points, instead of inferring it from the drawing.

        Returns:
            Netlist dictionary (nets, nodes, homeruns, circuits, stats).
        """

        gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError(f"Could not read image: {image_path}")

        scale = min(1.0, self.max_dimension / max(gray.shape[:2]))
        if scale < 1.0:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        ink = self._binarize(gray)
        stroke_w = self._stroke_width(ink)

        refs = self._assign_refs(detections)
        boxes = self._scaled_boxes(detections, scale, gray.shape)

        # Blank the symbols. The box is tight to the symbol, so grow it by a
        # stroke to take the symbol's own outline with it.
        open_ink = ink.copy()
        pad = int(np.ceil(stroke_w))
        height, width = open_ink.shape
        for x1, y1, x2, y2 in boxes:
            open_ink[max(0, y1 - pad):min(height, y2 + pad),
                     max(0, x1 - pad):min(width, x2 + pad)] = 0

        has_geometry = geometry is not None and geometry.has_line_work
        texts = list(geometry.texts) if geometry is not None else []
        lineweight = None
        graph = None
        nets_by_label = {}

        if has_geometry:
            # The drawing states its own connectivity; rasterizing it would
            # only lose the taps and the arrowheads again.
            source = "vector"
            coord_scale = 1.0
            graph, net_of_segment, nets_by_label, lineweight = self._vector_nets(
                geometry, detections, conductor_lineweight, scale
            )
            members, orphans = self._bind_devices_vector(
                graph, net_of_segment, detections, refs
            )
            junctions = self._vector_junctions(graph, net_of_segment, nets_by_label)
            homeruns = self._vector_homeruns(
                geometry, lineweight, graph, net_of_segment, detections, refs, texts
            )
            nets = self._build_vector_nets(
                graph, nets_by_label, members, junctions, homeruns
            )
        else:
            source = "raster"
            coord_scale = scale
            wires, labels, net_ids = self._wire_mask(open_ink, stroke_w)
            skeleton = self._thin(wires)
            junctions, endpoints = self._skeleton_nodes(skeleton, labels, net_ids)
            members, orphans = self._bind_devices(labels, boxes, detections, refs, net_ids)
            homeruns = self._trace_homeruns(
                open_ink, skeleton, endpoints, boxes, detections, refs, stroke_w
            )
            nets = self._build_nets(
                labels, skeleton, net_ids, members, junctions, homeruns, scale
            )

        symbol_tags = self._assign_tags(detections, refs, texts, scale)
        circuits = self._build_circuits(nets, members, homeruns)
        self._label_circuits(circuits, symbol_tags, homeruns, nets)
        tag_circuits = self._build_tag_circuits(symbol_tags, image_path.name)

        for net in nets:
            net.pop("net_label", None)

        overlay_path = None
        if output_dir is not None:
            if has_geometry:
                overlay_path = self._save_vector_overlay(
                    gray, scale, graph, nets_by_label, junctions, homeruns,
                    members, circuits, symbol_tags, boxes, image_path,
                    Path(output_dir)
                )
            else:
                overlay_path = self._save_overlay(
                    gray, labels, net_ids, junctions, homeruns, members,
                    circuits, image_path, Path(output_dir)
                )

        return {
            "sheet": image_path.name,
            "source": source,
            "conductor_lineweight_pt": lineweight,
            "nets": nets,
            "nodes": [self._scale_node(n, coord_scale) for n in junctions],
            "homeruns": [self._scale_homerun(h, coord_scale) for h in homeruns],
            "circuits": circuits,
            "tag_circuits": tag_circuits,
            "symbol_tags": symbol_tags,
            "unconnected_symbols": orphans,
            "overlay_path": str(overlay_path) if overlay_path else None,
            "stats": {
                "net_count": len(nets),
                "node_count": len(junctions),
                "homerun_count": len(homeruns),
                "circuit_count": len(circuits),
                "tagged_symbols": len(symbol_tags),
                "tag_circuit_count": len(tag_circuits),
                "connected_symbols": len({m["detection_index"] for m in members}),
                "unconnected_symbols": len(orphans),
                "traced_length_px": round(sum(n["length_px"] for n in nets), 1),
                "working_scale": round(scale, 4),
                "stroke_width_px": round(stroke_w / scale, 2),
            },
        }

    # ------------------------------------------------------------------
    # Image preparation
    # ------------------------------------------------------------------

    def _binarize(self, gray: np.ndarray) -> np.ndarray:
        """Ink mask: 255 where the drawing has line work."""

        smoothed = cv2.medianBlur(gray, 3)
        _, ink = cv2.threshold(smoothed, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

        # Otsu fails on sheets with a dark background or heavy shading; fall
        # back to a local threshold when it marks an implausible amount of ink.
        if float(np.count_nonzero(ink)) / ink.size > 0.35:
            ink = cv2.adaptiveThreshold(
                smoothed, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                cv2.THRESH_BINARY_INV, 25, 10
            )

        return ink

    def _stroke_width(self, ink: np.ndarray) -> float:
        """Typical line width in working pixels."""

        dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
        values = dist[ink > 0]
        if values.size == 0:
            return 1.0
        return float(max(1.0, 2.0 * np.percentile(values, 75)))

    def _scaled_boxes(
        self, detections: List[Dict], scale: float, shape: Tuple[int, int]
    ) -> List[Tuple[int, int, int, int]]:
        """Detection boxes in working-image integer coordinates."""

        height, width = shape[:2]
        boxes = []
        for det in detections:
            bbox = det.get("bbox", {})
            x1 = int(np.clip(round(bbox.get("x1", 0) * scale), 0, width - 1))
            y1 = int(np.clip(round(bbox.get("y1", 0) * scale), 0, height - 1))
            x2 = int(np.clip(round(bbox.get("x2", 0) * scale), x1 + 1, width))
            y2 = int(np.clip(round(bbox.get("y2", 0) * scale), y1 + 1, height))
            boxes.append((x1, y1, x2, y2))
        return boxes

    def _assign_refs(self, detections: List[Dict]) -> List[str]:
        """Stable reference designators, e.g. RECEPTACLE-3."""

        counters: Dict[str, int] = defaultdict(int)
        refs = []
        for det in detections:
            name = str(det.get("class_name", "SYMBOL")).upper().replace(" ", "_")
            counters[name] += 1
            refs.append(f"{name}-{counters[name]}")
        return refs

    # ------------------------------------------------------------------
    # Line following
    # ------------------------------------------------------------------

    def _wire_mask(
        self, open_ink: np.ndarray, stroke_w: float
    ) -> Tuple[np.ndarray, np.ndarray, Dict[int, str]]:
        """
        Keep only the long, thin components: the conductor runs.

        Returns:
            (wire mask, label image, {label -> net id})
        """

        mask = open_ink
        if self.gap_bridge >= 3:
            kernel_h = np.ones((1, self.gap_bridge), np.uint8)
            kernel_v = np.ones((self.gap_bridge, 1), np.uint8)
            mask = cv2.bitwise_or(
                cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_h),
                cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_v),
            )

        return self._filter_runs(mask, max_thickness=self.thickness_factor * stroke_w)

    def _filter_runs(
        self, mask: np.ndarray, max_thickness: Optional[float] = None
    ) -> Tuple[np.ndarray, np.ndarray, Dict[int, str]]:
        """
        Keep the components long enough to be a conductor run, and number them.

        Returns:
            (wire mask, label image, {label -> net id})
        """

        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

        lut = np.zeros(count, np.uint8)
        net_ids: Dict[int, str] = {}

        for label in range(1, count):
            width = stats[label, cv2.CC_STAT_WIDTH]
            height = stats[label, cv2.CC_STAT_HEIGHT]
            area = stats[label, cv2.CC_STAT_AREA]
            extent = max(width, height)

            if extent < self.min_run_length:
                continue
            # Average thickness along the run: lines stay thin, blocks do not.
            if max_thickness is not None and area / float(extent) > max_thickness:
                continue

            lut[label] = 1
            net_ids[label] = f"N{len(net_ids) + 1}"

        wires = lut[labels]
        labels = np.where(wires > 0, labels, 0).astype(np.int32)

        return (wires * 255).astype(np.uint8), labels, net_ids

    def _vector_nets(
        self,
        geometry,
        detections: List[Dict],
        forced_lineweight: Optional[float],
        scale: float,
    ) -> Tuple[Optional[SegmentGraph], Dict[int, int], Dict[int, np.ndarray], Optional[float]]:
        """
        Build the conductor graph from the sheet's own line work.

        The drawing office gives conductors their own pen, so the wiring is
        isolated by lineweight rather than guessed from pixels. Which pen holds
        it is settled by evidence: the pen whose runs chain symbols together
        and carry the homerun arrowheads.

        Returns:
            (graph, {segment -> net}, {net -> segment indices}, lineweight)
        """

        classes = geometry.width_classes()
        if not classes:
            return None, {}, {}, None

        tolerance = max(1.0, geometry.dpi / 144.0)
        min_length = self.min_run_length / max(scale, 1e-6)
        boxes = self._detection_boxes(detections)

        def graph_for(indices, width=None, join_taps=True):
            graph = SegmentGraph(
                geometry.segments[indices], tolerance, join_taps=join_taps
            )
            self._attach_arrowheads(graph, geometry, width)

            nets = graph.nets(min_length=min_length)
            net_of_segment = {
                int(segment): net_id
                for net_id, members in nets.items()
                for segment in members
            }
            return graph, net_of_segment, nets

        if forced_lineweight is not None:
            for width, indices in classes:
                if abs(width - forced_lineweight) < 1e-6:
                    graph, net_of_segment, nets = graph_for(indices, width)
                    return graph, net_of_segment, nets, width

        if not boxes:
            # Which pen holds the wiring is decided by watching it chain
            # symbols together. With no symbols there is nothing to watch, so
            # take all the line work rather than pick a pen wrong.
            graph, net_of_segment, nets = graph_for(np.arange(len(geometry.segments)))
            return graph, net_of_segment, nets, None

        arrow_bases = [head["base"] for head in geometry.arrowheads]
        sheet_diagonal = float(np.hypot(geometry.width, geometry.height))

        lengths = np.hypot(
            geometry.segments[:, 2] - geometry.segments[:, 0],
            geometry.segments[:, 3] - geometry.segments[:, 1],
        )
        total_length = float(lengths.sum()) or 1.0

        best = None
        for width, indices in classes:
            if float(lengths[indices].sum()) / total_length > self.max_conductor_share:
                continue  # This pen draws the building, not the circuits.

            graph, net_of_segment, nets = graph_for(indices, width, join_taps=False)
            if not nets:
                continue

            score, eligible = self._score_conductors(
                graph, net_of_segment, boxes, arrow_bases, sheet_diagonal
            )
            if not eligible:
                continue
            if best is None or score > best[0]:
                best = (score, width, indices)

        if best is None or best[0] <= 0:
            # No pen behaves like wiring: the sheet annotates its circuits
            # instead of drawing them. Say so rather than tracing the walls.
            return None, {}, {}, None

        _, lineweight, indices = best
        graph, net_of_segment, nets = graph_for(indices, lineweight)

        return graph, net_of_segment, nets, lineweight

    def _attach_arrowheads(self, graph: SegmentGraph, geometry, lineweight) -> int:
        """
        Bridge each arrowhead to the run it terminates.

        Measured on real sheets, the arrow sits a consistent short gap off the
        end of its run, so without this every homerun lands on a stub of its
        own instead of on the circuit it belongs to.
        """

        joined = 0
        for head in geometry.arrowheads:
            if lineweight is not None and not head.get("filled"):
                if abs(head.get("width", 0.0) - lineweight) > 1e-6:
                    continue

            length = max(head["length"], 1.0)
            centre = (
                (head["tip"][0] + 2 * head["base"][0]) / 3.0,
                (head["tip"][1] + 2 * head["base"][1]) / 3.0,
            )
            if graph.join_across_gap(centre, radius=length * 1.15, reach=length * 1.5):
                joined += 1

        return joined

    def _detection_boxes(self, detections: List[Dict]) -> List[Tuple[float, float, float, float]]:
        """Detection boxes in the drawing's own pixel coordinates."""

        boxes = []
        for det in detections:
            bbox = det.get("bbox", {})
            boxes.append((
                float(bbox.get("x1", 0.0)), float(bbox.get("y1", 0.0)),
                float(bbox.get("x2", 0.0)), float(bbox.get("y2", 0.0)),
            ))
        return boxes

    def _score_conductors(
        self,
        graph: SegmentGraph,
        net_of_segment: Dict[int, int],
        boxes: List[Tuple[float, float, float, float]],
        arrow_bases: List[Sequence[float]],
        sheet_diagonal: float,
    ) -> Tuple[int, bool]:
        """
        How much a pen behaves like branch wiring, and whether it really is.

        Wiring chains a handful of symbols per run and carries the homerun
        arrowheads. Chaining alone is not enough to convict a pen: walls chain
        symbols too, and on a sheet that annotates its circuits instead of
        drawing them, the wall pen would otherwise be traced and reported as
        circuits that do not exist. So a pen is only eligible if it also
        carries homerun arrows spread across the sheet - a legend's cluster of
        arrows does not qualify.

        Returns:
            (score, eligible)
        """

        devices_per_net: Dict[int, int] = defaultdict(int)
        for box in boxes:
            margin = self._terminal_margin_for(box)
            for net_id in graph.nets_in_box(box, margin, net_of_segment):
                devices_per_net[net_id] += 1

        chained = sum(
            1 for count in devices_per_net.values()
            if 2 <= count <= self.max_devices_per_run
        )

        on_pen = []
        for base in arrow_bases:
            if graph.net_at_point(base, net_of_segment, reach=graph.tolerance * 4) is not None:
                on_pen.append(base)

        # No arrow anywhere on the pen: no evidence it is wiring at all.
        eligible = len(on_pen) >= 1

        # Enough arrows to judge how they sit: wiring arrows are spread over
        # the plan, a legend's are in one corner.
        if eligible and len(on_pen) >= self.min_homerun_arrows and sheet_diagonal > 0:
            points = np.asarray(on_pen, np.float64)
            spread = float(np.hypot(*(points.max(axis=0) - points.min(axis=0))))
            eligible = spread >= self.min_arrow_spread * sheet_diagonal

        return chained * 10 + len(on_pen), eligible

    def _terminal_margin_for(self, box: Sequence[float]) -> float:
        """How far outside its box a run still lands on a symbol."""

        return max(3.0, self.terminal_margin * min(box[2] - box[0], box[3] - box[1]))

    def _bind_devices_vector(
        self,
        graph: Optional[SegmentGraph],
        net_of_segment: Dict[int, int],
        detections: List[Dict],
        refs: List[str],
    ) -> Tuple[List[Dict], List[Dict]]:
        """Attach every symbol to the runs that reach it."""

        members: List[Dict] = []
        connected = set()

        if graph is not None:
            for index, (det, ref) in enumerate(zip(detections, refs)):
                box = self._detection_boxes([det])[0]
                margin = self._terminal_margin_for(box)

                for net_id, point in graph.nets_in_box(box, margin, net_of_segment).items():
                    members.append({
                        "net_label": net_id,
                        "net_id": f"N{net_id}",
                        "detection_index": index,
                        "ref": ref,
                        "class_name": det.get("class_name", "unknown"),
                        "confidence": round(float(det.get("confidence", 0)), 3),
                        "is_panel": self._is_panel(det.get("class_name", "")),
                        "terminal": [int(round(point[0])), int(round(point[1]))],
                    })
                    connected.add(index)

        orphans = [
            {
                "detection_index": index,
                "ref": refs[index],
                "class_name": det.get("class_name", "unknown"),
            }
            for index, det in enumerate(detections)
            if index not in connected
        ]

        return members, orphans

    def _vector_junctions(
        self,
        graph: Optional[SegmentGraph],
        net_of_segment: Dict[int, int],
        nets: Dict[int, np.ndarray],
    ) -> List[Dict]:
        """Junction nodes: where three or more runs meet, or a run taps one."""

        if graph is None:
            return []

        return [
            {**node, "net_id": f"N{node['net_label']}"}
            for node in graph.junctions(net_of_segment)
        ]

    def _thin(self, mask: np.ndarray, max_iterations: int = 30) -> np.ndarray:
        """Zhang-Suen thinning, vectorized. Returns a 0/1 skeleton."""

        img = (mask > 0).astype(np.uint8)

        for _ in range(max_iterations):
            removed = False
            for step in (0, 1):
                padded = np.pad(img, 1)
                p2 = padded[0:-2, 1:-1]
                p3 = padded[0:-2, 2:]
                p4 = padded[1:-1, 2:]
                p5 = padded[2:, 2:]
                p6 = padded[2:, 1:-1]
                p7 = padded[2:, 0:-2]
                p8 = padded[1:-1, 0:-2]
                p9 = padded[0:-2, 0:-2]

                neighbours = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                ring = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
                transitions = sum(
                    ((ring[i] == 0) & (ring[i + 1] == 1)).astype(np.uint8)
                    for i in range(8)
                )

                if step == 0:
                    cond_a, cond_b = p2 * p4 * p6, p4 * p6 * p8
                else:
                    cond_a, cond_b = p2 * p4 * p8, p2 * p6 * p8

                doomed = (
                    (img == 1)
                    & (neighbours >= 2) & (neighbours <= 6)
                    & (transitions == 1)
                    & (cond_a == 0) & (cond_b == 0)
                )

                if doomed.any():
                    img[doomed] = 0
                    removed = True

            if not removed:
                break

        return img

    # ------------------------------------------------------------------
    # Node detection
    # ------------------------------------------------------------------

    def _branch_count(self, skeleton: np.ndarray) -> np.ndarray:
        """
        Branches leaving each skeleton pixel, as the crossing number: the
        0 -> 1 transitions around the 8-neighbourhood.

        A plain neighbour count would read every diagonal staircase pixel as a
        junction, because it has three touching neighbours on one branch.
        """

        padded = np.pad(skeleton, 1)
        ring = [
            padded[0:-2, 1:-1], padded[0:-2, 2:], padded[1:-1, 2:], padded[2:, 2:],
            padded[2:, 1:-1], padded[2:, 0:-2], padded[1:-1, 0:-2], padded[0:-2, 0:-2],
        ]
        ring.append(ring[0])

        return sum(
            ((ring[i] == 0) & (ring[i + 1] == 1)).astype(np.uint8)
            for i in range(8)
        )

    def _skeleton_nodes(
        self, skeleton: np.ndarray, labels: np.ndarray, net_ids: Dict[int, str]
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Junction nodes (3+ branches) and free run ends of the skeleton.

        Junction pixels are clustered so a single tee or cross yields one node.
        """

        branches = self._branch_count(skeleton)
        on_wire = skeleton == 1

        junction_mask = (on_wire & (branches >= 3)).astype(np.uint8)
        endpoint_mask = on_wire & (branches == 1)

        junctions = []
        count, clusters, _, centroids = cv2.connectedComponentsWithStats(junction_mask, 8)
        for cluster in range(1, count):
            x, y = centroids[cluster]
            xi = int(np.clip(round(x), 0, labels.shape[1] - 1))
            yi = int(np.clip(round(y), 0, labels.shape[0] - 1))
            net_label = int(labels[yi, xi])
            if net_label not in net_ids:
                continue

            junctions.append({
                "x": xi,
                "y": yi,
                "net_label": net_label,
                "net_id": net_ids[net_label],
                "degree": int(branches[clusters == cluster].max()),
            })

        endpoints = []
        ys, xs = np.nonzero(endpoint_mask)
        for y, x in zip(ys.tolist(), xs.tolist()):
            net_label = int(labels[y, x])
            if net_label in net_ids:
                endpoints.append({"x": x, "y": y, "net_label": net_label})

        return junctions, endpoints

    # ------------------------------------------------------------------
    # Device / net binding
    # ------------------------------------------------------------------

    def _bind_devices(
        self,
        labels: np.ndarray,
        boxes: List[Tuple[int, int, int, int]],
        detections: List[Dict],
        refs: List[str],
        net_ids: Dict[int, str],
    ) -> Tuple[List[Dict], List[Dict]]:
        """Attach every symbol to the nets landing on its terminal band."""

        height, width = labels.shape
        members: List[Dict] = []
        connected = set()

        for index, (box, det, ref) in enumerate(zip(boxes, detections, refs)):
            x1, y1, x2, y2 = box
            margin = max(3, int(round(self.terminal_margin * min(x2 - x1, y2 - y1))))

            rx1, ry1 = max(0, x1 - margin), max(0, y1 - margin)
            rx2, ry2 = min(width, x2 + margin), min(height, y2 + margin)
            band = labels[ry1:ry2, rx1:rx2]

            for label in np.unique(band):
                label = int(label)
                if label == 0 or label not in net_ids:
                    continue

                ys, xs = np.nonzero(band == label)
                members.append({
                    "net_label": label,
                    "net_id": net_ids[label],
                    "detection_index": index,
                    "ref": ref,
                    "class_name": det.get("class_name", "unknown"),
                    "confidence": round(float(det.get("confidence", 0)), 3),
                    "is_panel": self._is_panel(det.get("class_name", "")),
                    "terminal": [int(rx1 + xs.mean()), int(ry1 + ys.mean())],
                })
                connected.add(index)

        orphans = [
            {
                "detection_index": index,
                "ref": refs[index],
                "class_name": det.get("class_name", "unknown"),
            }
            for index, det in enumerate(detections)
            if index not in connected
        ]

        return members, orphans

    def _is_panel(self, class_name: str) -> bool:
        name = str(class_name).lower()
        return any(keyword in name for keyword in self.panel_keywords)

    # ------------------------------------------------------------------
    # Homerun tracing
    # ------------------------------------------------------------------

    def _trace_homeruns(
        self,
        open_ink: np.ndarray,
        skeleton: np.ndarray,
        endpoints: List[Dict],
        boxes: List[Tuple[int, int, int, int]],
        detections: List[Dict],
        refs: List[str],
        stroke_w: float,
    ) -> List[Dict]:
        """
        A homerun ends in a solid arrowhead. Find the endpoints where the line
        work is several strokes thick — that is the filled head — then see
        which panel the arrow points at.
        """

        if not endpoints:
            return []

        radius = max(5, int(round(4 * stroke_w)))
        _, ink_labels = cv2.connectedComponents(open_ink, 8)
        distance = cv2.distanceTransform(open_ink, cv2.DIST_L2, 5)

        grid_y, grid_x = np.ogrid[-radius:radius + 1, -radius:radius + 1]
        disc = (grid_x ** 2 + grid_y ** 2) <= radius ** 2

        panels = [
            (index, refs[index], boxes[index])
            for index, det in enumerate(detections)
            if self._is_panel(det.get("class_name", ""))
        ]

        height, width = open_ink.shape
        homeruns = []

        for endpoint in endpoints:
            x, y = endpoint["x"], endpoint["y"]
            if x - radius < 0 or y - radius < 0 or x + radius >= width or y + radius >= height:
                continue

            component = int(ink_labels[y, x])
            if component == 0:
                continue

            window = (slice(y - radius, y + radius + 1), slice(x - radius, x + radius + 1))
            head = (ink_labels[window] == component) & disc
            if not head.any():
                continue

            # Thickest point of the run near its end, in stroke widths.
            local_width = 2.0 * float(distance[window][head].max())
            if local_width < self.arrow_thickness_factor * stroke_w:
                continue

            direction = self._endpoint_direction(skeleton, x, y, radius * 3)
            panel_index, panel_ref = self._panel_in_line(x, y, direction, panels)

            homeruns.append({
                "net_label": endpoint["net_label"],
                "x": x,
                "y": y,
                "direction": [round(direction[0], 3), round(direction[1], 3)],
                "arrow_strength": round(local_width / stroke_w, 2),
                "panel_detection_index": panel_index,
                "panel_ref": panel_ref,
            })

        return homeruns

    def _vector_homeruns(
        self,
        geometry,
        lineweight: Optional[float],
        graph: Optional[SegmentGraph],
        net_of_segment: Dict[int, int],
        detections: List[Dict],
        refs: List[str],
        texts: List[Dict],
    ) -> List[Dict]:
        """
        Homeruns read straight off the drawing's own arrowheads.

        The sheet says where its arrows are, so there is nothing to infer: the
        tip, the direction and the run it sits on are exact. What is left is
        reading the circuit tag beside it and counting the conductor hash
        marks behind it.
        """

        if not geometry.arrowheads or graph is None:
            return []

        # Only the sheet's standalone one-stroke marks can be conductor hash
        # marks; the pieces of a flattened curve can not.
        tick_marks = geometry.segments[geometry.standalone] if len(geometry.standalone)             else geometry.segments
        heads = geometry.arrowheads

        if lineweight is not None:
            on_conductor_pen = (
                np.isclose(geometry.widths, lineweight) & geometry.standalone
                if len(geometry.standalone) else np.zeros(len(geometry.segments), bool)
            )
            if on_conductor_pen.any():
                tick_marks = geometry.segments[on_conductor_pen]

            # An arrow drawn with the conductor pen is a homerun; one drawn
            # with another pen belongs to a legend, a detail or a door swing.
            on_pen = [
                head for head in heads
                if head.get("filled") or abs(head.get("width", 0.0) - lineweight) < 1e-6
            ]
            if on_pen:
                heads = on_pen

        panels = [
            (index, refs[index], self._detection_boxes([det])[0])
            for index, det in enumerate(detections)
            if self._is_panel(det.get("class_name", ""))
        ]

        homeruns = []
        for head in heads:
            net_label = graph.net_at_point(
                head["base"], net_of_segment, reach=graph.tolerance * 4
            )
            if net_label is None:
                continue

            tip = head["tip"]
            direction = head["direction"]
            length = max(head["length"], 1.0)

            panel_index, panel_ref = self._panel_in_line(
                tip[0], tip[1], tuple(direction), panels
            )
            tag = find_circuit_tag(texts, tip, radius=self.tag_radius_boxes * 2 * length)
            conductors = count_conductor_ticks(
                tick_marks,
                tip=tip,
                direction=direction,
                window=6 * length,
                min_tick_length=0.4 * length,
                max_tick_length=2.5 * length,
                lateral=1.5 * length,
            )

            homeruns.append({
                "net_label": net_label,
                "x": int(round(tip[0])),
                "y": int(round(tip[1])),
                "direction": [round(direction[0], 3), round(direction[1], 3)],
                "arrow_strength": None,
                "panel_detection_index": panel_index,
                "panel_ref": panel_ref,
                "circuit_tag": tag["tag"] if tag else None,
                "conductor_count": conductors or None,
            })

        return homeruns

    # ------------------------------------------------------------------
    # Circuit tags
    # ------------------------------------------------------------------

    def _assign_tags(
        self,
        detections: List[Dict],
        refs: List[str],
        texts: List[Dict],
        scale: float,
    ) -> List[Dict]:
        """
        Attach each panel-circuit annotation to the symbol it labels.

        Sheets drawn in Revit carry no conductors at all: the circuit is stated
        next to the device instead. Reading those tags is the only way to get a
        netlist off such a sheet, and unlike tracing it is exact.

        Each tag belongs to its nearest symbol, so a tag is never counted twice.
        """

        tags = [word for word in texts if is_circuit_tag(word["text"])]
        if not tags or not detections:
            return []

        centres = np.array([
            [det.get("bbox", {}).get("center_x", 0.0), det.get("bbox", {}).get("center_y", 0.0)]
            for det in detections
        ], np.float64)
        sizes = np.array([
            max(det.get("bbox", {}).get("width", 0.0), det.get("bbox", {}).get("height", 0.0))
            for det in detections
        ], np.float64)
        radii = np.maximum(sizes * self.tag_radius_boxes, 1.0)

        # Distance from every tag to every symbol, then match the pairs that
        # choose each other. On a dense sheet a tag can sit closer to a
        # neighbour's device than to its own, and taking nearest-wins alone
        # puts the wrong circuit number on the takeoff.
        positions = np.array([[word["x"], word["y"]] for word in tags], np.float64)
        distances = np.hypot(
            positions[:, None, 0] - centres[None, :, 0],
            positions[:, None, 1] - centres[None, :, 1],
        )
        allowed = distances <= radii[None, :]
        masked = np.where(allowed, distances, np.inf)

        nearest_device = np.argmin(masked, axis=1)
        nearest_tag = np.argmin(masked, axis=0)

        assigned: Dict[int, Dict] = {}

        def claim(tag_index: int, device_index: int) -> None:
            distance = float(distances[tag_index, device_index])
            current = assigned.get(device_index)
            if current is None or distance < current["distance"]:
                assigned[device_index] = {
                    "detection_index": device_index,
                    "ref": refs[device_index],
                    "class_name": detections[device_index].get("class_name", "unknown"),
                    "tag": normalize_tag(tags[tag_index]["text"]),
                    "distance": round(distance, 1),
                    "source": tags[tag_index].get("source", "pdf_text"),
                }

        matched_tags = set()
        for tag_index in range(len(tags)):
            device_index = int(nearest_device[tag_index])
            if not np.isfinite(masked[tag_index, device_index]):
                continue
            if int(nearest_tag[device_index]) == tag_index:
                claim(tag_index, device_index)
                matched_tags.add(tag_index)

        # Whatever is left over falls back to nearest-within-radius, skipping
        # symbols that already agreed on a tag.
        for tag_index in range(len(tags)):
            if tag_index in matched_tags:
                continue
            order = np.argsort(masked[tag_index])
            for device_index in order:
                device_index = int(device_index)
                if not np.isfinite(masked[tag_index, device_index]):
                    break
                if device_index not in assigned:
                    claim(tag_index, device_index)
                    break

        return [assigned[index] for index in sorted(assigned)]

    def _build_tag_circuits(self, symbol_tags: List[Dict], sheet: str) -> List[Dict]:
        """Group the symbols that carry the same panel-circuit designation."""

        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for entry in symbol_tags:
            grouped[entry["tag"]].append(entry)

        circuits = []
        for tag in sorted(grouped):
            members = grouped[tag]
            panel = tag.rsplit("-", 1)[0] if "-" in tag else None
            circuits.append({
                "circuit_tag": tag,
                "panel": panel,
                "sheet": sheet,
                "device_count": len(members),
                "devices": [
                    {
                        "ref": member["ref"],
                        "class_name": member["class_name"],
                        "detection_index": member["detection_index"],
                    }
                    for member in members
                ],
            })

        return circuits

    def _label_circuits(
        self,
        circuits: List[Dict],
        symbol_tags: List[Dict],
        homeruns: List[Dict],
        nets: List[Dict],
    ) -> None:
        """
        Name each traced circuit with the designation its own parts carry.

        A traced circuit and an annotated one are two views of the same thing;
        when both are present the tag is what lets them be reconciled, and what
        lets the circuit be followed onto another sheet.
        """

        tag_by_ref = {entry["ref"]: entry["tag"] for entry in symbol_tags}
        net_id_by_label = {net["net_label"]: net["net_id"] for net in nets}

        tags_by_net_id = defaultdict(list)
        for homerun in homeruns:
            net_id = net_id_by_label.get(homerun["net_label"])
            if net_id and homerun.get("circuit_tag"):
                tags_by_net_id[net_id].append(normalize_tag(homerun["circuit_tag"]))

        for circuit in circuits:
            votes = Counter()
            for device in circuit["devices"]:
                tag = tag_by_ref.get(device["ref"])
                if tag:
                    votes[tag] += 1

            # A tag written on the homerun names the whole circuit, so it
            # outweighs the tags of individual devices.
            for net_id in circuit["net_ids"]:
                for tag in tags_by_net_id.get(net_id, []):
                    votes[tag] += 3

            circuit["circuit_tag"] = votes.most_common(1)[0][0] if votes else None

    def _endpoint_direction(
        self, skeleton: np.ndarray, x: int, y: int, reach: int
    ) -> Tuple[float, float]:
        """Unit vector pointing outward along the run that ends at (x, y)."""

        height, width = skeleton.shape
        x1, y1 = max(0, x - reach), max(0, y - reach)
        x2, y2 = min(width, x + reach + 1), min(height, y + reach + 1)

        ys, xs = np.nonzero(skeleton[y1:y2, x1:x2])
        if xs.size < 2:
            return (0.0, 0.0)

        dx = x - (x1 + float(xs.mean()))
        dy = y - (y1 + float(ys.mean()))
        norm = float(np.hypot(dx, dy))
        if norm < 1e-6:
            return (0.0, 0.0)

        return (dx / norm, dy / norm)

    def _panel_in_line(
        self,
        x: int,
        y: int,
        direction: Tuple[float, float],
        panels: List[Tuple[int, str, Tuple[int, int, int, int]]],
        max_angle_deg: float = 30.0,
    ) -> Tuple[Optional[int], Optional[str]]:
        """Nearest panel symbol inside the cone the arrow points into."""

        if direction == (0.0, 0.0) or not panels:
            return None, None

        cos_limit = float(np.cos(np.deg2rad(max_angle_deg)))
        best = (None, None, float("inf"))

        for index, ref, (bx1, by1, bx2, by2) in panels:
            cx, cy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
            dx, dy = cx - x, cy - y
            distance = float(np.hypot(dx, dy))
            if distance < 1e-6:
                continue

            alignment = (dx * direction[0] + dy * direction[1]) / distance
            if alignment >= cos_limit and distance < best[2]:
                best = (index, ref, distance)

        return best[0], best[1]

    # ------------------------------------------------------------------
    # Netlist assembly
    # ------------------------------------------------------------------

    def _build_nets(
        self,
        labels: np.ndarray,
        skeleton: np.ndarray,
        net_ids: Dict[int, str],
        members: List[Dict],
        junctions: List[Dict],
        homeruns: List[Dict],
        scale: float,
    ) -> List[Dict]:
        """One entry per electrically continuous conductor run."""

        by_net: Dict[int, List[Dict]] = defaultdict(list)
        for member in members:
            by_net[member["net_label"]].append(member)

        junctions_per_net: Dict[int, int] = defaultdict(int)
        for junction in junctions:
            junctions_per_net[junction["net_label"]] += 1

        homeruns_per_net: Dict[int, List[Dict]] = defaultdict(list)
        for homerun in homeruns:
            homeruns_per_net[homerun["net_label"]].append(homerun)

        skeleton_labels = np.where(skeleton > 0, labels, 0)
        lengths = np.bincount(skeleton_labels.ravel())

        nets = []
        for label, net_id in net_ids.items():
            attached = by_net.get(label, [])
            net_homeruns = homeruns_per_net.get(label, [])
            length = int(lengths[label]) if label < lengths.size else 0

            nets.append({
                "net_id": net_id,
                "net_label": label,
                "length_px": round(length / scale, 1),
                "junction_count": junctions_per_net.get(label, 0),
                "is_homerun": bool(net_homeruns),
                "panel_refs": sorted({
                    m["ref"] for m in attached if m["is_panel"]
                } | {
                    h["panel_ref"] for h in net_homeruns if h["panel_ref"]
                }),
                "connections": [
                    {
                        "ref": m["ref"],
                        "class_name": m["class_name"],
                        "confidence": m["confidence"],
                        "detection_index": m["detection_index"],
                        "terminal": [
                            int(round(m["terminal"][0] / scale)),
                            int(round(m["terminal"][1] / scale)),
                        ],
                    }
                    for m in sorted(attached, key=lambda m: m["ref"])
                ],
            })

        nets.sort(key=lambda n: int(n["net_id"][1:]))
        return nets

    def _build_vector_nets(
        self,
        graph: Optional[SegmentGraph],
        nets: Dict[int, np.ndarray],
        members: List[Dict],
        junctions: List[Dict],
        homeruns: List[Dict],
    ) -> List[Dict]:
        """One entry per conductor run taken from the drawing's line work."""

        if graph is None:
            return []

        by_net: Dict[int, List[Dict]] = defaultdict(list)
        for member in members:
            by_net[member["net_label"]].append(member)

        junctions_per_net: Dict[int, int] = defaultdict(int)
        for junction in junctions:
            junctions_per_net[junction["net_label"]] += 1

        homeruns_per_net: Dict[int, List[Dict]] = defaultdict(list)
        for homerun in homeruns:
            homeruns_per_net[homerun["net_label"]].append(homerun)

        built = []
        for net_label, indices in nets.items():
            attached = by_net.get(net_label, [])
            net_homeruns = homeruns_per_net.get(net_label, [])

            built.append({
                "net_id": f"N{net_label}",
                "net_label": net_label,
                "length_px": round(float(graph.lengths[indices].sum()), 1),
                "junction_count": junctions_per_net.get(net_label, 0),
                "is_homerun": bool(net_homeruns),
                "panel_refs": sorted(
                    {m["ref"] for m in attached if m["is_panel"]}
                    | {h["panel_ref"] for h in net_homeruns if h["panel_ref"]}
                ),
                "connections": [
                    {
                        "ref": m["ref"],
                        "class_name": m["class_name"],
                        "confidence": m["confidence"],
                        "detection_index": m["detection_index"],
                        "terminal": m["terminal"],
                    }
                    for m in sorted(attached, key=lambda m: m["ref"])
                ],
            })

        built.sort(key=lambda net: net["net_label"])
        return built

    def _build_circuits(
        self, nets: List[Dict], members: List[Dict], homeruns: List[Dict]
    ) -> List[Dict]:
        """
        Merge nets that daisy-chain through the same pass-through device. A
        panel terminates a circuit, so nets are never merged across one.
        """

        union = _UnionFind()
        for net in nets:
            union.find(net["net_id"])

        by_device: Dict[int, List[str]] = defaultdict(list)
        for member in members:
            if not member["is_panel"]:
                by_device[member["detection_index"]].append(member["net_id"])

        for shared in by_device.values():
            for other in shared[1:]:
                union.union(shared[0], other)

        nets_by_id = {net["net_id"]: net for net in nets}
        net_id_by_label = {net["net_label"]: net["net_id"] for net in nets}

        homeruns_by_net: Dict[str, List[Dict]] = defaultdict(list)
        for homerun in homeruns:
            net_id = net_id_by_label.get(homerun["net_label"])
            if net_id:
                homeruns_by_net[net_id].append(homerun)

        grouped: Dict[str, List[str]] = defaultdict(list)
        for net in nets:
            grouped[union.find(net["net_id"])].append(net["net_id"])

        circuits = []
        for number, (_, net_id_group) in enumerate(
            sorted(grouped.items(), key=lambda kv: int(kv[1][0][1:])), start=1
        ):
            devices: Dict[str, Dict] = {}
            panels: set = set()
            circuit_homeruns: List[Dict] = []
            length = 0.0
            junction_count = 0

            for net_id in net_id_group:
                net = nets_by_id[net_id]
                length += net["length_px"]
                junction_count += net["junction_count"]
                panels.update(net["panel_refs"])
                circuit_homeruns.extend(homeruns_by_net.get(net_id, []))
                for connection in net["connections"]:
                    devices[connection["ref"]] = connection

            circuits.append({
                "circuit_id": f"C{number}",
                "net_ids": sorted(net_id_group, key=lambda n: int(n[1:])),
                "device_count": len(devices),
                "devices": [devices[ref] for ref in sorted(devices)],
                "panel_refs": sorted(panels),
                "homerun_count": len(circuit_homeruns),
                "length_px": round(length, 1),
                "junction_count": junction_count,
            })

        return circuits

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _scale_node(self, node: Dict, scale: float) -> Dict:
        return {
            "x": int(round(node["x"] / scale)),
            "y": int(round(node["y"] / scale)),
            "net_id": node["net_id"],
            "degree": node["degree"],
        }

    def _scale_homerun(self, homerun: Dict, scale: float) -> Dict:
        return {
            "x": int(round(homerun["x"] / scale)),
            "y": int(round(homerun["y"] / scale)),
            "direction": homerun["direction"],
            "arrow_strength": homerun.get("arrow_strength"),
            "panel_ref": homerun["panel_ref"],
            "panel_detection_index": homerun["panel_detection_index"],
            "circuit_tag": homerun.get("circuit_tag"),
            "conductor_count": homerun.get("conductor_count"),
        }

    def _save_overlay(
        self,
        gray: np.ndarray,
        labels: np.ndarray,
        net_ids: Dict[int, str],
        junctions: List[Dict],
        homeruns: List[Dict],
        members: List[Dict],
        circuits: List[Dict],
        image_path: Path,
        output_dir: Path,
    ) -> Path:
        """Draw the traced circuits over a faded copy of the sheet."""

        output_dir.mkdir(parents=True, exist_ok=True)
        canvas = cv2.cvtColor(cv2.addWeighted(gray, 0.35, np.full_like(gray, 255), 0.65, 0), cv2.COLOR_GRAY2BGR)

        colour_by_net_id = {}
        for index, circuit in enumerate(circuits):
            colour = _OVERLAY_COLORS[index % len(_OVERLAY_COLORS)]
            for net_id in circuit["net_ids"]:
                colour_by_net_id[net_id] = colour

        for label, net_id in net_ids.items():
            colour = colour_by_net_id.get(net_id, (128, 128, 128))
            canvas[labels == label] = colour

        for junction in junctions:
            cv2.circle(canvas, (junction["x"], junction["y"]), 6, (0, 215, 255), 2)

        for homerun in homeruns:
            dx, dy = homerun["direction"]
            tip = (int(homerun["x"] + dx * 45), int(homerun["y"] + dy * 45))
            cv2.arrowedLine(canvas, (homerun["x"], homerun["y"]), tip, (0, 0, 255), 3, tipLength=0.35)

        for member in members:
            x, y = member["terminal"]
            cv2.circle(canvas, (x, y), 4, (0, 0, 0), -1)
            cv2.putText(canvas, member["ref"], (x + 6, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)

        output_path = output_dir / f"netlist_overlay_{image_path.stem}.png"
        cv2.imwrite(str(output_path), canvas)
        return output_path

    def _save_vector_overlay(
        self,
        gray: np.ndarray,
        scale: float,
        graph: Optional[SegmentGraph],
        nets: Dict[int, np.ndarray],
        junctions: List[Dict],
        homeruns: List[Dict],
        members: List[Dict],
        circuits: List[Dict],
        symbol_tags: List[Dict],
        boxes: List[Tuple[int, int, int, int]],
        image_path: Path,
        output_dir: Path,
    ) -> Path:
        """
        Draw what was found over a faded copy of the sheet.

        On a sheet that annotates its circuits rather than drawing them there
        are no runs to show, so the tag each symbol was given is drawn instead
        - otherwise the overlay for those sheets would be blank and there would
        be nothing to check the result against.
        """

        output_dir.mkdir(parents=True, exist_ok=True)
        canvas = cv2.cvtColor(
            cv2.addWeighted(gray, 0.35, np.full_like(gray, 255), 0.65, 0),
            cv2.COLOR_GRAY2BGR,
        )

        colour_by_net_id = {}
        for index, circuit in enumerate(circuits):
            colour = _OVERLAY_COLORS[index % len(_OVERLAY_COLORS)]
            for net_id in circuit["net_ids"]:
                colour_by_net_id[net_id] = colour

        if graph is not None:
            for net_label, indices in nets.items():
                colour = colour_by_net_id.get(f"N{net_label}", (128, 128, 128))
                points = (graph.segments[indices] * scale).round().astype(np.int32)
                cv2.polylines(canvas, list(points.reshape(-1, 2, 2)), False, colour, 2)

        for junction in junctions:
            centre = (int(junction["x"] * scale), int(junction["y"] * scale))
            cv2.circle(canvas, centre, 6, (0, 215, 255), 2)

        for homerun in homeruns:
            dx, dy = homerun["direction"]
            start = (int(homerun["x"] * scale), int(homerun["y"] * scale))
            tip = (int(start[0] + dx * 45), int(start[1] + dy * 45))
            cv2.arrowedLine(canvas, start, tip, (0, 0, 255), 3, tipLength=0.35)

            label = homerun.get("circuit_tag")
            if label:
                cv2.putText(canvas, label, (start[0] + 8, start[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)

        for member in members:
            x = int(member["terminal"][0] * scale)
            y = int(member["terminal"][1] * scale)
            cv2.circle(canvas, (x, y), 4, (0, 0, 0), -1)
            cv2.putText(canvas, member["ref"], (x + 6, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)

        colour_by_tag = {}
        for entry in symbol_tags:
            index = entry["detection_index"]
            if index >= len(boxes):
                continue

            colour = colour_by_tag.setdefault(
                entry["tag"], _OVERLAY_COLORS[len(colour_by_tag) % len(_OVERLAY_COLORS)]
            )
            x1, y1, x2, y2 = boxes[index]
            cv2.rectangle(canvas, (x1, y1), (x2, y2), colour, 2)
            cv2.putText(canvas, entry["tag"], (x1, max(12, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv2.LINE_AA)

        output_path = output_dir / f"netlist_overlay_{image_path.stem}.png"
        cv2.imwrite(str(output_path), canvas)
        return output_path
