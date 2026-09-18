"""Test suite for Phase 2: Fundamental Math, Geometry & Color Primitives."""

from __future__ import annotations

import math
import unittest

from anyconvert.common.color import (
    BLACK,
    Color,
    TRANSPARENT,
    WHITE,
)
from anyconvert.common.geometry import (
    BoundingBox,
    Matrix3x3,
    Point,
    Size,
)


class TestGeometryPrimitives(unittest.TestCase):
    """Test Point, Size, and BoundingBox behaviors."""

    def test_point_arithmetic(self) -> None:
        p1 = Point(10.0, 20.0)
        p2 = Point(5.0, -10.0)

        # Addition
        p_add = p1 + p2
        self.assertAlmostEqual(p_add.x, 15.0)
        self.assertAlmostEqual(p_add.y, 10.0)

        # Subtraction
        p_sub = p1 - p2
        self.assertAlmostEqual(p_sub.x, 5.0)
        self.assertAlmostEqual(p_sub.y, 30.0)

        # Scalar multiplication
        p_mul = p1 * 2.5
        self.assertAlmostEqual(p_mul.x, 25.0)
        self.assertAlmostEqual(p_mul.y, 50.0)
        p_rmul = 2.5 * p1
        self.assertAlmostEqual(p_rmul.x, 25.0)

        # Distance
        self.assertAlmostEqual(Point(0.0, 0.0).distance_to(Point(3.0, 4.0)), 5.0)
        self.assertEqual(p1.as_tuple(), (10.0, 20.0))

    def test_size_properties(self) -> None:
        s = Size(100.0, 50.0)
        self.assertEqual(s.width, 100.0)
        self.assertEqual(s.height, 50.0)
        self.assertEqual(s.area, 5000.0)
        self.assertFalse(s.is_empty)

        # Negative values clamp to 0.0
        s_neg = Size(-10.0, 20.0)
        self.assertEqual(s_neg.width, 0.0)
        self.assertTrue(s_neg.is_empty)

    def test_bounding_box_normalization(self) -> None:
        # Inverted coordinates should auto-normalize
        bb = BoundingBox(100.0, 200.0, 10.0, 50.0)
        self.assertEqual(bb.x0, 10.0)
        self.assertEqual(bb.y0, 50.0)
        self.assertEqual(bb.x1, 100.0)
        self.assertEqual(bb.y1, 200.0)
        self.assertEqual(bb.width, 90.0)
        self.assertEqual(bb.height, 150.0)
        self.assertEqual(bb.center, Point(55.0, 125.0))

    def test_bounding_box_intersection_and_union(self) -> None:
        b1 = BoundingBox(0.0, 0.0, 100.0, 100.0)
        b2 = BoundingBox(50.0, 50.0, 150.0, 150.0)

        self.assertTrue(b1.intersects(b2))
        inter = b1.intersection(b2)
        self.assertIsNotNone(inter)
        assert inter is not None
        self.assertEqual(inter, BoundingBox(50.0, 50.0, 100.0, 100.0))
        self.assertEqual(inter.area, 2500.0)

        # Union
        uni = b1.union(b2)
        self.assertEqual(uni, BoundingBox(0.0, 0.0, 150.0, 150.0))

        # Disjoint
        b3 = BoundingBox(200.0, 200.0, 300.0, 300.0)
        self.assertFalse(b1.intersects(b3))
        self.assertIsNone(b1.intersection(b3))

    def test_bounding_box_containment_and_overlap(self) -> None:
        b1 = BoundingBox(0.0, 0.0, 100.0, 100.0)
        self.assertTrue(b1.contains_point(Point(50.0, 50.0)))
        self.assertTrue(b1.contains_point(Point(0.0, 0.0)))
        self.assertFalse(b1.contains_point(Point(101.0, 50.0)))

        b_sub = BoundingBox(10.0, 10.0, 90.0, 90.0)
        self.assertTrue(b1.contains_box(b_sub))
        self.assertFalse(b_sub.contains_box(b1))

        # Horizontal and vertical overlap
        b2 = BoundingBox(50.0, 20.0, 150.0, 80.0)
        self.assertAlmostEqual(b1.horizontal_overlap(b2), 50.0)
        self.assertAlmostEqual(b1.vertical_overlap(b2), 60.0)

    def test_bounding_box_iou(self) -> None:
        b1 = BoundingBox(0.0, 0.0, 100.0, 100.0)
        # Identical boxes have IoU 1.0
        self.assertAlmostEqual(b1.iou(b1), 1.0)

        # b1 area = 10000; b2 area = 10000; overlap = 50x50 = 2500
        # union = 10000 + 10000 - 2500 = 17500; IoU = 2500 / 17500 = 1 / 7
        b2 = BoundingBox(50.0, 50.0, 150.0, 150.0)
        self.assertAlmostEqual(b1.iou(b2), 2500.0 / 17500.0)

        # Disjoint boxes have IoU 0.0
        b3 = BoundingBox(200.0, 200.0, 300.0, 300.0)
        self.assertAlmostEqual(b1.iou(b3), 0.0)


