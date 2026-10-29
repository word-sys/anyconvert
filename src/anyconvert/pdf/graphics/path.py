"""Vector path construction, transformation, and SVG path serialization.

Adheres to ISO 32000-1 §8.5 (Path Construction and Painting):
- Segment primitives: MoveTo ('m'), LineTo ('l'), CurveTo ('c', 'v', 'y'), Rectangle ('re'), ClosePath ('h').
- SubPath: Contiguous sequence of path segments starting with MoveTo or Rectangle.
- VectorPath: Maintains path segments, transforms points through CTM, computes bounding boxes,
  decomposes subpaths, flattens Bézier curves, and synthesizes standard SVG path strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import List, Optional, Tuple

from anyconvert.common.geometry import BoundingBox, Matrix3x3, Point


@dataclass(frozen=True, slots=True)
class MoveTo:
    """Move current point without drawing ('m')."""

    point: Point

    def transform(self, ctm: Matrix3x3) -> MoveTo:
        """Apply transformation matrix to point."""
        return MoveTo(self.point.transform(ctm))


@dataclass(frozen=True, slots=True)
class LineTo:
    """Draw a straight line to target point ('l')."""

    point: Point

    def transform(self, ctm: Matrix3x3) -> LineTo:
        """Apply transformation matrix to point."""
        return LineTo(self.point.transform(ctm))


@dataclass(frozen=True, slots=True)
class CurveTo:
    """Draw a cubic Bézier curve ('c', 'v', 'y')."""

    p1: Point
    p2: Point
    p3: Point

    def transform(self, ctm: Matrix3x3) -> CurveTo:
        """Apply transformation matrix to all curve control points."""
        return CurveTo(
            self.p1.transform(ctm),
            self.p2.transform(ctm),
            self.p3.transform(ctm),
        )

    def eval(self, t: float, p0: Point) -> Point:
        """Evaluate point on cubic Bézier at parameter t in [0.0, 1.0]."""
        mt = 1.0 - t
        mt2 = mt * mt
        mt3 = mt2 * mt
        t2 = t * t
        t3 = t2 * t
        x = mt3 * p0.x + 3.0 * mt2 * t * self.p1.x + 3.0 * mt * t2 * self.p2.x + t3 * self.p3.x
        y = mt3 * p0.y + 3.0 * mt2 * t * self.p1.y + 3.0 * mt * t2 * self.p2.y + t3 * self.p3.y
        return Point(x, y)

    def split(self, t: float, p0: Point) -> Tuple[CurveTo, CurveTo]:
        """De Casteljau subdivision at parameter t in [0.0, 1.0]."""
        p01 = Point((1.0 - t) * p0.x + t * self.p1.x, (1.0 - t) * p0.y + t * self.p1.y)
        p12 = Point((1.0 - t) * self.p1.x + t * self.p2.x, (1.0 - t) * self.p1.y + t * self.p2.y)
        p23 = Point((1.0 - t) * self.p2.x + t * self.p3.x, (1.0 - t) * self.p2.y + t * self.p3.y)
        p012 = Point((1.0 - t) * p01.x + t * p12.x, (1.0 - t) * p01.y + t * p12.y)
        p123 = Point((1.0 - t) * p12.x + t * p23.x, (1.0 - t) * p12.y + t * p23.y)
        p0123 = Point((1.0 - t) * p012.x + t * p123.x, (1.0 - t) * p012.y + t * p123.y)
        return (
            CurveTo(p1=p01, p2=p012, p3=p0123),
            CurveTo(p1=p123, p2=p23, p3=self.p3),
        )

    def extrema_t(self, p0: Point) -> List[float]:
        """Compute parameter t values in (0.0, 1.0) where curve derivative is zero."""
        t_values: List[float] = []

        def _solve_dim(c0: float, c1: float, c2: float, c3: float) -> None:
            a = -c0 + 3.0 * c1 - 3.0 * c2 + c3
            b = 2.0 * (c0 - 2.0 * c1 + c2)
            c = -c0 + c1
            if abs(a) < 1e-12:
                if abs(b) > 1e-12:
                    t = -c / b
                    if 0.0 < t < 1.0:
                        t_values.append(t)
            else:
                disc = b * b - 4.0 * a * c
                if disc >= 0.0:
                    sq = math.sqrt(disc)
                    t1 = (-b - sq) / (2.0 * a)
                    t2 = (-b + sq) / (2.0 * a)
                    if 0.0 < t1 < 1.0:
                        t_values.append(t1)
                    if 0.0 < t2 < 1.0:
                        t_values.append(t2)

        _solve_dim(p0.x, self.p1.x, self.p2.x, self.p3.x)
        _solve_dim(p0.y, self.p1.y, self.p2.y, self.p3.y)
        return sorted(set(t_values))

    def extrema_points(self, p0: Point) -> List[Point]:
        """Return points along the curve corresponding to local extrema."""
        return [self.eval(t, p0) for t in self.extrema_t(p0)]

    def to_polyline(self, p0: Point, tolerance: float = 0.5, max_depth: int = 8) -> List[Point]:
        """Subdivide cubic Bézier curve into piecewise linear points within tolerance."""
        def _flatten(curve: CurveTo, start: Point, depth: int) -> List[Point]:
            vx = curve.p3.x - start.x
            vy = curve.p3.y - start.y
            length = math.hypot(vx, vy)
            if length < 1e-6:
                d1 = math.hypot(curve.p1.x - start.x, curve.p1.y - start.y)
                d2 = math.hypot(curve.p2.x - start.x, curve.p2.y - start.y)
            else:
                d1 = abs(vy * (curve.p1.x - start.x) - vx * (curve.p1.y - start.y)) / length
                d2 = abs(vy * (curve.p2.x - start.x) - vx * (curve.p2.y - start.y)) / length
            if max(d1, d2) <= tolerance or depth >= max_depth:
                return [curve.p3]
            left, right = curve.split(0.5, start)
            pts = _flatten(left, start, depth + 1)
            pts.extend(_flatten(right, left.p3, depth + 1))
            return pts

        return _flatten(self, p0, 0)


@dataclass(frozen=True, slots=True)
class Rectangle:
    """Append a complete rectangle subpath ('re')."""

    x: float
    y: float
    width: float
    height: float

    def corners(self) -> List[Point]:
        """Return the four corner vertices of the rectangle."""
        return [
            Point(self.x, self.y),
            Point(self.x + self.width, self.y),
            Point(self.x + self.width, self.y + self.height),
            Point(self.x, self.y + self.height),
        ]

    def to_segments(self) -> List[PathSegment]:
        """Expand rectangle into MoveTo, LineTo, and ClosePath primitives."""
        c = self.corners()
        return [
            MoveTo(c[0]),
            LineTo(c[1]),
            LineTo(c[2]),
            LineTo(c[3]),
            ClosePath(),
        ]


@dataclass(frozen=True, slots=True)
class ClosePath:
    """Close the current subpath ('h')."""

    def transform(self, ctm: Matrix3x3) -> ClosePath:
        """Return ClosePath unchanged."""
        return ClosePath()


PathSegment = MoveTo | LineTo | CurveTo | Rectangle | ClosePath


@dataclass
class SubPath:
    """A contiguous sequence of path segments starting with MoveTo or Rectangle."""

    segments: List[PathSegment] = field(default_factory=list)
    is_closed: bool = False

    @property
    def start_point(self) -> Optional[Point]:
        """Return the subpath starting coordinate."""
        if not self.segments:
            return None
        first = self.segments[0]
        if isinstance(first, MoveTo):
            return first.point
        if isinstance(first, Rectangle):
            return Point(first.x, first.y)
        return None

    @property
    def current_point(self) -> Optional[Point]:
        """Return the active terminal point of the subpath."""
        if not self.segments:
            return None
        last = self.segments[-1]
        if isinstance(last, MoveTo):
            return last.point
        if isinstance(last, LineTo):
            return last.point
        if isinstance(last, CurveTo):
            return last.p3
        if isinstance(last, (Rectangle, ClosePath)):
            return self.start_point
        return None

    def to_svg(self, ctm: Optional[Matrix3x3] = None) -> str:
        """Serialize subpath into SVG path string."""
        path = VectorPath()
        for seg in self.segments:
            path._segments.append(seg)
        return path.to_svg(ctm)

    def compute_bbox(self, ctm: Optional[Matrix3x3] = None) -> Optional[BoundingBox]:
        """Compute axis-aligned bounding box for this subpath."""
        path = VectorPath()
        for seg in self.segments:
            path._segments.append(seg)
        return path.compute_bbox(ctm)

    def to_polyline(self, tolerance: float = 0.5) -> List[Point]:
        """Flatten subpath segments into connected polyline points."""
        points: List[Point] = []
        curr = Point(0.0, 0.0)
        start = Point(0.0, 0.0)

        for seg in self.segments:
            if isinstance(seg, MoveTo):
                curr = seg.point
                start = curr
                points.append(curr)
            elif isinstance(seg, LineTo):
                curr = seg.point
                points.append(curr)
            elif isinstance(seg, CurveTo):
                pts = seg.to_polyline(curr, tolerance=tolerance)
                points.extend(pts)
                curr = seg.p3
            elif isinstance(seg, Rectangle):
                c = seg.corners()
                points.extend([c[0], c[1], c[2], c[3], c[0]])
                curr = c[0]
                start = c[0]
            elif isinstance(seg, ClosePath):
                if points and points[-1] != start:
                    points.append(start)
                curr = start

        return points


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

    def decompose_subpaths(self) -> List[SubPath]:
        """Decompose path into individual constituent subpaths."""
        subpaths: List[SubPath] = []
        current_subpath: Optional[SubPath] = None

        for seg in self._segments:
            if isinstance(seg, Rectangle):
                if current_subpath is not None and current_subpath.segments:
                    subpaths.append(current_subpath)
                    current_subpath = None
                rect_sp = SubPath(segments=[seg], is_closed=True)
                subpaths.append(rect_sp)
            elif isinstance(seg, MoveTo):
                if current_subpath is not None and current_subpath.segments:
                    subpaths.append(current_subpath)
                current_subpath = SubPath(segments=[seg], is_closed=False)
            else:
                if current_subpath is None:
                    current_subpath = SubPath(segments=[MoveTo(Point(0.0, 0.0))], is_closed=False)
                current_subpath.segments.append(seg)
                if isinstance(seg, ClosePath):
                    current_subpath.is_closed = True

        if current_subpath is not None and current_subpath.segments:
            subpaths.append(current_subpath)

        return subpaths

    @property
    def subpaths(self) -> List[SubPath]:
        """Return decomposed list of subpaths."""
        return self.decompose_subpaths()

    def to_polylines(self, tolerance: float = 0.5) -> List[List[Point]]:
        """Flatten all subpaths into polylines within specified chord tolerance."""
        return [sp.to_polyline(tolerance=tolerance) for sp in self.decompose_subpaths()]

    def transform(self, ctm: Matrix3x3) -> VectorPath:
        """Return a new VectorPath with all coordinates transformed through ctm."""
        new_path = VectorPath()
        for seg in self._segments:
            if isinstance(seg, MoveTo):
                new_path._segments.append(seg.transform(ctm))
            elif isinstance(seg, LineTo):
                new_path._segments.append(seg.transform(ctm))
            elif isinstance(seg, CurveTo):
                new_path._segments.append(seg.transform(ctm))
            elif isinstance(seg, Rectangle):
                # When transformed through arbitrary CTM, rectangle becomes a polygon subpath
                new_path._segments.extend(
                    [
                        s.transform(ctm) if hasattr(s, "transform") else s
                        for s in seg.to_segments()
                    ]
                )
            elif isinstance(seg, ClosePath):
                new_path._segments.append(ClosePath())
        new_path._current_point = self._current_point.transform(ctm)
        new_path._subpath_start = self._subpath_start.transform(ctm)
        return new_path

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
                c = seg.corners()
                p0 = _tr(c[0])
                p1 = _tr(c[1])
                p2 = _tr(c[2])
                p3 = _tr(c[3])
                parts.append(f"M {p0.x:.2f} {p0.y:.2f} L {p1.x:.2f} {p1.y:.2f} L {p2.x:.2f} {p2.y:.2f} L {p3.x:.2f} {p3.y:.2f} Z")
            elif isinstance(seg, ClosePath):
                parts.append("Z")

        return " ".join(parts)

    def compute_bbox(
        self,
        ctm: Optional[Matrix3x3] = None,
        stroke_width: float = 0.0,
    ) -> Optional[BoundingBox]:
        """Compute axis-aligned bounding box encompassing all points in the path.

        Args:
            ctm: Optional transformation matrix to apply before computing bounds.
            stroke_width: Optional stroke width to expand bounding box bounds.

        Returns:
            Optional[BoundingBox]: Enclosing bounding box, or None if path is empty.
        """
        if not self._segments:
            return None

        points: List[Point] = []

        def _tr(pt: Point) -> Point:
            return pt.transform(ctm) if ctm is not None else pt

        curr: Point = Point(0.0, 0.0)
        subpath_start: Point = Point(0.0, 0.0)

        for seg in self._segments:
            if isinstance(seg, MoveTo):
                points.append(_tr(seg.point))
                curr = seg.point
                subpath_start = seg.point
            elif isinstance(seg, LineTo):
                points.append(_tr(curr))
                points.append(_tr(seg.point))
                curr = seg.point
            elif isinstance(seg, CurveTo):
                points.append(_tr(curr))
                points.append(_tr(seg.p1))
                points.append(_tr(seg.p2))
                points.append(_tr(seg.p3))
                for ep in seg.extrema_points(curr):
                    points.append(_tr(ep))
                curr = seg.p3
            elif isinstance(seg, Rectangle):
                for corner in seg.corners():
                    points.append(_tr(corner))
                curr = Point(seg.x, seg.y)
                subpath_start = curr
            elif isinstance(seg, ClosePath):
                curr = subpath_start

        if not points:
            return None

        min_x = min(p.x for p in points)
        min_y = min(p.y for p in points)
        max_x = max(p.x for p in points)
        max_y = max(p.y for p in points)

        if stroke_width > 0.0:
            half_w = stroke_width / 2.0
            return BoundingBox(
                x0=min_x - half_w,
                y0=min_y - half_w,
                x1=max_x + half_w,
                y1=max_y + half_w,
            )

        return BoundingBox(x0=min_x, y0=min_y, x1=max_x, y1=max_y)
