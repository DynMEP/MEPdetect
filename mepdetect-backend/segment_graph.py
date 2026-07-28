"""
Segment Graph
Connectivity of vector line work, without rasterizing it.

Rasterizing a drawing to trace it throws away exactly what matters: at any
working resolution small enough to process, an arrowhead and the run it
terminates stop touching, and taps disappear. Working on the segments directly
keeps the connectivity the CAD file already states, at full precision and
independent of resolution.

Two segments are on the same net when they share an endpoint, or when one ends
on the other's interior (a tap). Both tests use the same tolerance, expressed
in the drawing's own pixel space.
"""

from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


class UnionFind:
    """Union-find over integer ids."""

    def __init__(self, size: int):
        self._parent = np.arange(size, dtype=np.int64)

    def find(self, item: int) -> int:
        parent = self._parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return int(item)

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_b] = root_a

    def groups(self) -> Dict[int, List[int]]:
        grouped: Dict[int, List[int]] = defaultdict(list)
        for item in range(len(self._parent)):
            grouped[self.find(item)].append(item)
        return grouped


class SegmentGraph:
    """Nets, junction nodes and lookups over a set of line segments."""

    def __init__(
        self,
        segments: np.ndarray,
        tolerance: float,
        cell_size: Optional[float] = None,
        join_taps: bool = True,
    ):
        """
        Args:
            segments: (N, 4) array of x1, y1, x2, y2.
            tolerance: How close two pieces of line work must be to count as
                connected, in the same units as the segments.
            cell_size: Spatial index cell. Defaults to 20x the tolerance.
            join_taps: Also join runs that end on another run's interior. Costs
                a spatial query per endpoint, so it is skipped while comparing
                candidate pens and switched on for the chosen one.
        """

        self.segments = np.asarray(segments, np.float64).reshape(-1, 4)
        self.tolerance = float(tolerance)
        self.cell_size = float(cell_size or max(tolerance * 20.0, 1.0))

        self.starts = self.segments[:, :2]
        self.ends = self.segments[:, 2:]
        self.lengths = np.hypot(*(self.ends - self.starts).T)

        self._index = self._build_index()
        self._union = UnionFind(len(self.segments))
        self._junction_points: List[Tuple[float, float, int]] = []

        self._join_shared_endpoints()
        if join_taps:
            self._join_taps()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_index(self) -> Dict[Tuple[int, int], List[int]]:
        """Bucket segments into a uniform grid by the cells they cross."""

        index: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        if not len(self.segments):
            return index

        lows = np.minimum(self.starts, self.ends)
        highs = np.maximum(self.starts, self.ends)
        cell_lows = np.floor(lows / self.cell_size).astype(np.int64)
        cell_highs = np.floor(highs / self.cell_size).astype(np.int64)

        for i in range(len(self.segments)):
            for cx in range(cell_lows[i, 0], cell_highs[i, 0] + 1):
                for cy in range(cell_lows[i, 1], cell_highs[i, 1] + 1):
                    index[(cx, cy)].append(i)

        return index

    def _join_shared_endpoints(self) -> None:
        """
        Segments meeting at a point are one net; three or more meeting there
        is a junction node.
        """

        if not len(self.segments):
            return

        points = np.vstack([self.starts, self.ends])
        keys = np.round(points / max(self.tolerance, 1e-9)).astype(np.int64)

        at_point: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        for position, key in enumerate(map(tuple, keys)):
            at_point[key].append(position % len(self.segments))

        for key, members in at_point.items():
            unique = set(members)
            first = members[0]
            for other in members[1:]:
                self._union.union(first, other)

            if len(unique) >= 3:
                self._junction_points.append((
                    float(key[0] * self.tolerance),
                    float(key[1] * self.tolerance),
                    len(unique),
                ))

    def _join_taps(self) -> None:
        """Join a run that ends on another run's interior: a tap or a splice."""

        if not len(self.segments):
            return

        points = np.vstack([self.starts, self.ends])
        owners = np.concatenate([np.arange(len(self.segments))] * 2)

        for position in range(len(points)):
            point = points[position]
            owner = int(owners[position])

            candidates = self._nearby(point)
            if not candidates:
                continue

            candidates = np.array([c for c in candidates if c != owner], np.int64)
            if not len(candidates):
                continue

            distances = _point_segment_distance(
                point, self.segments[candidates, :2], self.segments[candidates, 2:]
            )
            touching = candidates[distances <= self.tolerance]

            for other in touching:
                other = int(other)
                if self._union.find(other) != self._union.find(owner):
                    self._union.union(owner, other)
                    self._junction_points.append((float(point[0]), float(point[1]), 3))

    def _nearby(self, point: Sequence[float]) -> List[int]:
        """Segment ids in the cells around a point."""

        cx = int(np.floor(point[0] / self.cell_size))
        cy = int(np.floor(point[1] / self.cell_size))

        found: List[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                found.extend(self._index.get((cx + dx, cy + dy), ()))

        return found

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def join_across_gap(self, centre: Sequence[float], radius: float, reach: float) -> bool:
        """
        Join a small detached mark to the run it belongs to.

        Drafting standards place a homerun arrowhead a short gap off the end of
        its run - it is a separate block, not part of the polyline. The gap is
        deliberate and consistent, so it is bridged explicitly here rather than
        by loosening the tolerance everywhere, which would fuse runs that
        merely pass close to each other.

        Args:
            centre: Middle of the detached mark.
            radius: How far the mark itself extends from that centre.
            reach: Largest gap to bridge.

        Returns:
            Whether a join was made.
        """

        centre = np.asarray(centre, np.float64)
        candidates = set(self._nearby(centre))
        for offset in (-reach, reach):
            candidates.update(self._nearby(centre + offset))
        if not candidates:
            return False

        candidates = np.array(sorted(candidates), np.int64)
        starts, ends = self.segments[candidates, :2], self.segments[candidates, 2:]

        own = (
            (np.hypot(*(starts - centre).T) <= radius)
            & (np.hypot(*(ends - centre).T) <= radius)
        )
        if not own.any() or own.all():
            return False

        others = candidates[~own]
        distances = _point_segment_distance(
            centre, self.segments[others, :2], self.segments[others, 2:]
        )

        closest = int(np.argmin(distances))
        if distances[closest] - radius > reach:
            return False

        self._union.union(int(candidates[own][0]), int(others[closest]))
        return True

    def nets(self, min_length: float = 0.0) -> Dict[int, np.ndarray]:
        """
        Connected runs, keyed by net id, as arrays of segment indices.

        Args:
            min_length: Drop runs shorter than this in total, which are stray
                ticks and leader stubs rather than conductors.
        """

        nets = {}
        for members in self._union.groups().values():
            indices = np.array(members, np.int64)
            if float(self.lengths[indices].sum()) >= min_length:
                nets[len(nets) + 1] = indices

        return nets

    def junctions(self, net_of_segment: Dict[int, int]) -> List[Dict]:
        """Junction nodes that survived on a kept net, de-duplicated."""

        seen = {}
        for x, y, degree in self._junction_points:
            net_id = self._net_at_point(np.array([x, y]), net_of_segment)
            if net_id is None:
                continue

            key = (round(x / max(self.tolerance * 4, 1e-9)),
                   round(y / max(self.tolerance * 4, 1e-9)))
            current = seen.get(key)
            if current is None or degree > current["degree"]:
                seen[key] = {
                    "x": int(round(x)),
                    "y": int(round(y)),
                    "degree": int(degree),
                    "net_label": net_id,
                }

        return list(seen.values())

    def net_at_point(
        self, point: Sequence[float], net_of_segment: Dict[int, int], reach: float
    ) -> Optional[int]:
        """The net whose line work passes closest to a point, within reach."""

        return self._net_at_point(np.asarray(point, np.float64), net_of_segment, reach)

    def _net_at_point(
        self,
        point: np.ndarray,
        net_of_segment: Dict[int, int],
        reach: Optional[float] = None,
    ) -> Optional[int]:
        reach = self.tolerance * 2 if reach is None else reach

        candidates = [c for c in self._nearby(point) if c in net_of_segment]
        if not candidates:
            return None

        candidates = np.array(candidates, np.int64)
        distances = _point_segment_distance(
            point, self.segments[candidates, :2], self.segments[candidates, 2:]
        )
        closest = int(np.argmin(distances))

        if distances[closest] > reach:
            return None

        return net_of_segment[int(candidates[closest])]

    def nets_in_box(
        self,
        box: Sequence[float],
        margin: float,
        net_of_segment: Dict[int, int],
    ) -> Dict[int, Tuple[float, float]]:
        """
        Nets whose line work enters a symbol's box, with where they enter.

        Args:
            box: x1, y1, x2, y2 of the symbol.
            margin: How far outside the box a run still counts as landing on it.
            net_of_segment: Segment id to net id, for the kept nets.

        Returns:
            {net id: (x, y)} of the closest approach to the box centre.
        """

        x1, y1, x2, y2 = box
        low = np.array([x1 - margin, y1 - margin], np.float64)
        high = np.array([x2 + margin, y2 + margin], np.float64)
        centre = np.array([(x1 + x2) / 2, (y1 + y2) / 2], np.float64)

        cell_low = np.floor(low / self.cell_size).astype(np.int64)
        cell_high = np.floor(high / self.cell_size).astype(np.int64)

        candidates = set()
        for cx in range(cell_low[0], cell_high[0] + 1):
            for cy in range(cell_low[1], cell_high[1] + 1):
                candidates.update(self._index.get((cx, cy), ()))

        found: Dict[int, Tuple[float, float]] = {}
        best: Dict[int, float] = {}

        for index in candidates:
            net_id = net_of_segment.get(index)
            if net_id is None:
                continue

            start, end = self.segments[index, :2], self.segments[index, 2:]
            if not _segment_hits_box(start, end, low, high):
                continue

            point = _closest_point_on_segment(centre, start, end)
            distance = float(np.hypot(*(point - centre)))
            if net_id not in best or distance < best[net_id]:
                best[net_id] = distance
                found[net_id] = (float(point[0]), float(point[1]))

        return found


# ----------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------

def _point_segment_distance(
    point: np.ndarray, starts: np.ndarray, ends: np.ndarray
) -> np.ndarray:
    """Distance from one point to each of many segments."""

    vectors = ends - starts
    lengths_sq = np.einsum("ij,ij->i", vectors, vectors)
    lengths_sq = np.where(lengths_sq < 1e-12, 1e-12, lengths_sq)

    t = np.clip(np.einsum("ij,ij->i", point - starts, vectors) / lengths_sq, 0.0, 1.0)
    projections = starts + t[:, None] * vectors

    return np.hypot(*(point - projections).T)


def _closest_point_on_segment(
    point: np.ndarray, start: np.ndarray, end: np.ndarray
) -> np.ndarray:
    """The point on a segment nearest to a given point."""

    vector = end - start
    length_sq = float(vector @ vector)
    if length_sq < 1e-12:
        return start

    t = float(np.clip((point - start) @ vector / length_sq, 0.0, 1.0))
    return start + t * vector


def _segment_hits_box(
    start: np.ndarray, end: np.ndarray, low: np.ndarray, high: np.ndarray
) -> bool:
    """Whether a segment touches an axis-aligned box (slab test)."""

    direction = end - start
    t_enter, t_exit = 0.0, 1.0

    for axis in (0, 1):
        if abs(direction[axis]) < 1e-12:
            if start[axis] < low[axis] or start[axis] > high[axis]:
                return False
            continue

        t1 = (low[axis] - start[axis]) / direction[axis]
        t2 = (high[axis] - start[axis]) / direction[axis]
        if t1 > t2:
            t1, t2 = t2, t1

        t_enter = max(t_enter, t1)
        t_exit = min(t_exit, t2)
        if t_enter > t_exit:
            return False

    return True
