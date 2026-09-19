"""Unit tests for Phase 2: geometry primitives, affine math, and color models."""

from __future__ import annotations

import math
import unittest

from anyconvert.common.color import (
    BLACK,
    BLUE,
    GREEN,
    RED,
    TRANSPARENT,
    WHITE,
    Color,
)
from anyconvert.common.geometry import (
    BoundingBox,
    Matrix3x3,
    Point,
    Size,
)
from anyconvert.common.logging import configure_logging, get_logger


class TestPoint(unittest.TestCase):
    """Tests for Point primitive."""

    def test_point_arithmetic(self) -> None:
        p1 = Point(10.0, 20.0)
        p2 = Point(5.0, -5.0)

        # Addition
        p_add = p1 + p2
        self.assertEqual(p_add, Point(15.0, 15.0))

        # Subtraction
        p_sub = p1 - p2
        self.assertEqual(p_sub, Point(5.0, 25.0))

        # Multiplication
        p_mul = p1 * 2.5
        self.assertEqual(p_mul, Point(25.0, 50.0))
        p_rmul = 2.5 * p1
        self.assertEqual(p_rmul, Point(25.0, 50.0))

    def test_distance_and_translation(self) -> None:
        p1 = Point(0.0, 0.0)
        p2 = Point(3.0, 4.0)
        self.assertAlmostEqual(p1.distance_to(p2), 5.0)

        p_trans = p1.translate(10.0, -10.0)
        self.assertEqual(p_trans, Point(10.0, -10.0))
        self.assertEqual(p1.to_tuple(), (0.0, 0.0))


class TestSize(unittest.TestCase):
    """Tests for Size primitive."""

    def test_valid_size(self) -> None:
        s = Size(100.0, 200.0)
        self.assertEqual(s.width, 100.0)
        self.assertEqual(s.height, 200.0)
        self.assertEqual(s.area, 20000.0)
        self.assertFalse(s.is_empty)

    def test_empty_size(self) -> None:
        s = Size(0.0, 50.0)
        self.assertTrue(s.is_empty)
        self.assertEqual(s.area, 0.0)

    def test_negative_size_raises(self) -> None:
        with self.assertRaises(ValueError):
            Size(-1.0, 50.0)
        with self.assertRaises(ValueError):
            Size(10.0, -5.0)


class TestBoundingBox(unittest.TestCase):
    """Tests for BoundingBox primitive."""

    def test_properties(self) -> None:
        bbox = BoundingBox(10.0, 20.0, 60.0, 100.0)
        self.assertEqual(bbox.width, 50.0)
        self.assertEqual(bbox.height, 80.0)
        self.assertEqual(bbox.area, 4000.0)
        self.assertEqual(bbox.center, Point(35.0, 60.0))
        self.assertFalse(bbox.is_empty)

    def test_empty_and_normalized(self) -> None:
        # Inverted box
        bbox = BoundingBox(60.0, 100.0, 10.0, 20.0)
        self.assertTrue(bbox.is_empty)
        norm = bbox.normalized()
        self.assertEqual(norm, BoundingBox(10.0, 20.0, 60.0, 100.0))
        self.assertFalse(norm.is_empty)

    def test_contains(self) -> None:
        bbox = BoundingBox(0.0, 0.0, 100.0, 100.0)
        self.assertTrue(bbox.contains_point(Point(50.0, 50.0)))
        self.assertTrue(bbox.contains_point(Point(0.0, 0.0)))
        self.assertTrue(bbox.contains_point(Point(100.0, 100.0)))
        self.assertFalse(bbox.contains_point(Point(100.1, 50.0)))

        inner = BoundingBox(10.0, 10.0, 90.0, 90.0)
        self.assertTrue(bbox.contains_box(inner))
        self.assertFalse(inner.contains_box(bbox))

    def test_intersects_and_intersection(self) -> None:
        b1 = BoundingBox(0.0, 0.0, 50.0, 50.0)
        b2 = BoundingBox(25.0, 25.0, 75.0, 75.0)
        b3 = BoundingBox(60.0, 60.0, 100.0, 100.0)

        self.assertTrue(b1.intersects(b2))
        self.assertTrue(b2.intersects(b3))
        self.assertFalse(b1.intersects(b3))

        inter = b1.intersection(b2)
        self.assertIsNotNone(inter)
        assert inter is not None
        self.assertEqual(inter, BoundingBox(25.0, 25.0, 50.0, 50.0))

        no_inter = b1.intersection(b3)
        self.assertIsNone(no_inter)

    def test_union_and_expand_and_translate(self) -> None:
        b1 = BoundingBox(0.0, 0.0, 50.0, 50.0)
        b2 = BoundingBox(25.0, 25.0, 100.0, 80.0)
        union_box = b1.union(b2)
        self.assertEqual(union_box, BoundingBox(0.0, 0.0, 100.0, 80.0))

        expanded = b1.expand(5.0, 10.0)
        self.assertEqual(expanded, BoundingBox(-5.0, -10.0, 55.0, 60.0))

        trans = b1.translate(10.0, 20.0)
        self.assertEqual(trans, BoundingBox(10.0, 20.0, 60.0, 70.0))

    def test_from_points_and_xywh(self) -> None:
        pts = [Point(10.0, 20.0), Point(-5.0, 15.0), Point(40.0, 80.0)]
        bbox = BoundingBox.from_points(pts)
        self.assertEqual(bbox, BoundingBox(-5.0, 15.0, 40.0, 80.0))

        with self.assertRaises(ValueError):
            BoundingBox.from_points([])

        from_xywh = BoundingBox.from_xywh(10.0, 20.0, 30.0, 40.0)
        self.assertEqual(from_xywh, BoundingBox(10.0, 20.0, 40.0, 60.0))


