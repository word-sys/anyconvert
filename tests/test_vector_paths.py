"""Comprehensive unit and integration tests for Step 21: Vector Path Parser & Curve Decomposition."""

from __future__ import annotations

import math
import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Matrix3x3, Point
from anyconvert.ir.builder import DocumentIRBuilder, _flip_svg_path_y
from anyconvert.ir.model import DocumentPage, VectorBlock
from anyconvert.pdf.content.interpreter import ContentInterpreter, VectorElement
from anyconvert.pdf.graphics.path import (
    ClosePath,
    CurveTo,
    LineTo,
    MoveTo,
    Rectangle,
    SubPath,
    VectorPath,
)
from anyconvert.pdf.graphics.state import GraphicsState
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFName


def test_curve_to_eval_and_split() -> None:
    """Test cubic Bézier curve evaluation and De Casteljau subdivision."""
    p0 = Point(0.0, 0.0)
    p1 = Point(0.0, 10.0)
    p2 = Point(10.0, 10.0)
    p3 = Point(10.0, 0.0)
    curve = CurveTo(p1, p2, p3)

    # Endpoints
    pt0 = curve.eval(0.0, p0)
    assert abs(pt0.x - 0.0) < 1e-6
    assert abs(pt0.y - 0.0) < 1e-6

    pt1 = curve.eval(1.0, p0)
    assert abs(pt1.x - 10.0) < 1e-6
    assert abs(pt1.y - 0.0) < 1e-6

    # Midpoint
    mid = curve.eval(0.5, p0)
    assert abs(mid.x - 5.0) < 1e-6
    assert abs(mid.y - 7.5) < 1e-6

    # De Casteljau split at 0.5
    left, right = curve.split(0.5, p0)
    assert abs(left.p3.x - mid.x) < 1e-6
    assert abs(left.p3.y - mid.y) < 1e-6
    assert abs(right.p3.x - 10.0) < 1e-6


def test_curve_to_extrema_and_polyline() -> None:
    """Test finding curve extrema and adaptive flattening to polyline."""
    p0 = Point(0.0, 0.0)
    curve = CurveTo(Point(0.0, 100.0), Point(100.0, 100.0), Point(100.0, 0.0))

    extrema_t = curve.extrema_t(p0)
    assert len(extrema_t) == 1
    assert abs(extrema_t[0] - 0.5) < 1e-6

    ext_pts = curve.extrema_points(p0)
    assert len(ext_pts) == 1
    assert abs(ext_pts[0].x - 50.0) < 1e-6
    assert abs(ext_pts[0].y - 75.0) < 1e-6

    # Polyline flattening
    poly = curve.to_polyline(p0, tolerance=1.0)
    assert len(poly) >= 4
    # Last point must match target p3
    assert abs(poly[-1].x - 100.0) < 1e-6
    assert abs(poly[-1].y - 0.0) < 1e-6


def test_subpath_decomposition() -> None:
    """Test decomposing VectorPath into discrete subpaths."""
    path = VectorPath()

    # Subpath 1: triangle
    path.move_to(0.0, 0.0)
    path.line_to(10.0, 0.0)
    path.line_to(5.0, 10.0)
    path.close_path()

    # Subpath 2: rectangle
    path.rectangle(20.0, 20.0, 30.0, 40.0)

    # Subpath 3: open curve
    path.move_to(100.0, 100.0)
    path.curve_to(110.0, 120.0, 130.0, 120.0, 140.0, 100.0)

    subpaths = path.decompose_subpaths()
    assert len(subpaths) == 3

    # Check Subpath 1
    assert subpaths[0].is_closed is True
    assert subpaths[0].start_point == Point(0.0, 0.0)
    assert len(subpaths[0].segments) == 4

    # Check Subpath 2
    assert subpaths[1].is_closed is True
    assert subpaths[1].start_point == Point(20.0, 20.0)

    # Check Subpath 3
    assert subpaths[2].is_closed is False
    assert subpaths[2].start_point == Point(100.0, 100.0)
    assert subpaths[2].current_point == Point(140.0, 100.0)


