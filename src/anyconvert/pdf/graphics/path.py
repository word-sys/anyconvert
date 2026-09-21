"""Vector path construction, transformation, and SVG path serialization.

Adheres to ISO 32000-1 §8.5 (Path Construction and Painting):
- Segment primitives: MoveTo ('m'), LineTo ('l'), CurveTo ('c', 'v', 'y'), Rectangle ('re'), ClosePath ('h').
- VectorPath: Maintains path segments, transforms points through CTM, computes bounding boxes,
  and synthesizes standard SVG path strings ('M x y L x y C x1 y1 x2 y2 x y Z').
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from anyconvert.common.geometry import BoundingBox, Matrix3x3, Point


@dataclass(frozen=True, slots=True)
class MoveTo:
    """Move current point without drawing ('m')."""

    point: Point


@dataclass(frozen=True, slots=True)
class LineTo:
    """Draw a straight line to target point ('l')."""

    point: Point


@dataclass(frozen=True, slots=True)
class CurveTo:
    """Draw a cubic Bézier curve ('c', 'v', 'y')."""

    p1: Point
    p2: Point
    p3: Point


@dataclass(frozen=True, slots=True)
class Rectangle:
    """Append a complete rectangle subpath ('re')."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class ClosePath:
    """Close the current subpath ('h')."""

    pass


PathSegment = MoveTo | LineTo | CurveTo | Rectangle | ClosePath


class VectorPath:
    """Accumulates path construction operators and converts to device-space SVG."""

    __slots__ = ("_segments", "_current_point", "_subpath_start")

    def __init__(self) -> None:
        self._segments: List[PathSegment] = []
        self._current_point: Point = Point(0.0, 0.0)
        self._subpath_start: Point = Point(0.0, 0.0)

    @property
    def segments(self) -> List[PathSegment]:
        """Return list of path segments."""
        return list(self._segments)

    @property
    def is_empty(self) -> bool:
        """Return True if path contains no segments."""
        return len(self._segments) == 0

    @property
    def current_point(self) -> Point:
        """Return active cursor position."""
        return self._current_point

    def move_to(self, x: float, y: float) -> None:
        """Append MoveTo segment ('m')."""
        pt = Point(x, y)
        self._segments.append(MoveTo(pt))
        self._current_point = pt
        self._subpath_start = pt

    def line_to(self, x: float, y: float) -> None:
        """Append LineTo segment ('l')."""
        pt = Point(x, y)
        self._segments.append(LineTo(pt))
        self._current_point = pt

    def curve_to(self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> None:
        """Append cubic Bézier CurveTo segment ('c')."""
        p1 = Point(x1, y1)
        p2 = Point(x2, y2)
        p3 = Point(x3, y3)
        self._segments.append(CurveTo(p1, p2, p3))
        self._current_point = p3

    def curve_to_v(self, x2: float, y2: float, x3: float, y3: float) -> None:
        """Append CurveTo segment with p1 replicated from current point ('v')."""
        self.curve_to(self._current_point.x, self._current_point.y, x2, y2, x3, y3)

    def curve_to_y(self, x1: float, y1: float, x3: float, y3: float) -> None:
        """Append CurveTo segment with p2 replicated from p3 ('y')."""
        self.curve_to(x1, y1, x3, y3, x3, y3)

    def rectangle(self, x: float, y: float, width: float, height: float) -> None:
        """Append Rectangle subpath ('re')."""
        self._segments.append(Rectangle(x, y, width, height))
        self._current_point = Point(x, y)
        self._subpath_start = Point(x, y)

    def close_path(self) -> None:
        """Append ClosePath segment ('h')."""
        self._segments.append(ClosePath())
        self._current_point = self._subpath_start

    def clear(self) -> None:
        """Reset path accumulator."""
        self._segments.clear()
        self._current_point = Point(0.0, 0.0)
        self._subpath_start = Point(0.0, 0.0)

    def to_svg(self, ctm: Optional[Matrix3x3] = None) -> str:
        """Serialize path into SVG path command string ('d').

        Args:
            ctm: Optional Current Transformation Matrix to transform coordinates into device space.

        Returns:
            str: SVG path string (e.g. 'M 10 20 L 30 40 Z').
        """
        parts: List[str] = []

        def _tr(pt: Point) -> Point:
            return pt.transform(ctm) if ctm is not None else pt

        for seg in self._segments:
            if isinstance(seg, MoveTo):
                p = _tr(seg.point)
                parts.append(f"M {p.x:.2f} {p.y:.2f}")
            elif isinstance(seg, LineTo):
                p = _tr(seg.point)
                parts.append(f"L {p.x:.2f} {p.y:.2f}")
            elif isinstance(seg, CurveTo):
                p1 = _tr(seg.p1)
                p2 = _tr(seg.p2)
                p3 = _tr(seg.p3)
                parts.append(f"C {p1.x:.2f} {p1.y:.2f} {p2.x:.2f} {p2.y:.2f} {p3.x:.2f} {p3.y:.2f}")
            elif isinstance(seg, Rectangle):
                # Expand rectangle into M, L, L, L, Z
                p0 = _tr(Point(seg.x, seg.y))
                p1 = _tr(Point(seg.x + seg.width, seg.y))
                p2 = _tr(Point(seg.x + seg.width, seg.y + seg.height))
                p3 = _tr(Point(seg.x, seg.y + seg.height))
                parts.append(f"M {p0.x:.2f} {p0.y:.2f} L {p1.x:.2f} {p1.y:.2f} L {p2.x:.2f} {p2.y:.2f} L {p3.x:.2f} {p3.y:.2f} Z")
            elif isinstance(seg, ClosePath):
                parts.append("Z")

        return " ".join(parts)

    def compute_bbox(self, ctm: Optional[Matrix3x3] = None) -> Optional[BoundingBox]:
        """Compute axis-aligned bounding box encompassing all points in the path.

        Args:
            ctm: Optional transformation matrix to apply before computing bounds.

        Returns:
            Optional[BoundingBox]: Enclosing bounding box, or None if path is empty.
        """
        if not self._segments:
            return None

        points: List[Point] = []

        def _tr(pt: Point) -> Point:
            return pt.transform(ctm) if ctm is not None else pt

        for seg in self._segments:
            if isinstance(seg, MoveTo):
                points.append(_tr(seg.point))
            elif isinstance(seg, LineTo):
                points.append(_tr(seg.point))
            elif isinstance(seg, CurveTo):
                points.append(_tr(seg.p1))
                points.append(_tr(seg.p2))
                points.append(_tr(seg.p3))
            elif isinstance(seg, Rectangle):
                points.append(_tr(Point(seg.x, seg.y)))
                points.append(_tr(Point(seg.x + seg.width, seg.y + seg.height)))

        if not points:
            return None

        min_x = min(p.x for p in points)
        min_y = min(p.y for p in points)
        max_x = max(p.x for p in points)
        max_y = max(p.y for p in points)

        return BoundingBox(x0=min_x, y0=min_y, x1=max_x, y1=max_y)
