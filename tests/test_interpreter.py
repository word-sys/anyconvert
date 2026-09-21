"""Unit test suite for Phase 11: Graphics State & Content Stream Interpreter."""

from __future__ import annotations

import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Matrix3x3, Point
from anyconvert.pdf.content.interpreter import (
    ContentInterpreter,
    ImageElement,
    InterpreterOutput,
    TextElement,
    VectorElement,
)
from anyconvert.pdf.graphics.path import VectorPath
from anyconvert.pdf.graphics.state import GraphicsState, GraphicsStateStack, TextState
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFName, PDFStream
from anyconvert.pdf.typography.cmap import CMap


# ==============================================================================
# 1. Graphics State Stack and Path Tests
# ==============================================================================


def test_graphics_state_stack_push_pop() -> None:
    stack = GraphicsStateStack()
    initial = stack.current
    assert initial.line_width == 1.0
    assert initial.fill_color == Color(0, 0, 0, 1.0)

    # Push and mutate
    stack.push()
    stack.current.line_width = 3.5
    stack.current.fill_color = Color(255, 0, 0, 1.0)
    stack.current.ctm = Matrix3x3.translation(100.0, 200.0)

    assert stack.current.line_width == 3.5
    assert stack.current.fill_color == Color(255, 0, 0, 1.0)
    assert stack.current.ctm == Matrix3x3.translation(100.0, 200.0)

    # Pop restores previous state
    stack.pop()
    assert stack.current.line_width == 1.0
    assert stack.current.fill_color == Color(0, 0, 0, 1.0)
    assert stack.current.ctm == Matrix3x3.identity()

    # Underflow protection
    stack.pop()
    assert stack.current.line_width == 1.0


def test_vector_path_construction_and_svg() -> None:
    path = VectorPath()
    assert path.is_empty is True

    path.move_to(10.0, 20.0)
    path.line_to(50.0, 60.0)
    path.curve_to(70.0, 80.0, 90.0, 100.0, 110.0, 120.0)
    path.close_path()

    assert path.is_empty is False
    svg = path.to_svg()
    assert svg == "M 10.00 20.00 L 50.00 60.00 C 70.00 80.00 90.00 100.00 110.00 120.00 Z"

    bbox = path.compute_bbox()
    assert bbox is not None
    assert bbox.x0 == 10.0
    assert bbox.y0 == 20.0
    assert bbox.x1 == 110.0
    assert bbox.y1 == 120.0


def test_vector_path_rectangle_and_ctm_transform() -> None:
    path = VectorPath()
    path.rectangle(0.0, 0.0, 100.0, 50.0)

    # Transform with scaling by 2 and translation (10, 20)
    # [x', y', 1] = [x, y, 1] * Matrix
    # x' = 2*x + 10, y' = 2*y + 20
    ctm = Matrix3x3(2.0, 0.0, 0.0, 2.0, 10.0, 20.0)

    svg = path.to_svg(ctm)
    assert svg == "M 10.00 20.00 L 210.00 20.00 L 210.00 120.00 L 10.00 120.00 Z"

    bbox = path.compute_bbox(ctm)
    assert bbox is not None
    assert bbox.x0 == 10.0
    assert bbox.y0 == 20.0
    assert bbox.x1 == 210.0
    assert bbox.y1 == 120.0


# ==============================================================================
# 2. Content Stream Interpretation Tests
# ==============================================================================


def test_interpreter_path_painting_and_colors() -> None:
    # PDF stream with stroke, fill, colors, and line widths
    stream = """
    1 0 0 1 10 20 cm
    0.5 g
    0 0 100 50 re
    f
    1 0 0 RG
    2 w
    10 10 m 90 40 l S
    """
    interpreter = ContentInterpreter()
    output = interpreter.interpret(stream)

    assert len(output.vector_elements) == 2

    # First element: rectangle fill with 0.5 gray (128, 128, 128)
    el0 = output.vector_elements[0]
    assert el0.fill_color == Color(128, 128, 128, 1.0)
    assert el0.stroke_color is None
    assert el0.fill_rule == "nonzero"
    assert el0.bbox is not None
    assert el0.bbox.x0 == 10.0
    assert el0.bbox.y0 == 20.0
    assert el0.bbox.x1 == 110.0
    assert el0.bbox.y1 == 70.0

    # Second element: line stroke with RGB red (255, 0, 0) and line width 2
    el1 = output.vector_elements[1]
    assert el1.stroke_color == Color(255, 0, 0, 1.0)
    assert el1.fill_color is None
    assert el1.stroke_width == 2.0


def test_interpreter_graphics_state_push_pop_cm() -> None:
    stream = """
    q
      2 0 0 2 0 0 cm
      0 0 10 10 re f
    Q
    0 0 10 10 re f
    """
    interpreter = ContentInterpreter()
    output = interpreter.interpret(stream)

    assert len(output.vector_elements) == 2
    # First: scaled by 2
    assert output.vector_elements[0].bbox == BoundingBox(0.0, 0.0, 20.0, 20.0)
    # Second: unscaled (CTM restored by Q)
    assert output.vector_elements[1].bbox == BoundingBox(0.0, 0.0, 10.0, 10.0)


def test_interpreter_ext_gstate() -> None:
    ext_gstate = PDFDict({
        "GS1": PDFDict({
            "ca": 0.5,
            "CA": 0.8,
            "LW": 4.0,
            "BM": PDFName("Multiply"),
        })
    })
    resources = PDFDict({"ExtGState": ext_gstate})

    stream = """
    /GS1 gs
    0 0 10 10 re f
    """
    interpreter = ContentInterpreter(resources=resources)
    output = interpreter.interpret(stream)

    assert len(output.vector_elements) == 1
    assert output.vector_elements[0].fill_alpha == 0.5
    assert output.vector_elements[0].stroke_alpha == 0.8
    assert output.vector_elements[0].stroke_width == 4.0