def test_vector_path_transform() -> None:
    """Test transforming entire VectorPath through affine matrix."""
    path = VectorPath()
    path.move_to(10.0, 20.0)
    path.line_to(30.0, 40.0)
    path.close_path()

    # Translate by (5, 10) and scale by 2
    matrix = Matrix3x3(2.0, 0.0, 0.0, 2.0, 5.0, 10.0)
    tr_path = path.transform(matrix)

    assert tr_path.segments[0] == MoveTo(Point(25.0, 50.0))
    assert tr_path.segments[1] == LineTo(Point(65.0, 90.0))
    assert isinstance(tr_path.segments[2], ClosePath)


def test_interpreter_curve_operators_v_and_y() -> None:
    """Test 'v' (replicate p1 from current) and 'y' (replicate p2 from p3) operators."""
    stream = """
    10 20 m
    30 40 50 60 v
    70 80 90 100 y
    S
    """
    interp = ContentInterpreter()
    out = interp.interpret(stream)

    assert len(out.vector_elements) == 1
    vec = out.vector_elements[0]
    tokens = vec.svg_path.split()
    assert tokens[0] == "M"
    assert tokens[1] == "10.00"
    assert tokens[2] == "20.00"
    assert tokens[3] == "C"
    # 'v': p1 replicated from current point (10, 20)
    assert tokens[4] == "10.00"
    assert tokens[5] == "20.00"
    assert tokens[6] == "30.00"
    assert tokens[7] == "40.00"
    assert tokens[8] == "50.00"
    assert tokens[9] == "60.00"
    # 'y': p2 replicated from p3 (90, 100)
    assert tokens[10] == "C"
    assert tokens[11] == "70.00"
    assert tokens[12] == "80.00"
    assert tokens[13] == "90.00"
    assert tokens[14] == "100.00"
    assert tokens[15] == "90.00"
    assert tokens[16] == "100.00"


def test_interpreter_fill_stroke_variations() -> None:
    """Test all fill and stroke operators: s, f, f*, B, B*, b, b*, n."""
    stream = """
    0 0 m 10 0 l 10 10 l s
    0 0 m 20 0 l 20 20 l f
    0 0 m 30 0 l 30 30 l f*
    0 0 m 40 0 l 40 40 l B
    0 0 m 50 0 l 50 50 l B*
    0 0 m 60 0 l 60 60 l b
    0 0 m 70 0 l 70 70 l b*
    0 0 m 80 0 l 80 80 l n
    """
    interp = ContentInterpreter()
    out = interp.interpret(stream)

    # n produces no vector element
    assert len(out.vector_elements) == 7

    # 's' (close and stroke)
    assert out.vector_elements[0].stroke_color is not None
    assert out.vector_elements[0].fill_color is None
    assert "Z" in out.vector_elements[0].svg_path

    # 'f' (nonzero fill)
    assert out.vector_elements[1].fill_rule == "nonzero"
    assert out.vector_elements[1].fill_color is not None
    assert out.vector_elements[1].stroke_color is None

    # 'f*' (evenodd fill)
    assert out.vector_elements[2].fill_rule == "evenodd"
    assert out.vector_elements[2].fill_color is not None

    # 'B' (nonzero fill and stroke)
    assert out.vector_elements[3].fill_rule == "nonzero"
    assert out.vector_elements[3].fill_color is not None
    assert out.vector_elements[3].stroke_color is not None

    # 'B*' (evenodd fill and stroke)
    assert out.vector_elements[4].fill_rule == "evenodd"
    assert out.vector_elements[4].fill_color is not None
    assert out.vector_elements[4].stroke_color is not None

    # 'b' (close, nonzero fill and stroke)
    assert out.vector_elements[5].fill_rule == "nonzero"
    assert out.vector_elements[5].fill_color is not None
    assert out.vector_elements[5].stroke_color is not None
    assert "Z" in out.vector_elements[5].svg_path

    # 'b*' (close, evenodd fill and stroke)
    assert out.vector_elements[6].fill_rule == "evenodd"
    assert out.vector_elements[6].fill_color is not None
    assert out.vector_elements[6].stroke_color is not None
    assert "Z" in out.vector_elements[6].svg_path


