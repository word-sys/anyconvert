"""Fundamental geometry, coordinate transformations, and affine matrix mathematics.

Provides mathematically rigorous, immutable primitives:
- Point: 2D coordinate pair (x, y)
- Size: 2D dimension pair (width, height)
- BoundingBox: Axis-aligned bounding box (x0, y0, x1, y1) with collision, union, and intersection
- Matrix3x3: Full 3x3 homogeneous transformation matrix with affine multiplication,
  inversion, determinant, rotation, translation, scaling, and point/bbox transformations.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Point:
    """Immutable 2D coordinate point (x, y)."""

    x: float
    y: float

    def __add__(self, other: Point) -> Point:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Point:
        return Point(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Point:
        return self.__mul__(scalar)

    def distance_to(self, other: Point) -> float:
        """Compute Euclidean distance to another Point."""
        return math.hypot(self.x - other.x, self.y - other.y)

    def as_tuple(self) -> Tuple[float, float]:
        """Return (x, y) tuple."""
        return (self.x, self.y)


@dataclass(frozen=True)
class Size:
    """Immutable 2D dimension pair (width, height)."""

    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width < 0.0 or self.height < 0.0:
            object.__setattr__(self, "width", max(0.0, self.width))
            object.__setattr__(self, "height", max(0.0, self.height))

    @property
    def area(self) -> float:
        """Area of the dimension."""
        return self.width * self.height

    @property
    def is_empty(self) -> bool:
        """Check if width or height is negligible."""
        return self.width <= 1e-6 or self.height <= 1e-6


@dataclass(frozen=True)
class BoundingBox:
    """Immutable 2D Axis-Aligned Bounding Box (AABB).

    Attributes:
        x0: Minimum X coordinate (left).
        y0: Minimum Y coordinate (top in presentation space, bottom in PDF space).
        x1: Maximum X coordinate (right).
        y1: Maximum Y coordinate (bottom in presentation space, top in PDF space).
    """

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        # Normalize bounds so x0 <= x1 and y0 <= y1
        min_x, max_x = (self.x0, self.x1) if self.x0 <= self.x1 else (self.x1, self.x0)
        min_y, max_y = (self.y0, self.y1) if self.y0 <= self.y1 else (self.y1, self.y0)
        if min_x != self.x0 or max_x != self.x1:
            object.__setattr__(self, "x0", min_x)
            object.__setattr__(self, "x1", max_x)
        if min_y != self.y0 or max_y != self.y1:
            object.__setattr__(self, "y0", min_y)
            object.__setattr__(self, "y1", max_y)

    @classmethod
    def from_points(cls, points: Sequence[Point]) -> BoundingBox:
        """Construct bounding box enclosing all given points."""
        if not points:
            return cls(0.0, 0.0, 0.0, 0.0)
        min_x = min(p.x for p in points)
        max_x = max(p.x for p in points)
        min_y = min(p.y for p in points)
        max_y = max(p.y for p in points)
        return cls(min_x, min_y, max_x, max_y)

    @classmethod
    def from_origin_size(cls, x: float, y: float, width: float, height: float) -> BoundingBox:
        """Construct bounding box from origin (x, y) and dimensions."""
        return cls(x, y, x + width, y + height)

    @property
    def width(self) -> float:
        """Width of the bounding box."""
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        """Height of the bounding box."""
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        """Area enclosed by the bounding box."""
        return self.width * self.height

    @property
    def center(self) -> Point:
        """Center coordinate of the bounding box."""
        return Point((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def is_empty(self) -> bool:
        """Check whether the bounding box has zero or negligible area."""
        return self.width <= 1e-6 or self.height <= 1e-6

    @property
    def corners(self) -> List[Point]:
        """Return the four corner points: (top-left, top-right, bottom-right, bottom-left)."""
        return [
            Point(self.x0, self.y0),
            Point(self.x1, self.y0),
            Point(self.x1, self.y1),
            Point(self.x0, self.y1),
        ]

    def contains_point(self, pt: Point, tolerance: float = 1e-6) -> bool:
        """Test if a Point lies inside or on the boundary of this box."""
        return (
            (self.x0 - tolerance) <= pt.x <= (self.x1 + tolerance)
            and (self.y0 - tolerance) <= pt.y <= (self.y1 + tolerance)
        )

    def contains_box(self, other: BoundingBox, tolerance: float = 1e-6) -> bool:
        """Test if another BoundingBox is completely inside this box."""
        return (
            (self.x0 - tolerance) <= other.x0
            and (other.x1 - tolerance) <= self.x1
            and (self.y0 - tolerance) <= other.y0
            and (other.y1 - tolerance) <= self.y1
        )

    def intersects(self, other: BoundingBox, tolerance: float = 1e-6) -> bool:
        """Test if this bounding box overlaps with another bounding box."""
        if self.x1 < other.x0 - tolerance or other.x1 < self.x0 - tolerance:
            return False
        if self.y1 < other.y0 - tolerance or other.y1 < self.y0 - tolerance:
            return False
        return True

    def intersection(self, other: BoundingBox) -> Optional[BoundingBox]:
        """Compute the intersecting rectangle, or None if no overlap exists."""
        ix0 = max(self.x0, other.x0)
        iy0 = max(self.y0, other.y0)
        ix1 = min(self.x1, other.x1)
        iy1 = min(self.y1, other.y1)

        if ix0 <= ix1 and iy0 <= iy1:
            return BoundingBox(ix0, iy0, ix1, iy1)
        return None

    def union(self, other: BoundingBox) -> BoundingBox:
        """Compute the minimum bounding box enclosing both boxes."""
        return BoundingBox(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def iou(self, other: BoundingBox) -> float:
        """Compute Intersection-over-Union (Jaccard index) in range [0.0, 1.0]."""
        inter = self.intersection(other)
        if inter is None or inter.is_empty:
            return 0.0
        inter_area = inter.area
        total_area = self.area + other.area - inter_area
        if total_area <= 1e-9:
            return 1.0
        return inter_area / total_area

    def horizontal_overlap(self, other: BoundingBox) -> float:
        """Calculate the horizontal overlap distance between two bounding boxes."""
        overlap = min(self.x1, other.x1) - max(self.x0, other.x0)
        return max(0.0, overlap)

    def vertical_overlap(self, other: BoundingBox) -> float:
        """Calculate the vertical overlap distance between two bounding boxes."""
        overlap = min(self.y1, other.y1) - max(self.y0, other.y0)
        return max(0.0, overlap)

    def translate(self, dx: float, dy: float) -> BoundingBox:
        """Translate bounding box by (dx, dy)."""
        return BoundingBox(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def scale(self, sx: float, sy: float) -> BoundingBox:
        """Scale bounding box relative to origin."""
        return BoundingBox(self.x0 * sx, self.y0 * sy, self.x1 * sx, self.y1 * sy)

    def expand(self, margin: float) -> BoundingBox:
        """Expand bounding box outward on all sides by given margin."""
        return BoundingBox(
            self.x0 - margin,
            self.y0 - margin,
            self.x1 + margin,
            self.y1 + margin,
        )

    def transform(self, matrix: Matrix3x3) -> BoundingBox:
        """Transform all 4 corners by affine matrix and construct new AABB."""
        transformed_points = [matrix.transform_point(pt) for pt in self.corners]
        return BoundingBox.from_points(transformed_points)


@dataclass(frozen=True)
class Matrix3x3:
    """Immutable 3x3 homogeneous transformation matrix for 2D affine graphics.

    Representation:
        [ a  b  0 ]   where row 0 = (a, b, 0)
        [ c  d  0 ]   where row 1 = (c, d, 0)
        [ e  f  1 ]   where row 2 = (e, f, 1)

    In PDF / PostScript coordinate space convention:
        [x'  y'  1] = [x  y  1] * Matrix
        x' = a * x + c * y + e
        y' = b * x + d * y + f
    """

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @classmethod
    def identity(cls) -> Matrix3x3:
        """Construct 3x3 identity transformation matrix."""
        return cls(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    @classmethod
    def translation(cls, tx: float, ty: float) -> Matrix3x3:
        """Construct pure translation matrix."""
        return cls(1.0, 0.0, 0.0, 1.0, tx, ty)

    @classmethod
    def scaling(cls, sx: float, sy: float) -> Matrix3x3:
        """Construct scaling matrix."""
        return cls(sx, 0.0, 0.0, sy, 0.0, 0.0)

    @classmethod
    def rotation(cls, theta_radians: float) -> Matrix3x3:
        """Construct rotation matrix (counter-clockwise by theta radians)."""
        cos_t = math.cos(theta_radians)
        sin_t = math.sin(theta_radians)
        return cls(cos_t, sin_t, -sin_t, cos_t, 0.0, 0.0)

    @classmethod
    def skew(cls, alpha_radians: float, beta_radians: float) -> Matrix3x3:
        """Construct skew / shear matrix."""
        tan_a = math.tan(alpha_radians)
        tan_b = math.tan(beta_radians)
        return cls(1.0, tan_a, tan_b, 1.0, 0.0, 0.0)

    @classmethod
    def from_pdf(cls, coeffs: Sequence[float]) -> Matrix3x3:
        """Construct from PDF 6-element array [a, b, c, d, e, f]."""
        if len(coeffs) != 6:
            raise ValueError(f"PDF matrix requires exactly 6 elements, received {len(coeffs)}")
        return cls(
            float(coeffs[0]),
            float(coeffs[1]),
            float(coeffs[2]),
            float(coeffs[3]),
            float(coeffs[4]),
            float(coeffs[5]),
        )

    def to_tuple(self) -> Tuple[float, float, float, float, float, float]:
        """Return (a, b, c, d, e, f) tuple."""
        return (self.a, self.b, self.c, self.d, self.e, self.f)

    def multiply(self, other: Matrix3x3) -> Matrix3x3:
        """Multiply self by other (self * other in row-vector convention: other(self(v))).

        Note: When chaining transformations [x y 1] * A * B,
        result matrix is A.multiply(B).
        """
        a1, b1, c1, d1, e1, f1 = self.a, self.b, self.c, self.d, self.e, self.f
        a2, b2, c2, d2, e2, f2 = other.a, other.b, other.c, other.d, other.e, other.f

        return Matrix3x3(
            a=a1 * a2 + b1 * c2,
            b=a1 * b2 + b1 * d2,
            c=c1 * a2 + d1 * c2,
            d=c1 * b2 + d1 * d2,
            e=e1 * a2 + f1 * c2 + e2,
            f=e1 * b2 + f1 * d2 + f2,
        )

    def __matmul__(self, other: Matrix3x3) -> Matrix3x3:
        return self.multiply(other)

    def determinant(self) -> float:
        """Calculate determinant of the 2x2 linear portion (ad - bc)."""
        return self.a * self.d - self.b * self.c

    def inverse(self) -> Matrix3x3:
        """Calculate inverse matrix.

        Raises:
            ZeroDivisionError: If matrix is degenerate/singular (determinant == 0).
        """
        det = self.determinant()
        if abs(det) < 1e-12:
            raise ZeroDivisionError(f"Cannot invert singular Matrix3x3 (det = {det})")

        inv_det = 1.0 / det
        # Inverse of affine [a b 0; c d 0; e f 1]
        inv_a = self.d * inv_det
        inv_b = -self.b * inv_det
        inv_c = -self.c * inv_det
        inv_d = self.a * inv_det
        inv_e = (self.c * self.f - self.d * self.e) * inv_det
        inv_f = (self.b * self.e - self.a * self.f) * inv_det

        return Matrix3x3(inv_a, inv_b, inv_c, inv_d, inv_e, inv_f)

    def transform_point(self, pt: Point) -> Point:
        """Transform a 2D point [x y 1] * M."""
        nx = self.a * pt.x + self.c * pt.y + self.e
        ny = self.b * pt.x + self.d * pt.y + self.f
        return Point(nx, ny)

    def transform_xy(self, x: float, y: float) -> Tuple[float, float]:
        """Transform coordinate pair (x, y) returning (x', y')."""
        nx = self.a * x + self.c * y + self.e
        ny = self.b * x + self.d * y + self.f
        return (nx, ny)

    def transform_vector(self, dx: float, dy: float) -> Tuple[float, float]:
        """Transform directional vector (dx, dy) ignoring translation (e, f)."""
        return (self.a * dx + self.c * dy, self.b * dx + self.d * dy)

    def transform_bbox(self, bbox: BoundingBox) -> BoundingBox:
        """Transform bounding box corners and compute enclosing axis-aligned box."""
        return bbox.transform(self)

    def decompose(self) -> Tuple[float, float, float, float, float]:
        """Decompose matrix into (scale_x, scale_y, rotation_radians, shear_radians, tx, ty).

        Returns:
            Tuple of (scale_x, scale_y, rotation_radians, tx, ty).
        """
        scale_x = math.hypot(self.a, self.b)
        scale_y = math.hypot(self.c, self.d)

        det = self.determinant()
        if det < 0.0:
            scale_y = -scale_y

        rotation = math.atan2(self.b, self.a)
        return (scale_x, scale_y, rotation, self.e, self.f)


__all__ = [
    "Point",
    "Size",
    "BoundingBox",
    "Matrix3x3",
]
