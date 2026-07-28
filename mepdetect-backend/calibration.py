"""
Scale Calibration
Converts pixel measurements on a rendered sheet into real-world distances.

Detections and traced conductors live in the pixel space of the page rendered
at the job's DPI. Two reference points a known distance apart - a graphic
scale bar, a dimensioned grid line - fix the plot scale, and every pixel
length after that is a real length. One calibration applies to the whole job:
sheets in a plan set are plotted at the same scale and rendered at the same
DPI, which is the case the API exposes.
"""

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True)
class Calibration:
    """Real units per rendered-image pixel."""

    units_per_pixel: float
    units: str = "feet"

    @classmethod
    def from_reference(
        cls,
        point_a: Sequence[float],
        point_b: Sequence[float],
        real_distance: float,
        units: str = "feet",
    ) -> "Calibration":
        """
        Calibrate from two points a known real distance apart.

        Args:
            point_a: First reference point, in rendered-image pixels.
            point_b: Second reference point, in rendered-image pixels.
            real_distance: Real distance between them, in `units`.
            units: Unit name the distance is stated in.

        Returns:
            Calibration mapping that sheet's pixels to real units.
        """

        pixel_distance = math.hypot(
            point_b[0] - point_a[0], point_b[1] - point_a[1]
        )
        if pixel_distance <= 0:
            raise ValueError("Reference points must be distinct")
        if real_distance <= 0:
            raise ValueError("Reference distance must be positive")

        return cls(units_per_pixel=real_distance / pixel_distance, units=units)

    def length(self, pixels: float) -> float:
        """A pixel length in real units."""
        return pixels * self.units_per_pixel

    def to_dict(self) -> dict:
        return {
            "units": self.units,
            "units_per_pixel": self.units_per_pixel,
        }


def parse_reference(
    ref_points: Optional[str],
    real_distance: Optional[float],
    units: str = "feet",
) -> Optional[Calibration]:
    """
    Calibration from the API's form fields, or None when not requested.

    `ref_points` is "x1,y1,x2,y2" in rendered-image pixels. Asking for one
    half of the calibration without the other is a caller mistake and raises,
    rather than silently returning uncalibrated results.
    """

    if not ref_points and real_distance is None:
        return None
    if not ref_points or real_distance is None:
        raise ValueError("Calibration needs both ref_points and real_distance")

    try:
        values = [float(v) for v in ref_points.split(",")]
    except ValueError:
        raise ValueError(f"ref_points must be 'x1,y1,x2,y2', got: {ref_points}")
    if len(values) != 4:
        raise ValueError(f"ref_points must be 'x1,y1,x2,y2', got: {ref_points}")

    return Calibration.from_reference(
        (values[0], values[1]), (values[2], values[3]), real_distance, units
    )
