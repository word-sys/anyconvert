"""Test suite for Step 22: Native DrawingML Vector Translation for DOCX."""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.docx import DocxEmitter
from anyconvert.emitters.docx.drawing import (
    render_vector_block_flow,
    render_vector_run_canvas,
    svg_path_to_drawingml,
)
from anyconvert.ir.model import (
    DocumentIR,
    DocumentPage,
    Paragraph,
    TextRun,
    VectorBlock,
)
from anyconvert.packaging.opc import OPCPackage


def test_svg_path_to_drawingml_basic() -> None:
    """Test translating SVG path commands M, L, C, Z to DrawingML."""
    svg = "M 10.00 20.00 L 50.00 60.00 C 70.00 80.00 90.00 100.00 110.00 120.00 Z"
    dml = svg_path_to_drawingml(svg, scale=100.0, origin_x=10.0, origin_y=20.0)

    # 10 - 10 = 0, 20 - 20 = 0 -> (0, 0)
    assert '<a:moveTo><a:pt x="0" y="0"/></a:moveTo>' in dml
    # 50 - 10 = 40 -> 4000
    assert '<a:lnTo><a:pt x="4000" y="4000"/></a:lnTo>' in dml
    # 70 - 10 = 60 -> 6000, 110 - 10 = 100 -> 10000
    assert '<a:cubicBezTo>' in dml
    assert '<a:pt x="6000" y="6000"/>' in dml
    assert '<a:pt x="8000" y="8000"/>' in dml
    assert '<a:pt x="10000" y="10000"/>' in dml
    assert '<a:close/>' in dml


def test_svg_path_to_drawingml_multi_subpaths() -> None:
    """Test translating paths with multiple subpaths."""
    svg = "M 0 0 L 10 0 L 10 10 Z M 20 20 L 30 20 L 30 30 Z"
    dml = svg_path_to_drawingml(svg, scale=10.0, origin_x=0.0, origin_y=0.0)

    assert dml.count("<a:moveTo>") == 2
    assert dml.count("<a:close/>") == 2


def test_drawingml_fill_and_alpha() -> None:
    """Test solid fill with and without transparency."""
    # Opaque fill
    vec_opaque = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=Color(255, 0, 0, 1.0),
        stroke_color=None,
    )
    xml_opaque = render_vector_block_flow(vec_opaque, 101)
    assert '<a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>' in xml_opaque

    # Semi-transparent fill (alpha 0.5 -> 50000)
    vec_alpha = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=Color(0, 255, 0, 1.0),
        fill_alpha=0.5,
        stroke_color=None,
    )
    xml_alpha = render_vector_block_flow(vec_alpha, 102)
    assert '<a:solidFill><a:srgbClr val="00FF00"><a:alpha val="50000"/></a:srgbClr></a:solidFill>' in xml_alpha

    # No fill
    vec_nofill = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=None,
        stroke_color=Color(0, 0, 0, 1.0),
    )
    xml_nofill = render_vector_block_flow(vec_nofill, 103)
    assert '<a:noFill/>' in xml_nofill


def test_drawingml_stroke_attributes() -> None:
    """Test line caps, line joins, dashes, and stroke width in DrawingML."""
    # Round caps (cap="rnd"), bevel joins (<a:bevel/>), dashes [4.0, 2.0]
    vec = VectorBlock(
        svg_path="M 0 0 L 100 100 Z",
        bbox=BoundingBox(0.0, 0.0, 100.0, 100.0),
        stroke_color=Color(0, 0, 255, 1.0),
        stroke_width=2.0,
        line_cap=1,     # round
        line_join=2,    # bevel
        dash_array=[4.0, 2.0],
    )
    xml = render_vector_block_flow(vec, 104)

    assert 'cap="rnd"' in xml
    assert '<a:bevel/>' in xml
    assert '<a:custDash>' in xml
    # 4.0 / 2.0 * 100000 = 200000; 2.0 / 2.0 * 100000 = 100000
    assert '<a:ds d="200000" sp="100000"/>' in xml

    # Miter join (<a:miter lim="...">) and flat cap (cap="flat")
    vec_miter = VectorBlock(
        svg_path="M 0 0 L 50 50 Z",
        bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=1.0,
        line_cap=0,     # butt/flat
        line_join=0,    # miter
        miter_limit=8.0,
    )
    xml_miter = render_vector_block_flow(vec_miter, 105)
    assert 'cap="flat"' in xml_miter
    assert '<a:miter lim="800000"/>' in xml_miter


def test_docx_emitter_flow_with_vector_blocks() -> None:
    """Test DOCX emitter generating inline DrawingML shapes in Flow mode."""
    vec = VectorBlock(
        svg_path="M 10 10 L 50 10 L 50 50 L 10 50 Z",
        bbox=BoundingBox(10.0, 10.0, 50.0, 50.0),
        fill_color=Color(255, 200, 0, 1.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=1.5,
    )
    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[
            Paragraph(runs=[TextRun("Above vector shape", "Calibri", 11.0, Color.black())]),
            vec,
            Paragraph(runs=[TextRun("Below vector shape", "Calibri", 11.0, Color.black())]),
        ],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = DocxEmitter()
    docx_bytes = emitter.emit(doc_ir, mode=ConversionMode.FLOW)
    pkg = OPCPackage.parse(docx_bytes)
    doc_xml = pkg.get_part("word/document.xml").content.decode("utf-8")

    assert '<wp:inline' in doc_xml
    assert '<wps:wsp>' in doc_xml
    assert '<a:custGeom>' in doc_xml
    assert '<a:pathLst>' in doc_xml
    assert '<a:solidFill><a:srgbClr val="FFC800"/></a:solidFill>' in doc_xml


def test_docx_emitter_canvas_with_vector_blocks() -> None:
    """Test DOCX emitter generating positioned DrawingML shapes in Canvas mode."""
    vec = VectorBlock(
        svg_path="M 100 200 L 300 200 L 300 400 Z",
        bbox=BoundingBox(100.0, 200.0, 300.0, 400.0),
        fill_color=Color(100, 150, 200, 1.0),
        stroke_color=Color(50, 50, 50, 1.0),
        stroke_width=2.0,
    )
    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[vec],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = DocxEmitter()
    docx_bytes = emitter.emit(doc_ir, mode=ConversionMode.CANVAS)
    pkg = OPCPackage.parse(docx_bytes)
    doc_xml = pkg.get_part("word/document.xml").content.decode("utf-8")

    assert '<wp:anchor' in doc_xml
    assert 'behindDoc="1"' in doc_xml
    assert '<wps:wsp>' in doc_xml
    assert '<a:custGeom>' in doc_xml
    assert '<a:pathLst>' in doc_xml
    # Check that position offset matches bbox: 100 pt = 1270000 EMU, 200 pt = 2540000 EMU
    assert '<wp:posOffset>1270000</wp:posOffset>' in doc_xml
    assert '<wp:posOffset>2540000</wp:posOffset>' in doc_xml