class TestMatrix3x3(unittest.TestCase):
    """Test 3x3 affine transformation matrix math."""

    def test_identity(self) -> None:
        ident = Matrix3x3.identity()
        p = Point(42.0, -17.0)
        tp = ident.transform_point(p)
        self.assertAlmostEqual(tp.x, 42.0)
        self.assertAlmostEqual(tp.y, -17.0)
        self.assertAlmostEqual(ident.determinant(), 1.0)

    def test_translation(self) -> None:
        trans = Matrix3x3.translation(10.0, -25.0)
        p = Point(5.0, 5.0)
        tp = trans.transform_point(p)
        self.assertAlmostEqual(tp.x, 15.0)
        self.assertAlmostEqual(tp.y, -20.0)

    def test_scaling(self) -> None:
        scale = Matrix3x3.scaling(2.0, 3.0)
        p = Point(10.0, 20.0)
        tp = scale.transform_point(p)
        self.assertAlmostEqual(tp.x, 20.0)
        self.assertAlmostEqual(tp.y, 60.0)

    def test_rotation(self) -> None:
        # Rotate 90 degrees CCW (pi / 2 radians)
        rot = Matrix3x3.rotation(math.pi / 2.0)
        p = Point(1.0, 0.0)
        tp = rot.transform_point(p)
        self.assertAlmostEqual(tp.x, 0.0, places=5)
        self.assertAlmostEqual(tp.y, 1.0, places=5)

    def test_multiplication_and_chaining(self) -> None:
        # Translate then scale
        trans = Matrix3x3.translation(10.0, 20.0)
        scale = Matrix3x3.scaling(2.0, 2.0)

        # Chained: P * trans * scale
        combined = trans @ scale
        p = Point(5.0, 5.0)
        # (5 + 10) * 2 = 30, (5 + 20) * 2 = 50
        tp = combined.transform_point(p)
        self.assertAlmostEqual(tp.x, 30.0)
        self.assertAlmostEqual(tp.y, 50.0)

    def test_inversion(self) -> None:
        rot = Matrix3x3.rotation(0.785)
        scale = Matrix3x3.scaling(1.5, 2.5)
        trans = Matrix3x3.translation(100.0, -50.0)
        m = trans @ rot @ scale

        inv_m = m.inverse()
        ident_approx = m @ inv_m

        self.assertAlmostEqual(ident_approx.a, 1.0, places=5)
        self.assertAlmostEqual(ident_approx.b, 0.0, places=5)
        self.assertAlmostEqual(ident_approx.c, 0.0, places=5)
        self.assertAlmostEqual(ident_approx.d, 1.0, places=5)
        self.assertAlmostEqual(ident_approx.e, 0.0, places=5)
        self.assertAlmostEqual(ident_approx.f, 0.0, places=5)

        # Inversion of singular matrix should raise ZeroDivisionError
        singular = Matrix3x3(0.0, 0.0, 0.0, 0.0, 10.0, 20.0)
        with self.assertRaises(ZeroDivisionError):
            singular.inverse()

    def test_transform_bbox(self) -> None:
        box = BoundingBox(0.0, 0.0, 10.0, 20.0)
        # Scale 2x and translate (5, 5)
        m = Matrix3x3.scaling(2.0, 2.0) @ Matrix3x3.translation(5.0, 5.0)
        tb = box.transform(m)
        self.assertAlmostEqual(tb.x0, 5.0)
        self.assertAlmostEqual(tb.y0, 5.0)
        self.assertAlmostEqual(tb.x1, 25.0)
        self.assertAlmostEqual(tb.y1, 45.0)