def test_interpreter_line_attributes_and_dashes() -> None:
    """Test line cap, line join, miter limit, and dash pattern preservation."""
    stream = """
    2.5 w
    1 J
    2 j
    5.0 M
    [4 2] 1 d
    1 0 0 RG
    0 1 0 rg
    10 10 m 50 50 l S
    """
    interp = ContentInterpreter()
    out = interp.interpret(stream)

    assert len(out.vector_elements) == 1
    vec = out.vector_elements[0]
    assert vec.stroke_width == 2.5
    assert vec.line_cap == 1
    assert vec.line_join == 2
    assert vec.miter_limit == 5.0
    assert vec.dash_array == (4.0, 2.0)
    assert vec.dash_phase == 1.0
    assert vec.stroke_color == Color(255, 0, 0, 1.0)


def test_interpreter_color_space_and_sc_scn() -> None:
    """Test CS/cs and sc/SC/scn/SCN operators for RGB, Gray, and CMYK."""
    stream = """
    /DeviceRGB CS
    1 0.5 0 SC
    /DeviceGray cs
    0.25 sc
    0 0 10 10 re B
    """
    interp = ContentInterpreter()
    out = interp.interpret(stream)

    assert len(out.vector_elements) == 1
    vec = out.vector_elements[0]
    assert vec.stroke_color == Color(255, 127, 0, 1.0)
    assert vec.fill_color == Color(64, 64, 64, 1.0)


def test_interpreter_ext_gstate_miter_limit_and_dash() -> None:
    """Test ExtGState loading of ML and D parameters."""
    res = PDFDict({
        "ExtGState": PDFDict({
            "GS_VEC": PDFDict({
                "LW": 3.0,
                "LC": 2,
                "LJ": 1,
                "ML": 8.0,
                "D": PDFArray([PDFArray([5.0, 2.5]), 0.0]),
                "CA": 0.9,
                "ca": 0.7,
            })
        })
    })
    stream = """
    /GS_VEC gs
    0 0 m 100 100 l S
    """
    interp = ContentInterpreter(resources=res)
    out = interp.interpret(stream)

    assert len(out.vector_elements) == 1
    vec = out.vector_elements[0]
    assert vec.stroke_width == 3.0
    assert vec.line_cap == 2
    assert vec.line_join == 1
    assert vec.miter_limit == 8.0
    assert vec.dash_array == (5.0, 2.5)
    assert vec.dash_phase == 0.0
    assert vec.stroke_alpha == 0.9
    assert vec.fill_alpha == 0.7


def test_ir_builder_vector_block_preservation() -> None:
    """Test that DocumentIRBuilder captures all vector properties into VectorBlock."""
    stream = """
    1.5 w
    1 J
    2 j
    4.0 M
    [3 1] 0.5 d
    0 0 1 RG
    1 1 0 rg
    10 10 m 50 10 l 50 50 l 10 50 l b
    """
    interp = ContentInterpreter()
    out = interp.interpret(stream)

    builder = DocumentIRBuilder()
    doc_page = builder.build_page(
        page_number=1,
        page_width=612.0,
        page_height=792.0,
        output=out,
    )

    vec_blocks = [b for b in doc_page.blocks if isinstance(b, VectorBlock)]
    assert len(vec_blocks) == 1
    vb = vec_blocks[0]
    assert vb.stroke_width == 1.5
    assert vb.line_cap == 1
    assert vb.line_join == 2
    assert vb.miter_limit == 4.0
    assert vb.dash_array == [3.0, 1.0]
    assert vb.dash_phase == 0.5
    assert vb.stroke_color == Color(0, 0, 255, 1.0)
    assert vb.fill_color == Color(255, 255, 0, 1.0)
    assert vb.fill_rule == "nonzero"


def test_flip_svg_path_y_robustness() -> None:
    """Test _flip_svg_path_y handling curves, lines, moves, and close commands."""
    svg = "M 10.00 20.00 L 30.00 40.00 C 50.00 60.00 70.00 80.00 90.00 100.00 Z"
    flipped = _flip_svg_path_y(svg, 200.0)
    tokens = flipped.split()
    assert tokens == [
        "M", "10.00", "180.00",
        "L", "30.00", "160.00",
        "C", "50.00", "140.00", "70.00", "120.00", "90.00", "100.00",
        "Z",
    ]