def test_interpreter_text_showing_tj() -> None:
    # Test simple text extraction with positioning
    stream = """
    BT
      /F1 12 Tf
      100 200 Td
      (Hello) Tj
    ET
    """
    interpreter = ContentInterpreter()
    output = interpreter.interpret(stream)

    assert len(output.text_elements) == 5
    chars = "".join(e.text for e in output.text_elements)
    assert chars == "Hello"

    # First character 'H' origin is at (100, 200)
    e0 = output.text_elements[0]
    assert e0.origin.x == pytest.approx(100.0, abs=1e-2)
    assert e0.origin.y == pytest.approx(200.0, abs=1e-2)
    assert e0.font_size == 12.0


def test_interpreter_text_kerning_tj_array() -> None:
    # Test TJ operator with kerning offset: [ (A) 100 (V) ]
    # Kerning 100 means -100/1000 * 10 = -1.0 pt displacement
    stream = """
    BT
      /F1 10 Tf
      50 100 Td
      [ (A) 100 (V) ] TJ
    ET
    """
    interpreter = ContentInterpreter()
    output = interpreter.interpret(stream)

    assert len(output.text_elements) == 2
    eA = output.text_elements[0]
    eV = output.text_elements[1]

    assert eA.text == "A"
    assert eV.text == "V"

    # Default width of 'A' is 500 (5.0 pt at size 10)
    # Kern is 100: displaces by -1.0 pt
    # So 'V' origin should be at 50 + 5.0 - 1.0 = 54.0
    assert eA.origin.x == pytest.approx(50.0, abs=1e-2)
    assert eV.origin.x == pytest.approx(54.0, abs=1e-2)


def test_interpreter_text_multiline_td_and_t_star() -> None:
    # Test multiline positioning via T*, Td, and TD
    stream = """
    BT
      /F1 12 Tf
      15 TL
      50 500 Td
      (Line 1) Tj
      T*
      (Line 2) Tj
    ET
    """
    interpreter = ContentInterpreter()
    output = interpreter.interpret(stream)

    line1 = "".join(e.text for e in output.text_elements if e.origin.y == pytest.approx(500.0, abs=1e-2))
    line2 = "".join(e.text for e in output.text_elements if e.origin.y == pytest.approx(485.0, abs=1e-2))

    assert line1 == "Line 1"
    assert line2 == "Line 2"


def test_interpreter_image_and_form_xobjects() -> None:
    # Construct an image XObject and a Form XObject
    img_stream = PDFStream(
        dict=PDFDict({"Type": PDFName("XObject"), "Subtype": PDFName("Image"), "Width": 100, "Height": 100}),
        data=memoryview(b"\x00" * 100),
    )

    form_content = b"0 0 50 50 re f"
    form_stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Form"),
            "BBox": PDFArray([0, 0, 50, 50]),
            "Matrix": PDFArray([2, 0, 0, 2, 10, 10]),
        }),
        data=memoryview(form_content),
    )

    resources = PDFDict({
        "XObject": PDFDict({
            "Im1": img_stream,
            "Fm1": form_stream,
        })
    })

    stream = """
    q
      100 0 0 100 50 50 cm
      /Im1 Do
    Q
    /Fm1 Do
    """
    interpreter = ContentInterpreter(resources=resources)
    output = interpreter.interpret(stream)

    # 1. Image Element
    assert len(output.image_elements) == 1
    img_el = output.image_elements[0]
    assert img_el.name == "Im1"
    assert img_el.bbox == BoundingBox(50.0, 50.0, 150.0, 150.0)

    # 2. Form Element (emits vector from nested stream, scaled by 2 and translated by 10)
    assert len(output.vector_elements) == 1
    form_vec = output.vector_elements[0]
    assert form_vec.bbox == BoundingBox(10.0, 10.0, 110.0, 110.0)


def test_interpreter_composite_font_to_unicode() -> None:
    # Test composite font (Type 0) with /ToUnicode CMap in interpreter
    cmap_text = b"""
    begincmap
    1 begincodespacerange <0000> <FFFF> endcodespacerange
    2 beginbfchar
      <0001> <0048>
      <0002> <0069>
    endbfchar
    endcmap
    """
    to_unicode_stream = PDFStream(dict=PDFDict({"Length": len(cmap_text)}), data=memoryview(cmap_text))

    cid_font = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("CIDFontType2"),
        "BaseFont": PDFName("TestCID"),
        "DW": 1000,
    })

    type0_font = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("Type0"),
        "BaseFont": PDFName("TestCID"),
        "Encoding": PDFName("Identity-H"),
        "DescendantFonts": PDFArray([cid_font]),
        "ToUnicode": to_unicode_stream,
    })

    resources = PDFDict({"Font": PDFDict({"F1": type0_font})})

    # Stream showing 2-byte CIDs: 0x0001 ('H') and 0x0002 ('i')
    stream = """
    BT
      /F1 14 Tf
      10 10 Td
      <00010002> Tj
    ET
    """
    interpreter = ContentInterpreter(resources=resources)
    output = interpreter.interpret(stream)

    assert len(output.text_elements) == 2
    assert output.text_elements[0].text == "H"
    assert output.text_elements[1].text == "i"
    assert output.text_elements[0].font_size == 14.0