class TestColorPrimitives(unittest.TestCase):
    """Test Color representation and conversions."""

    def test_color_rgb_and_hex(self) -> None:
        c = Color(255, 128, 0)
        self.assertEqual(c.hex, "FF8000")
        self.assertEqual(c.hex_with_hash, "#FF8000")
        self.assertEqual(c.rgba_hex, "FF8000FF")

    def test_color_clamping(self) -> None:
        c = Color(-10, 300, 128, a=1.5)
        self.assertEqual(c.r, 0)
        self.assertEqual(c.g, 255)
        self.assertEqual(c.b, 128)
        self.assertEqual(c.a, 1.0)

    def test_from_rgb_float(self) -> None:
        c = Color.from_rgb_float(1.0, 0.5, 0.0)
        self.assertEqual(c.r, 255)
        self.assertEqual(c.g, 128)
        self.assertEqual(c.b, 0)

    def test_from_gray(self) -> None:
        black = Color.from_gray(0.0)
        self.assertEqual(black, BLACK)
        white = Color.from_gray(1.0)
        self.assertEqual(white, WHITE)
        mid = Color.from_gray(0.5)
        self.assertEqual(mid.r, 128)
        self.assertEqual(mid.g, 128)
        self.assertEqual(mid.b, 128)

    def test_from_cmyk(self) -> None:
        # Pure Black: K=1.0 -> R=0, G=0, B=0
        black_cmyk = Color.from_cmyk(0.0, 0.0, 0.0, 1.0)
        self.assertEqual(black_cmyk.r, 0)
        self.assertEqual(black_cmyk.g, 0)
        self.assertEqual(black_cmyk.b, 0)

        # Pure White: C=0, M=0, Y=0, K=0 -> R=255, G=255, B=255
        white_cmyk = Color.from_cmyk(0.0, 0.0, 0.0, 0.0)
        self.assertEqual(white_cmyk.r, 255)
        self.assertEqual(white_cmyk.g, 255)
        self.assertEqual(white_cmyk.b, 255)

        # Pure Cyan: C=1, M=0, Y=0, K=0 -> R=0, G=255, B=255
        cyan_cmyk = Color.from_cmyk(1.0, 0.0, 0.0, 0.0)
        self.assertEqual(cyan_cmyk.r, 0)
        self.assertEqual(cyan_cmyk.g, 255)
        self.assertEqual(cyan_cmyk.b, 255)

    def test_from_hex(self) -> None:
        # #RGB
        c3 = Color.from_hex("#F80")
        self.assertEqual(c3.hex, "FF8800")
        self.assertEqual(c3.a, 1.0)

        # #RRGGBB
        c6 = Color.from_hex("#336699")
        self.assertEqual(c6.r, 0x33)
        self.assertEqual(c6.g, 0x66)
        self.assertEqual(c6.b, 0x99)
        self.assertEqual(c6.a, 1.0)

        # #RRGGBBAA
        c8 = Color.from_hex("#33669980")
        self.assertEqual(c8.r, 0x33)
        self.assertAlmostEqual(c8.a, 0x80 / 255.0, places=2)

        # Without hash
        c_nohash = Color.from_hex("00FF00")
        self.assertEqual(c_nohash.r, 0)
        self.assertEqual(c_nohash.g, 255)
        self.assertEqual(c_nohash.b, 0)

        # Invalid
        with self.assertRaises(ValueError):
            Color.from_hex("not-a-color")

    def test_transparency_and_luminance(self) -> None:
        self.assertTrue(TRANSPARENT.is_transparent)
        self.assertFalse(BLACK.is_transparent)

        self.assertAlmostEqual(BLACK.luminance, 0.0)
        self.assertAlmostEqual(WHITE.luminance, 1.0)
        self.assertTrue(BLACK.is_dark)
        self.assertFalse(WHITE.is_dark)


if __name__ == "__main__":
    unittest.main()
