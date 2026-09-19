"""Geometric primitives and 2D affine transformation mathematics.

This module provides high-performance, strictly typed geometric primitives:
- Point: 2D coordinate pair (x, y).
- Size: 2D dimension pair (width, height).
- BoundingBox: Axis-aligned bounding box (x0, y0, x1, y1).
- Matrix3x3: 3x3 homogeneous affine transformation matrix adhering to PDF 32000-1 specifications.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


@dataclass(frozen=True, slots=True)
class Point:
    """Represents a 2D point in Euclidean space.

    Attributes:
        x: Horizontal coordinate.
        y: Vertical coordinate.
    """

    x: float
    y: float

    def distance_to(self, other: Point) -> float:
        """Calculate Euclidean distance to another point.

        Args:
            other: Target point.

        Returns:
            float: Euclidean distance between self and other.
        """
        return math.hypot(self.x - other.x, self.y - other.y)

    def translate(self, dx: float, dy: float) -> Point:
        """Return a new point shifted by (dx, dy).

        Args:
            dx: Horizontal displacement.
            dy: Vertical displacement.

        Returns:
            Point: Translated point.
        """
        return Point(self.x + dx, self.y + dy)

    def transform(self, matrix: Matrix3x3) -> Point:
        """Transform this point through a 3x3 affine transformation matrix.

        Args:
            matrix: Affine transformation matrix.

        Returns:
            Point: Transformed point.
        """
        return matrix.transform_point(self)

    def to_tuple(self) -> Tuple[float, float]:
        """Convert point to (x, y) tuple."""
        return (self.x, self.y)

    def __add__(self, other: Point) -> Point:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Point:
        return Point(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Point:
        return self.__mul__(scalar)


@dataclass(frozen=True, slots=True)
class Size:
    """Represents 2D dimensions (width and height).

    Attributes:
        width: Width magnitude (non-negative).
        height: Height magnitude (non-negative).
    """

    width: float
    height: float

    def __post_init__(self) -> None:
        """Validate non-negative dimensions."""
        if self.width < 0.0 or self.height < 0.0:
            raise ValueError(f"Size dimensions must be non-negative, got width={self.width}, height={self.height}")

    @property
    def area(self) -> float:
        """Calculate rectangular area."""
        return self.width * self.height

    @property
    def is_empty(self) -> bool:
        """Return True if either width or height is zero."""
        return self.width == 0.0 or self.height == 0.0

    def to_tuple(self) -> Tuple[float, float]:
        """Convert size to (width, height) tuple."""
        return (self.width, self.height)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Represents an axis-aligned bounding box defined by two corner points (x0, y0) and (x1, y1).

    In anyconvert presentation space, x0 <= x1 and y0 <= y1.
    """

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        """Return horizontal span."""
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        """Return vertical span."""
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        """Return total area of bounding box."""
        return self.width * self.height

    @property
    def center(self) -> Point:
        """Return center point of bounding box."""
        return Point((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def is_empty(self) -> bool:
        """Return True if bounding box has zero or negative area."""
        return self.x1 <= self.x0 or self.y1 <= self.y0

    def normalized(self) -> BoundingBox:
        """Return a normalized bounding box where x0 <= x1 and y0 <= y1."""
        return BoundingBox(
            x0=min(self.x0, self.x1),
            y0=min(self.y0, self.y1),
            x1=max(self.x0, self.x1),
            y1=max(self.y0, self.y1),
        )

    def contains_point(self, point: Point) -> bool:
        """Check if a point lies within or on the boundaries of this box.

        Args:
            point: Point to test.

        Returns:
            bool: True if inside or on boundary.
        """
        return self.x0 <= point.x <= self.x1 and self.y0 <= point.y <= self.y1

    def contains_box(self, other: BoundingBox) -> bool:
        """Check if another bounding box is completely enclosed within this box.

        Args:
            other: Bounding box to test.

        Returns:
            bool: True if completely contained.
        """
        return (
            self.x0 <= other.x0
            and self.y0 <= other.y0
            and self.x1 >= other.x1
            and self.y1 >= other.y1
        )

    def intersects(self, other: BoundingBox) -> bool:
        """Check if this bounding box intersects with another box.

        Args:
            other: Bounding box to test.

        Returns:
            bool: True if there is a non-empty overlapping region.
        """
        return not (
            self.x1 < other.x0
            or self.x0 > other.x1
            or self.y1 < other.y0
            or self.y0 > other.y1
        )

    def intersection(self, other: BoundingBox) -> BoundingBox | None:
        """Compute the intersection of this box with another.

        Args:
            other: Bounding box to intersect with.

        Returns:
            Optional[BoundingBox]: Intersected bounding box, or None if no overlap.
        """
        ix0 = max(self.x0, other.x0)
        iy0 = max(self.y0, other.y0)
        ix1 = min(self.x1, other.x1)
        iy1 = min(self.y1, other.y1)

        if ix0 > ix1 or iy0 > iy1:
            return None
        return BoundingBox(ix0, iy0, ix1, iy1)

    def union(self, other: BoundingBox) -> BoundingBox:
        """Compute the minimal bounding box enclosing both this box and another.

        Args:
            other: Bounding box to merge.

        Returns:
            BoundingBox: Enclosing union box.
        """
        return BoundingBox(
            x0=min(self.x0, other.x0),
            y0=min(self.y0, other.y0),
            x1=max(self.x1, other.x1),
            y1=max(self.y1, other.y1),
        )

    def expand(self, dx: float, dy: float | None = None) -> BoundingBox:
        """Expand or shrink bounding box boundaries by delta margins.

        Args:
            dx: Horizontal margin expansion (both left and right).
            dy: Vertical margin expansion (both top and bottom). Defaults to dx.

        Returns:
            BoundingBox: Expanded bounding box.
        """
        v_dy = dx if dy is None else dy
        return BoundingBox(
            x0=self.x0 - dx,
            y0=self.y0 - v_dy,
            x1=self.x1 + dx,
            y1=self.y1 + v_dy,
        )

    def translate(self, dx: float, dy: float) -> BoundingBox:
        """Translate bounding box by (dx, dy).

        Args:
            dx: Horizontal offset.
            dy: Vertical offset.

        Returns:
            BoundingBox: Translated bounding box.
        """
        return BoundingBox(
            x0=self.x0 + dx,
            y0=self.y0 + dy,
            x1=self.x1 + dx,
            y1=self.y1 + dy,
        )

    def transform(self, matrix: Matrix3x3) -> BoundingBox:
        """Transform all 4 corners through an affine matrix and return the new axis-aligned bounding box.

        Args:
            matrix: 3x3 affine transformation matrix.

        Returns:
            BoundingBox: Transformed axis-aligned bounding box.
        """
        corners = [
            Point(self.x0, self.y0),
            Point(self.x1, self.y0),
            Point(self.x0, self.y1),
            Point(self.x1, self.y1),
        ]
        transformed = [matrix.transform_point(p) for p in corners]
        return BoundingBox.from_points(transformed)

    @classmethod
    def from_points(cls, points: Iterable[Point]) -> BoundingBox:
        """Construct the minimal bounding box enclosing an iterable of points.

        Args:
            points: Sequence or iterable of points.

        Returns:
            BoundingBox: Minimal enclosing bounding box.

        Raises:
            ValueError: If points iterable is empty.
        """
        pts = list(points)
        if not pts:
            raise ValueError("Cannot construct BoundingBox from empty point sequence")

        x0 = min(p.x for p in pts)
        y0 = min(p.y for p in pts)
        x1 = max(p.x for p in pts)
        y1 = max(p.y for p in pts)
        return cls(x0=x0, y0=y0, x1=x1, y1=y1)

    @classmethod
    def from_xywh(cls, x: float, y: float, width: float, height: float) -> BoundingBox:
        """Construct bounding box from origin and dimensions."""
        return cls(x0=x, y0=y, x1=x + width, y1=y + height)

    def to_tuple(self) -> Tuple[float, float, float, float]:
        """Convert to (x0, y0, x1, y1) tuple."""
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass(frozen=True, slots=True)
class Matrix3x3:
    """Represents a 3x3 2D affine transformation matrix.

    In accordance with PDF 32000-1:2008 (§8.3.3), 2D transformations are represented
    by a six-element array [a, b, c, d, e, f] representing the matrix:
        [ a  b  0 ]
        [ c  d  0 ]
        [ e  f  1 ]

    Coordinates are represented as row vectors [x, y, 1], such that:
        [x', y', 1] = [x, y, 1] * Matrix
        x' = a*x + c*y + e
        y' = b*x + d*y + f
    """

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @classmethod
    def identity(cls) -> Matrix3x3:
        """Create a 3x3 identity matrix."""
        return cls(a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0)

    @classmethod
    def translation(cls, tx: float, ty: float) -> Matrix3x3:
        """Create a translation matrix."""
        return cls(a=1.0, b=0.0, c=0.0, d=1.0, e=tx, f=ty)

    @classmethod
    def scaling(cls, sx: float, sy: float) -> Matrix3x3:
        """Create a scaling matrix."""
        return cls(a=sx, b=0.0, c=0.0, d=sy, e=0.0, f=0.0)

    @classmethod
    def rotation(cls, angle_radians: float) -> Matrix3x3:
        """Create a rotation matrix from an angle in radians (counterclockwise)."""
        cos_theta = math.cos(angle_radians)
        sin_theta = math.sin(angle_radians)
        return cls(a=cos_theta, b=sin_theta, c=-sin_theta, d=cos_theta, e=0.0, f=0.0)

    @classmethod
    def rotation_degrees(cls, angle_degrees: float) -> Matrix3x3:
        """Create a rotation matrix from an angle in degrees."""
        return cls.rotation(math.radians(angle_degrees))

    @classmethod
    def skew(cls, alpha_rad: float, beta_rad: float) -> Matrix3x3:
        """Create a skew matrix from horizontal and vertical shear angles in radians."""
        tan_alpha = math.tan(alpha_rad)
        tan_beta = math.tan(beta_rad)
        return cls(a=1.0, b=tan_alpha, c=tan_beta, d=1.0, e=0.0, f=0.0)

    @classmethod
    def from_pdf_array(cls, values: Sequence[float]) -> Matrix3x3:
        """Create matrix from a 6-element PDF array [a, b, c, d, e, f]."""
        if len(values) != 6:
            raise ValueError(f"PDF matrix array must contain exactly 6 elements, got {len(values)}")
        return cls(
            a=float(values[0]),
            b=float(values[1]),
            c=float(values[2]),
            d=float(values[3]),
            e=float(values[4]),
            f=float(values[5]),
        )

    @property
    def determinant(self) -> float:
        """Calculate matrix determinant (a*d - b*c)."""
        return self.a * self.d - self.b * self.c

    @property
    def is_invertible(self) -> bool:
        """Return True if matrix has a non-zero determinant."""
        return abs(self.determinant) > 1e-12

    def multiply(self, other: Matrix3x3) -> Matrix3x3:
        """Multiply this matrix by another (self * other).

        In row-vector transformation:
            [x, y, 1] * (M1 * M2) == ([x, y, 1] * M1) * M2

        Args:
            other: Matrix to multiply on the right.

        Returns:
            Matrix3x3: Result of matrix multiplication.
        """
        return Matrix3x3(
            a=self.a * other.a + self.b * other.c,
            b=self.a * other.b + self.b * other.d,
            c=self.c * other.a + self.d * other.c,
            d=self.c * other.b + self.d * other.d,
            e=self.e * other.a + self.f * other.c + other.e,
            f=self.e * other.b + self.f * other.d + other.f,
        )

    def __matmul__(self, other: Matrix3x3) -> Matrix3x3:
        """Overload @ operator for matrix multiplication."""
        return self.multiply(other)

    def inverse(self) -> Matrix3x3:
        """Calculate the inverse matrix.

        Returns:
            Matrix3x3: Inverted matrix.

        Raises:
            ValueError: If matrix is singular (determinant is zero).
        """
        det = self.determinant
        if abs(det) <= 1e-12:
            raise ValueError(f"Cannot invert singular matrix with determinant={det}")

        inv_det = 1.0 / det
        inv_a = self.d * inv_det
        inv_b = -self.b * inv_det
        inv_c = -self.c * inv_det
        inv_d = self.a * inv_det
        inv_e = (self.c * self.f - self.d * self.e) * inv_det
        inv_f = (self.b * self.e - self.a * self.f) * inv_det

        return Matrix3x3(
            a=inv_a,
            b=inv_b,
            c=inv_c,
            d=inv_d,
            e=inv_e,
            f=inv_f,
        )

    def transform_point(self, point: Point) -> Point:
        """Transform a 2D point [x, y, 1] through this matrix.

        Args:
            point: Point to transform.

        Returns:
            Point: Transformed point.
        """
        nx = self.a * point.x + self.c * point.y + self.e
        ny = self.b * point.x + self.d * point.y + self.f
        return Point(nx, ny)

    def transform_xy(self, x: float, y: float) -> Tuple[float, float]:
        """Transform (x, y) coordinates through this matrix.

        Args:
            x: X coordinate.
            y: Y coordinate.

        Returns:
            Tuple[float, float]: Transformed (x', y').
        """
        nx = self.a * x + self.c * y + self.e
        ny = self.b * x + self.d * y + self.f
        return (nx, ny)

    def transform_bbox(self, bbox: BoundingBox) -> BoundingBox:
        """Transform an axis-aligned bounding box through this matrix."""
        return bbox.transform(self)

    def to_tuple(self) -> Tuple[float, float, float, float, float, float]:
        """Convert matrix components to (a, b, c, d, e, f) tuple."""
        return (self.a, self.b, self.c, self.d, self.e, self.f)

    def to_list(self) -> List[float]:
        """Convert matrix components to [a, b, c, d, e, f] list."""
        return [self.a, self.b, self.c, self.d, self.e, self.f]