class TestMatrix3x3(unittest.TestCase):
    """Tests for 3x3 affine transformation matrix."""

    def test_identity(self) -> None:
        ident = Matrix3x3.identity()
        self.assertEqual(ident.to_tuple(), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
        self.assertEqual(ident.determinant, 1.0)
        self.assertTrue(ident.is_invertible)

        p = Point(12.3, 45.6)
        self.assertEqual(ident.transform_point(p), p)

    def test_translation(self) -> None:
        t = Matrix3x3.translation(100.0, 200.0)
        p = Point(10.0, 20.0)
        transformed = t.transform_point(p)
        self.assertEqual(transformed, Point(110.0, 220.0))

    def test_scaling(self) -> None:
        s = Matrix3x3.scaling(2.0, 0.5)
        p = Point(10.0, 20.0)
        transformed = s.transform_point(p)
        self.assertEqual(transformed, Point(20.0, 10.0))

    def test_rotation(self) -> None:
        rot90 = Matrix3x3.rotation_degrees(90.0)
        p = Point(1.0, 0.0)
        res = rot90.transform_point(p)
        self.assertAlmostEqual(res.x, 0.0, places=6)
        self.assertAlmostEqual(res.y, 1.0, places=6)

    def test_matrix_multiplication(self) -> None:
        # Translate then scale
        t = Matrix3x3.translation(10.0, 20.0)
        s = Matrix3x3.scaling(2.0, 3.0)

        # M = T * S -> transform by T, then S
        # p * (T * S) == (p * T) * S
        p = Point(5.0, 6.0)
        m = t @ s

        p_t = t.transform_point(p)  # (15, 26)
        p_ts = s.transform_point(p_t)  # (30, 78)

        p_m = m.transform_point(p)
        self.assertAlmostEqual(p_m.x, p_ts.x)
        self.assertAlmostEqual(p_m.y, p_ts.y)

    def test_inverse(self) -> None:
        t = Matrix3x3.translation(50.0, -30.0)
        s = Matrix3x3.scaling(1.5, 2.5)
        r = Matrix3x3.rotation_degrees(45.0)

        combined = t @ s @ r
        inv = combined.inverse()

        identity_check = combined @ inv
        self.assertAlmostEqual(identity_check.a, 1.0, places=6)
        self.assertAlmostEqual(identity_check.b, 0.0, places=6)
        self.assertAlmostEqual(identity_check.c, 0.0, places=6)
        self.assertAlmostEqual(identity_check.d, 1.0, places=6)
        self.assertAlmostEqual(identity_check.e, 0.0, places=6)
        self.assertAlmostEqual(identity_check.f, 0.0, places=6)

        p = Point(123.45, 678.9)
        p_restored = inv.transform_point(combined.transform_point(p))
        self.assertAlmostEqual(p_restored.x, p.x, places=6)
        self.assertAlmostEqual(p_restored.y, p.y, places=6)

    def test_singular_matrix(self) -> None:
        singular = Matrix3x3(0.0, 0.0, 0.0, 0.0, 1.0, 1.0)
        self.assertFalse(singular.is_invertible)
        with self.assertRaises(ValueError):
            singular.inverse()

    def test_from_pdf_array(self) -> None:
        m = Matrix3x3.from_pdf_array([1, 2, 3, 4, 5, 6])
        self.assertEqual(m.to_list(), [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

        with self.assertRaises(ValueError):
            Matrix3x3.from_pdf_array([1, 2, 3])

    def test_transform_bbox(self) -> None:
        bbox = BoundingBox(0.0, 0.0, 10.0, 10.0)
        t = Matrix3x3.translation(5.0, 15.0)
        transformed = bbox.transform(t)
        self.assertEqual(transformed, BoundingBox(5.0, 15.0, 15.0, 25.0))


class TestColor(unittest.TestCase):
    """Tests for Color model and color conversions."""

    def test_clamping_and_properties(self) -> None:
        c = Color(300, -10, 128, a=1.5)
        self.assertEqual(c.r, 255)
        self.assertEqual(c.g, 0)
        self.assertEqual(c.b, 128)
        self.assertEqual(c.a, 1.0)
        self.assertEqual(c.hex, "FF0080")
        self.assertEqual(c.hex_with_hash, "#FF0080")
        self.assertEqual(c.hex_with_alpha, "FF0080FF")
        self.assertTrue(c.is_opaque)
        self.assertFalse(c.is_transparent)

    def test_gray_conversion(self) -> None:
        c_black = Color.from_gray(0.0)
        self.assertEqual(c_black, Color(0, 0, 0))

        c_white = Color.from_gray(1.0)
        self.assertEqual(c_white, Color(255, 255, 255))

        c_mid = Color.from_gray(0.5)
        self.assertEqual(c_mid.r, 128)
        self.assertEqual(c_mid.g, 128)
        self.assertEqual(c_mid.b, 128)

    def test_cmyk_conversion(self) -> None:
        # Pure Black in CMYK
        black = Color.from_cmyk(0.0, 0.0, 0.0, 1.0)
        self.assertEqual(black, Color(0, 0, 0))

        # Pure White in CMYK
        white = Color.from_cmyk(0.0, 0.0, 0.0, 0.0)
        self.assertEqual(white, Color(255, 255, 255))

        # Cyan: C=1, M=0, Y=0, K=0 -> R=0, G=255, B=255
        cyan = Color.from_cmyk(1.0, 0.0, 0.0, 0.0)
        self.assertEqual(cyan, Color(0, 255, 255))

        # Magenta: C=0, M=1, Y=0, K=0 -> R=255, G=0, B=255
        magenta = Color.from_cmyk(0.0, 1.0, 0.0, 0.0)
        self.assertEqual(magenta, Color(255, 0, 255))

        # Yellow: C=0, M=0, Y=1, K=0 -> R=255, G=255, B=0
        yellow = Color.from_cmyk(0.0, 0.0, 1.0, 0.0)
        self.assertEqual(yellow, Color(255, 255, 0))

        # Roundtrip to_cmyk
        cmyk_vals = cyan.to_cmyk()
        self.assertAlmostEqual(cmyk_vals[0], 1.0)
        self.assertAlmostEqual(cmyk_vals[1], 0.0)
        self.assertAlmostEqual(cmyk_vals[2], 0.0)
        self.assertAlmostEqual(cmyk_vals[3], 0.0)

    def test_hex_parsing(self) -> None:
        # Standard #RRGGBB
        self.assertEqual(Color.from_hex("#FF8000"), Color(255, 128, 0))
        self.assertEqual(Color.from_hex("FF8000"), Color(255, 128, 0))

        # Short #RGB
        self.assertEqual(Color.from_hex("#F80"), Color(255, 136, 0))
        self.assertEqual(Color.from_hex("F80"), Color(255, 136, 0))

        # With alpha #RRGGBBAA
        c_alpha = Color.from_hex("#FF800080")
        self.assertEqual(c_alpha.r, 255)
        self.assertEqual(c_alpha.g, 128)
        self.assertEqual(c_alpha.b, 0)
        self.assertAlmostEqual(c_alpha.a, 128 / 255.0, places=2)

        # Invalid formats
        with self.assertRaises(ValueError):
            Color.from_hex("#INVALID")
        with self.assertRaises(ValueError):
            Color.from_hex("#12")

    def test_alpha_blend_over(self) -> None:
        # Opaque red over opaque blue -> pure red
        blended = RED.blend_over(BLUE)
        self.assertEqual(blended, RED)

        # 50% white over black -> mid gray
        semi_white = WHITE.with_alpha(0.5)
        blended_gray = semi_white.blend_over(BLACK)
        self.assertAlmostEqual(blended_gray.r, 128, delta=1)
        self.assertAlmostEqual(blended_gray.g, 128, delta=1)
        self.assertAlmostEqual(blended_gray.b, 128, delta=1)
        self.assertEqual(blended_gray.a, 1.0)

    def test_logging(self) -> None:
        logger = get_logger("test")
        self.assertEqual(logger.name, "anyconvert.test")
        configure_logging(verbose=True)


if __name__ == "__main__":
    unittest.main()
