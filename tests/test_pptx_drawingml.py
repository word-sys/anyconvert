from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.pptx import PptxEmitter
from anyconvert.emitters.pptx.shapes import render_vector_shape
from anyconvert.ir.model import (
    DocumentIR,
    DocumentPage,
    Paragraph,
    TextRun,
    VectorBlock,
)
from anyconvert.packaging.opc import OPCPackage


def test_pptx_render_vector_shape_basic() -> None:
    """Test generating PresentationML shape <p:sp> with custom geometry."""
    vec = VectorBlock(
        svg_path="M 50 60 L 150 60 L 150 160 Z",
        bbox=BoundingBox(50.0, 60.0, 150.0, 160.0),
        fill_color=Color(255, 0, 0, 1.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=2.0,
    )
    xml = render_vector_shape(vec, shape_id=201)

    assert '<p:sp>' in xml
    assert '<p:cNvPr id="201" name="Vector_201"/>' in xml
    assert '<a:custGeom>' in xml
    assert '<a:pathLst>' in xml
    assert '<a:moveTo><a:pt x="0" y="0"/></a:moveTo>' in xml
    # 150 - 50 = 100 pt -> 10000 units
    assert '<a:lnTo><a:pt x="10000" y="0"/></a:lnTo>' in xml
    assert '<a:close/>' in xml

    # Check position offsets: 50 pt = 635000 EMU, 60 pt = 762000 EMU
    assert '<a:off x="635000" y="762000"/>' in xml
    # Check extent: 100 pt = 1270000 EMU
    assert '<a:ext cx="1270000" cy="1270000"/>' in xml


def test_pptx_render_vector_shape_fills() -> None:
    """Test PPTX shape fill options: solid, alpha transparency, noFill."""
    # Opaque fill
    v1 = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=Color(0, 128, 255, 1.0),
        stroke_color=None,
    )
    xml1 = render_vector_shape(v1, 1)
    assert '<a:solidFill><a:srgbClr val="0080FF"/></a:solidFill>' in xml1

    # Transparent fill: alpha 0.4 -> 40000
    v2 = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=Color(10, 20, 30, 1.0),
        fill_alpha=0.4,
        stroke_color=None,
    )
    xml2 = render_vector_shape(v2, 2)
    assert '<a:solidFill><a:srgbClr val="0A141E"><a:alpha val="40000"/></a:srgbClr></a:solidFill>' in xml2

    # No fill
    v3 = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=None,
        stroke_color=Color(0, 0, 0, 1.0),
    )
    xml3 = render_vector_shape(v3, 3)
    assert '<a:noFill/>' in xml3


def test_pptx_render_vector_shape_strokes() -> None:
    """Test PPTX shape stroke attributes: width, cap, join, dashes, alpha."""
    # Round cap (rnd), bevel join (<a:bevel/>), dashes [6.0, 3.0], alpha 0.75
    vec = VectorBlock(
        svg_path="M 0 0 L 100 100 Z",
        bbox=BoundingBox(0.0, 0.0, 100.0, 100.0),
        stroke_color=Color(200, 100, 50, 1.0),
        stroke_width=3.0,
        stroke_alpha=0.75,
        line_cap=1,
        line_join=2,
        dash_array=[6.0, 3.0],
    )
    xml = render_vector_shape(vec, 4)

    assert 'cap="rnd"' in xml
    assert '<a:bevel/>' in xml
    assert '<a:custDash>' in xml
    # 6.0 / 3.0 * 100000 = 200000; 3.0 / 3.0 * 100000 = 100000
    assert '<a:ds d="200000" sp="100000"/>' in xml
    assert '<a:alpha val="75000"/>' in xml

    # Miter join and square cap
    vec_sq = VectorBlock(
        svg_path="M 0 0 L 50 50 Z",
        bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=1.0,
        line_cap=2,     # square
        line_join=0,    # miter
        miter_limit=5.0,
    )
    xml_sq = render_vector_shape(vec_sq, 5)
    assert 'cap="sq"' in xml_sq
    assert '<a:miter lim="500000"/>' in xml_sq


def test_pptx_emitter_end_to_end_with_vectors() -> None:
    """Test end-to-end PPTX generation with VectorBlock shapes alongside text."""
    para = Paragraph(
        runs=[TextRun("Slide Title", "Calibri", 28.0, Color(0, 0, 0), is_bold=True)],
        bbox=BoundingBox(50.0, 40.0, 400.0, 80.0),
    )
    # Vector triangle
    triangle = VectorBlock(
        svg_path="M 50 150 L 150 150 L 100 250 Z",
        bbox=BoundingBox(50.0, 150.0, 150.0, 250.0),
        fill_color=Color(0, 150, 255, 1.0),
        stroke_color=Color(0, 50, 150, 1.0),
        stroke_width=2.0,
    )
    # Vector bezier curve annotation
    curve = VectorBlock(
        svg_path="M 200 150 C 250 100 300 200 350 150",
        bbox=BoundingBox(200.0, 100.0, 350.0, 200.0),
        fill_color=None,
        stroke_color=Color(255, 50, 50, 1.0),
        stroke_width=3.0,
        line_cap=1,
    )

    page = DocumentPage(
        page_number=1,
        width=720.0,
        height=540.0,
        blocks=[para, triangle, curve],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = PptxEmitter()
    pptx_bytes = emitter.emit(doc_ir)
    assert len(pptx_bytes) > 0

    pkg = OPCPackage.parse(pptx_bytes)
    assert pkg.has_part("ppt/slides/slide1.xml")
    slide_xml = pkg.get_part("ppt/slides/slide1.xml").content.decode("utf-8")

    # Check slide tree has both text box and custom geometry vector shapes
    assert '<p:spTree>' in slide_xml
    assert 'TextBox' in slide_xml
    assert 'Vector_' in slide_xml
    assert '<a:custGeom>' in slide_xml
    assert '<a:pathLst>' in slide_xml
    assert '<a:cubicBezTo>' in slide_xml
    assert '<a:solidFill><a:srgbClr val="0096FF"/></a:solidFill>' in slide_xml
    assert '<a:solidFill><a:srgbClr val="FF3232"/></a:solidFill>' in slide_xml

    # Verify XML well-formedness
    root = ET.fromstring(slide_xml)
    assert root.tag.endswith("sld")
